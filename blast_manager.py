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
    if result.returncode != 0 and result.stderr:
        print(f"[CMD ERROR] {cmd[:80]}: {result.stderr.strip()[:200]}")
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
    """Background thread: poll QR dan update status dari container"""
    container = get_container_name(user_id)
    qr_path = f"/tmp/wa_qr_{session_id}.png"
    status_file = f"/tmp/wa_status_{session_id}.json"
    
    for i in range(120):  # max 10 menit
        time.sleep(5)
        
        # Copy QR screenshot dari container
        run_cmd(f"docker cp {container}:/app/wa_qr.png {qr_path} 2>/dev/null")
        
        if os.path.exists(qr_path):
            url = upload_to_cloudinary(qr_path, f"qr_{session_id}_{int(time.time())}")
            if url:
                sessions[session_id]['qrUrl'] = url
                sessions[session_id]['status'] = 'waiting_scan'
        
        # Cek status dari container
        run_cmd(f"docker cp {container}:/app/wa_status.json {status_file} 2>/dev/null")
        if os.path.exists(status_file):
            try:
                with open(status_file) as f:
                    status_data = json.load(f)
                status = status_data.get('status')
                if status == 'connected':
                    sessions[session_id]['status'] = 'connected'
                    print(f"[{session_id}] WhatsApp connected!")
                    break
                elif status == 'blasting':
                    sessions[session_id].update({
                        'status': 'blasting',
                        'sent': status_data.get('sent', 0),
                        'total': status_data.get('total', 0)
                    })
                elif status == 'done':
                    sessions[session_id].update({
                        'status': 'done',
                        'sent': status_data.get('sent', 0),
                        'failed': status_data.get('failed', 0)
                    })
                    break
            except: pass
        
        if i % 6 == 0:
            print(f"[{session_id}] Waiting for QR scan... ({i*5}s)")

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'version': '1.0'})

@app.route('/get-qr', methods=['GET'])
def get_qr():
    """Ambil QR image sebagai base64"""
    if not verify_secret(request):
        return jsonify({'error': 'Unauthorized'}), 401
    
    session_id = request.args.get('sessionId')
    if not session_id or session_id not in sessions:
        return jsonify({'error': 'Session tidak ditemukan'}), 404
    
    sess = sessions[session_id]
    container = sess['container']
    qr_path = f"/tmp/wa_qr_{session_id}.png"
    
    run_cmd(f"docker cp {container}:/app/wa_qr.png {qr_path} 2>/dev/null")
    
    if os.path.exists(qr_path):
        import base64
        with open(qr_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode()
        return jsonify({
            'success': True,
            'qr': f"data:image/png;base64,{b64}",
            'status': sess.get('status')
        })
    
    return jsonify({'error': 'QR belum tersedia', 'status': sess.get('status')})

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
    
    # Copy wa_standby.py ke tmp
    standby_src = f"{WORKSPACE}/prisilblast/wa_standby.py"
    
    # Jalankan container baru dengan wa_standby.py
    cmd = f"""docker run -d \
        --name {container} \
        --network host \
        -v {volume}:/app/wa_session \
        -v {contacts_path}:/app/contacts.csv \
        -v /tmp:/tmp \
        -v {standby_src}:/app/wa_standby.py \
        -e SESSION_DIR=/app/wa_session \
        {BLAST_IMAGE} python3 -u /app/wa_standby.py"""
    
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
    
    # Kirim command blast via file
    cmd_file = f"/tmp/blast_command.json"
    with open(cmd_file, 'w') as f:
        json.dump({
            'action': 'blast',
            'template': template,
            'contacts': '/app/contacts.csv'
        }, f)
    run_cmd(f"docker cp {cmd_file} {container}:/app/blast_command.json")
    
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
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True, use_reloader=False)
