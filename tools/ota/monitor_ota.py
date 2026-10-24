#!/usr/bin/env python3
import socket
import time
import sys

TARGET_IP = "192.168.1.45"
DEV_PORT = 55555
ESPHOME_PORT = 6053

print(f"[*] Starting OTA lifecycle monitor for {TARGET_IP}...")

# 1. Connect to port 55555
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(2.0)
try:
    s.connect((TARGET_IP, DEV_PORT))
    print(f"[+] Connected to Developer Port {DEV_PORT}. Capturing live logs...")
except Exception as e:
    print(f"[-] Could not connect to {DEV_PORT}: {e}")
    s = None

start_time = time.time()
while time.time() - start_time < 90:
    if s:
        try:
            data = s.recv(1024)
            if data:
                sys.stdout.write(data.decode("utf-8", errors="ignore"))
                sys.stdout.flush()
            else:
                print(f"\n[*] Port {DEV_PORT} connection closed by remote (rebooting?)")
                s.close()
                s = None
        except socket.timeout:
            pass
        except Exception as e:
            print(f"\n[*] Port {DEV_PORT} disconnected: {e}")
            s.close()
            s = None
    else:
        # Check if ESPHome port 6053 is open
        s_esp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s_esp.settimeout(1.0)
        res_esp = s_esp.connect_ex((TARGET_IP, ESPHOME_PORT))
        s_esp.close()

        if res_esp == 0:
            print(f"\n[🎉 SUCCESS] ESPHome Native API port {ESPHOME_PORT} is OPEN on {TARGET_IP}!")
            sys.exit(0)

        # Check if stock port 55555 came back up
        s_dev = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s_dev.settimeout(1.0)
        res_dev = s_dev.connect_ex((TARGET_IP, DEV_PORT))
        s_dev.close()

        if res_dev == 0:
            print(f"\n[!] Stock Developer Port {DEV_PORT} is back UP on {TARGET_IP} (Rollback occurred).")
            sys.exit(1)

        time.sleep(1)

print("\n[-] Monitor timed out after 90 seconds.")
sys.exit(2)
