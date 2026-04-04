#!/usr/bin/env python3
"""
PrisilBlast - VPS Blast Manager Server
Mengelola Docker containers per user
Port: 8766
"""

from flask import Flask, request, jsonify
import subprocess, json, os, time, threading, hashlib
import urllib.request, urllib.parse

app = Flask(__name__)

# Config
PORT = 8766
CLOUDINARY_URL = "https://api.cloudinary.com/v1_1/dwmb6shgh/image/upload"
CLOUDINARY_PRESET = "prisilblast_qr"
BLAST_IMAGE = "wa_blast_image"
WORKSPACE = "/home/aldog/.openclaw/workspace"
API_SECRET = "prisilblast_vps_secret_2026"

# State per session
sessions = {}  # sessionId -> { userId, nomor, status, containerId }

def verify_secret(req):
    return req.headers.get('X-Secret') == API_SECRET

def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip(), result.returncode

def upload_to_cloudinary(image_path, public_id):
    """Upload gambar ke Cloudinary, return URL"""
    try:
        import base64
        with open(image_path, 'rb') as f:
            img_data = base64.b64encode(f.read()).decode()
        
        data = urllib.parse.urlencode({
            'file': f'data:image/png;base64,{img_data}',
            'upload_preset': CLOUDINARY_PRESET,
            'public_id': public_id,
        }).encode()
        
        req = urllib.request.Request(CLOUDINARY_URL, data=data)
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            return result.get('secure_url')
    except Exception as e:
        print(f"Cloudinary error: {e}")
        return None

def get_container_name(user_id):
    return f"pb_{hashlib.md5(user_id.encode()).hexdigest()[:8]}"

def get_volume_name(user_id):
    return f"pb_vol_{hashlib.md5(user_id.encode()).hexdigest()[:8]}"

def poll_qr(session_id, user_id, contacts_file, template):
    """Background thread: poll QR dan update status"""
    container = get_container_name(user_id)
    
    for i in range(60):  # max 5 menit
        time.sleep(5)
        
        # Screenshot dari container
        screenshot_path = f"/tmp/qr_{session_id}.png"
        out, code = run_cmd(f"docker exec {container} python3 -c \"\nimport sys; sys.path.insert(0,'/app')\nfrom playwright.sync_api import sync_playwright\nimport time\nwith sync_playwright() as p:\n    ctx = p.chromium.connect_over_cdp('http://localhost:9222') if False else None\n\" 2>/dev/null; docker cp {container}:/tmp/wa_debug.png {screenshot_path} 2>/dev/null")
        
        if os.path.exists(screenshot_path):
            # Upload ke Cloudinary
            url = upload_to_cloudinary(screenshot_path, f"qr_{session_id}")
            if url:
                sessions[session_id]['qrUrl'] = url
                sessions[session_id]['status'] = 'waiting_scan'
        
        # Cek apakah sudah connected
        out, _ = run_cmd(f"docker logs {container} --tail 5 2>/dev/null")
        if 'WhatsApp siap' in out:
            sessions[session_id]['status'] = 'connected'
            print(f"[{session_id}] WhatsApp connected!")
            break
        
        if i == 0 or i % 6 == 0:
            print(f"[{session_id}] Waiting for QR scan... ({i*5}s)")

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'version': '1.0'})

@app.route('/connect', methods=['POST'])
def connect_wa():
    """Spawn Docker container untuk user"""
    if not verify_secret(request):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    user_id = data.get('userId')
    nomor = data.get('nomor')
    
    if not user_id or not nomor:
        return jsonify({'error': 'userId dan nomor wajib diisi'}), 400
    
    container = get_container_name(user_id)
    volume = get_volume_name(user_id)
    session_id = hashlib.md5(f"{user_id}_{nomor}".encode()).hexdigest()[:12]
    
    # Stop container lama kalau ada
    run_cmd(f"docker stop {container} 2>/dev/null; docker rm {container} 2>/dev/null")
    
    # Buat contacts file placeholder
    contacts_path = f"/tmp/contacts_{session_id}.csv"
    with open(contacts_path, 'w') as f:
        f.write("nama,nomor\n")
    
    # Jalankan container baru
    cmd = f"""docker run -d \
        --name {container} \
        --network host \
        -v {volume}:/app/wa_session \
        -v {contacts_path}:/app/contacts.csv \
        -e LOG_FILE=/tmp/blast_log_{session_id}.json \
        {BLAST_IMAGE}"""
    
    out, code = run_cmd(cmd)
    if code != 0:
        return jsonify({'error': f'Gagal spawn container: {out}'}), 500
    
    # Simpan session
    sessions[session_id] = {
        'userId': user_id,
        'nomor': nomor,
        'container': container,
        'volume': volume,
        'status': 'starting',
        'qrUrl': None,
        'sent': 0,
        'failed': 0,
        'total': 0,
        'contactsPath': contacts_path,
        'startedAt': time.time()
    }
    
    # Background thread untuk poll QR
    t = threading.Thread(target=poll_qr, args=(session_id, user_id, contacts_path, ''))
    t.daemon = True
    t.start()
    
    return jsonify({'success': True, 'sessionId': session_id})

