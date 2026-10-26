# PawSync Feeder Flashing & Firmware Guide

This guide details the firmware architecture and flashing methods available for the **Pawsync PPF-R361S Smart Pet Feeder**.

> [!CAUTION]
> ### ⚠️ SAFETY NOTICE & DISCLAIMER
> Modifying embedded firmware involves risk. Interrupted OTA flashing, power drops, or unverified hardware revisions can brick the device. The authors take **no responsibility** for damaged hardware or bricked devices. **We strongly recommend disassembling the unit and creating a 4MB UART flash backup before flashing custom firmware for the first time.** See [Hardware Teardown & Backup Guide in README](README.md#-hardware-teardown-uart-pinout--flash-backuprestore-guide).

---

## 1. Automated Wireless OTA Flashing (In-HA)

The easiest method to install ESPHome onto the feeder is through the automated wireless OTA flasher built into the Home Assistant integration.

### How It Works:
1. **Local HTTP Stager (`ota_stager.py`)**:
   - The integration spins up an embedded HTTP server on port 8000.
   - It serves `pawsync_ota_update.bin`, a packaged ESP32-C3 binary wrapped in a 129-byte encrypted container header required by the factory stock firmware bootloader.
2. **Paced Transfer**:
   - **Chunk 1**: Sends exactly 129 bytes (the header), then pauses for **8.0 seconds** to allow the stock firmware to erase the 1.25 MB `ota_0` partition on SPI Flash.
   - **Subsequent Chunks**: Streams 2048-byte chunks paced at ~100 KB/s (20ms delay per chunk) to ensure stable flash writing without starving the feeder's CPU.
3. **Cloud Command Relay (`vesync_relay.py`)**:
   - Home Assistant sends an authorized `bypassV2` command (`upFirmware`) to the feeder via the cloud API.
   - The URL is formatted using integer DWORD notation (`http://3232235916:8000/firmware.bin`) for direct compatibility with the feeder's embedded lwIP socket client.
4. **Adoption**:
   - Upon completing the download, the feeder validates the MD5 checksum, updates its boot partition, reboots into ESPHome, and connects to your local Home Assistant instance.

---

## 2. Command-Line Interface (ESPHome CLI)

For developers and power users, the firmware can be compiled and flashed directly using the ESPHome CLI:

### Prerequisites:
- Python 3.10+
- ESPHome 2024.6.0+

```bash
# Clone the repository
git clone https://github.com/sibero80/pawsync_esphome.git
cd pawsync_esphome

# Create your secrets file
cp secrets.yaml.example secrets.yaml
# Edit secrets.yaml with your Wi-Fi SSID, password, and encryption key

# Compile the firmware
esphome compile pawsync.yaml

# Flash wirelessly over local Wi-Fi (if already running ESPHome)
esphome run pawsync.yaml --device 192.168.1.45
```

---

## 3. WebSerial / USB-C Direct Flashing

If wireless flashing is unavailable or if you are recovering a bricked device:

### Hardware Connection:
1. Connect a USB-C data cable between your computer and the feeder.
2. The internal ESP32-C3 serial bridge will enumerate as a CDC USB Serial device (e.g., `/dev/ttyACM0` on Linux, `COMx` on Windows).

### Flashing via esptool:
```bash
esptool.py --chip esp32c3 --port /dev/ttyACM0 --baud 921600 write_flash 0x20000 .esphome/build/pawsync-feeder/build/firmware.bin
```

---

## 4. Hardware Pinout Reference

| Function | ESP32-C3 Pin | SC95F8766P Coprocessor Pin | Description |
| :--- | :---: | :---: | :--- |
| **UART TX** | `GPIO21` | `RXD` (Pin 4) | Commands to Motor/Scale Coprocessor |
| **UART RX** | `GPIO20` | `TXD` (Pin 5) | Telemetry & Scale Weight Packets |
| **Baud Rate** | - | - | 9600 Baud, 8N1, Full Duplex |
| **Status LED** | `GPIO3` | - | Wi-Fi / Pairing Indicator |
| **Boot Mode** | `GPIO9` | - | Internal Pull-up (Pull low for bootloader) |
