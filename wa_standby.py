#!/usr/bin/env python3
"""
WA Standby - Mode tunggu login WA, screenshot QR, siap blast
Dipanggil oleh blast_manager per user/container
"""

from playwright.sync_api import sync_playwright
import time, os, subprocess, json, signal, sys

SESSION_DIR = os.environ.get('SESSION_DIR', '/app/wa_session')
QR_PATH = '/app/wa_qr.png'
STATUS_FILE = '/app/wa_status.json'
DELAY_SECONDS = int(os.environ.get('DELAY_SECONDS', '65'))

def save_status(status, extra={}):
    data = {'status': status, 'ts': time.time(), **extra}
    with open(STATUS_FILE, 'w') as f:
        json.dump(data, f)
    print(f"[STATUS] {status}", flush=True)

def clean_number(n):
    import re
    if not n: return None
    n = re.sub(r'[\s\-\(\)\+]', '', n.strip())
    if n.startswith('08'): n = '62' + n[1:]
    elif not n.startswith('62'): n = '62' + n
    if not re.match(r'^\d{10,15}$', n): return None
    return n

def load_contacts(csv_path):
    import csv
    contacts, seen = [], set()
    if not os.path.exists(csv_path): return contacts
    with open(csv_path, 'r', encoding='utf-8') as f:
        sample = f.read(200); f.seek(0)
        if 'NAMA' in sample.upper():
            reader = csv.DictReader(f)
            for row in reader:
                nama = (row.get('NAMA','') or row.get('nama','')).strip() or 'Pelanggan'
                nomor = clean_number((row.get('NOMER WA','') or row.get('NOMOR','')).strip())
                if nomor and nomor not in seen:
                    seen.add(nomor); contacts.append({'nama': nama, 'nomor': nomor})
        else:
            reader = csv.reader(f)
            for row in reader:
                if len(row) < 2: continue
                nama = row[0].strip() or 'Pelanggan'
                nomor = clean_number(row[1].strip())
                if nomor and nomor not in seen:
                    seen.add(nomor); contacts.append({'nama': nama, 'nomor': nomor})
    return contacts

def run():
    import urllib.parse
    save_status('starting')
    os.makedirs(SESSION_DIR, exist_ok=True)
    
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            SESSION_DIR, headless=True,
            args=['--no-sandbox','--disable-dev-shm-usage'],
            viewport={'width':1280,'height':720},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto('https://web.whatsapp.com', wait_until='domcontentloaded')
        
        save_status('waiting_qr')
        
        # Tunggu login
        connected = False
        for i in range(120):
            time.sleep(5)
            try:
                content = page.content()
                if 'Cari atau mulai' in content or 'Search or start' in content or 'chats' in page.url:
                    connected = True
                    save_status('connected')
                    print("✅ WhatsApp siap!", flush=True)
                    break
                # Screenshot QR setiap 15 detik
                if i % 3 == 0:
                    page.screenshot(path=QR_PATH)
                    save_status('waiting_qr', {'qr_updated': time.time()})
            except Exception as e:
                print(f"[WARN] {e}", flush=True)
        
        if not connected:
            save_status('timeout')
            browser.close()
            return
        
        # Tunggu perintah blast (cek file /tmp/blast_command.json)
        print("[STANDBY] Menunggu perintah blast...", flush=True)
        blast_log = {'sent': [], 'failed': []}
        
        for _ in range(720):  # tunggu max 1 jam
            time.sleep(5)
            cmd_file = '/app/blast_command.json'
            if os.path.exists(cmd_file):
                with open(cmd_file) as f:
                    cmd = json.load(f)
                if cmd.get('action') == 'blast':
                    os.remove(cmd_file)
                    template = cmd.get('template', 'Halo {nama}!')
                    contacts_path = cmd.get('contacts', '/app/contacts.csv')
                    contacts = load_contacts(contacts_path)
                    sent_set = set(blast_log['sent'])
                    to_send = [c for c in contacts if c['nomor'] not in sent_set]
                    
                    save_status('blasting', {'total': len(contacts), 'sent': len(sent_set)})
                    print(f"🚀 Mulai blast {len(to_send)} kontak", flush=True)
                    
                    sent = failed = 0
                    for i, c in enumerate(to_send):
                        nama, nomor = c['nama'], c['nomor']
                        pesan = template.replace('{nama}', nama)
                        try:
                            txt = urllib.parse.quote(pesan)
                            page.goto(f"https://web.whatsapp.com/send?phone={nomor}&text={txt}",
                                     wait_until='networkidle', timeout=30000)
                            time.sleep(5)
                            page.keyboard.press('Enter')
                            time.sleep(3)
                            print(f"✅ [{i+1}/{len(to_send)}] {nama}", flush=True)
                            sent += 1
                            blast_log['sent'].append(nomor)
                            save_status('blasting', {'total':len(contacts),'sent':len(blast_log['sent']),'failed':failed})
                            if i < len(to_send)-1:
                                time.sleep(DELAY_SECONDS)
                        except Exception as e:
                            print(f"❌ [{i+1}] {nama}: {e}", flush=True)
                            failed += 1
                            blast_log['failed'].append(nomor)
                    
                    save_status('done', {'total':len(contacts),'sent':len(blast_log['sent']),'failed':failed})
                    print(f"\n✅ Selesai! Terkirim: {sent} | Gagal: {failed}", flush=True)
                
                elif cmd.get('action') == 'stop':
                    break
        
        browser.close()

if __name__ == '__main__':
    run()