@app.route('/qr-status', methods=['GET'])
def qr_status():
    """Cek status QR dan koneksi"""
    if not verify_secret(request):
        return jsonify({'error': 'Unauthorized'}), 401
    
    session_id = request.args.get('sessionId')
    if not session_id or session_id not in sessions:
        return jsonify({'error': 'Session tidak ditemukan'}), 404
    
    sess = sessions[session_id]
    
    # Cek log container
    container = sess['container']
    out, _ = run_cmd(f"docker logs {container} --tail 10 2>/dev/null")
    
    if 'WhatsApp siap' in out:
        sess['status'] = 'connected'
    
    return jsonify({
        'status': sess['status'],
        'qrUrl': sess.get('qrUrl'),
        'nomor': sess['nomor']
    })

@app.route('/upload-contacts', methods=['POST'])
def upload_contacts():
    """Simpan kontak CSV ke path container"""
    if not verify_secret(request):
        return jsonify({'error': 'Unauthorized'}), 401
    
    session_id = request.args.get('sessionId')
    if not session_id or session_id not in sessions:
        return jsonify({'error': 'Session tidak ditemukan'}), 404
    
    csv_content = request.data.decode('utf-8')
    sess = sessions[session_id]
    contacts_path = sess['contactsPath']
    
    with open(contacts_path, 'w', encoding='utf-8') as f:
        f.write(csv_content)
    
    # Copy ke container
    container = sess['container']
    run_cmd(f"docker cp {contacts_path} {container}:/app/contacts.csv")
    
    # Hitung total kontak
    lines = [l for l in csv_content.strip().split('\n') if l.strip()]
    total = max(0, len(lines) - 1)  # minus header
    sess['total'] = total
    
    return jsonify({'success': True, 'total': total})

@app.route('/start-blast', methods=['POST'])
def start_blast():
    """Mulai blast dengan template"""
    if not verify_secret(request):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    session_id = data.get('sessionId')
    template = data.get('template', '')
    
    if not session_id or session_id not in sessions:
        return jsonify({'error': 'Session tidak ditemukan'}), 404
    
    sess = sessions[session_id]
    container = sess['container']
    
    # Set template di container via env
    template_path = f"/tmp/template_{session_id}.txt"
    with open(template_path, 'w', encoding='utf-8') as f:
        f.write(template)
    run_cmd(f"docker cp {template_path} {container}:/app/template.txt")
    
    # Restart container dengan blast mode
    run_cmd(f"docker restart {container}")
    
    sess['status'] = 'blasting'
    sess['sent'] = 0
    sess['failed'] = 0
    
    # Background polling progress
    def poll_progress():
        while sess.get('status') == 'blasting':
            time.sleep(10)
            out, _ = run_cmd(f"docker logs {container} --tail 20 2>/dev/null")
            
            sent = out.count('✅')
            failed = out.count('❌')
            sess['sent'] = max(sess.get('sent', 0), sent)
            sess['failed'] = max(sess.get('failed', 0), failed)
            
            if 'Terkirim:' in out and 'Gagal:' in out:
                sess['status'] = 'done'
                break
    
    t = threading.Thread(target=poll_progress)
    t.daemon = True
    t.start()
    
    return jsonify({'success': True})

@app.route('/blast-status', methods=['GET'])
def blast_status():
    """Cek progress blast"""
    if not verify_secret(request):
        return jsonify({'error': 'Unauthorized'}), 401
    
    session_id = request.args.get('sessionId')
    if not session_id or session_id not in sessions:
        return jsonify({'error': 'Session tidak ditemukan'}), 404
    
    sess = sessions[session_id]
    return jsonify({
        'status': sess.get('status'),
        'sent': sess.get('sent', 0),
        'failed': sess.get('failed', 0),
        'total': sess.get('total', 0)
    })

@app.route('/stop-blast', methods=['POST'])
def stop_blast():
    """Stop blast"""
    if not verify_secret(request):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    session_id = data.get('sessionId')
    
    if not session_id or session_id not in sessions:
        return jsonify({'error': 'Session tidak ditemukan'}), 404
    
    sess = sessions[session_id]
    container = sess['container']
    run_cmd(f"docker stop {container}")
    sess['status'] = 'stopped'
    
    return jsonify({'success': True})

@app.route('/pause-blast', methods=['POST'])
def pause_blast():
    """Pause blast"""
    if not verify_secret(request):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    session_id = data.get('sessionId')
    
    if not session_id or session_id not in sessions:
        return jsonify({'error': 'Session tidak ditemukan'}), 404
    
    sess = sessions[session_id]
    container = sess['container']
    run_cmd(f"docker pause {container}")
    sess['status'] = 'paused'
    
    return jsonify({'success': True})

if __name__ == '__main__':
    print(f"🚀 PrisilBlast Manager running on port {PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)
