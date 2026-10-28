# PawSync Feeder Flashing & Firmware Guide

This guide details the firmware architecture and flashing methods available for the **Pawsync PPF-R361S Smart Pet Feeder**.

> [!CAUTION]
> ### ⚠️ SAFETY NOTICE & DISCLAIMER
> Modifying embedded firmware involves risk. Interrupted OTA flashing, power drops, or unverified hardware revisions can brick the device. The authors take **no responsibility** for damaged hardware or bricked devices. **We strongly recommend disassembling the unit and creating a 4MB UART flash backup before flashing custom firmware for the first time.** See [Hardware Teardown & Backup Guide in README](README.md#-hardware-teardown-uart-pinout--flash-backuprestore-guide).

---

## 1. Automated Wireless OTA Flashing (In-HA)

The easiest method to install ESPHome onto the feeder is through the automated wireless OTA flasher built into the Home Assistant integration.

### How It Works:
1. **Dynamic Binary Retrieval ([`firmware_downloader.py`](file:///root/pawsync_esphome/custom_components/pawsync/firmware_downloader.py))**:
   - The integration resolves the verified `pawsync_ota_update.bin` container.
   - If not found locally in `/config/`, it automatically downloads the verified release container on demand from the transparent upstream repository: [**sibero80/pawsync_ota**](https://github.com/sibero80/pawsync_ota).
   - Offline users can manually place `pawsync_ota_update.bin` directly into `/config/` to bypass internet access.
2. **Local Ephemeral Stager ([`ota_stager.py`](file:///root/pawsync_esphome/custom_components/pawsync/ota_stager.py))**:
   - The integration spins up an embedded HTTP server on an ephemeral randomized path (`/firmware_<16-hex>.bin`) with an automated 10-minute self-termination timeout.
   - It serves `pawsync_ota_update.bin`, a packaged ESP32-C3 binary wrapped in a 129-byte encrypted container header required by the factory stock firmware bootloader.
3. **Paced Transfer**:
   - **Chunk 1**: Sends exactly 129 bytes (the header), then pauses for **8.0 seconds** to allow the stock firmware to erase the 1.25 MB `ota_0` partition on SPI Flash.
   - **Subsequent Chunks**: Streams 2048-byte chunks paced at ~100 KB/s (20ms delay per chunk) to ensure stable flash writing without starving the feeder's CPU.
4. **Cloud Command Relay ([`vesync_relay.py`](file:///root/pawsync_esphome/custom_components/pawsync/vesync_relay.py))**:
   - Home Assistant sends an authorized `bypassV2` command (`upFirmware`) to the feeder via the cloud API.
   - The URL is formatted using integer DWORD notation (`http://3232235916:8099/firmware_<token>.bin`) for direct compatibility with the feeder's embedded lwIP socket client.
5. **Adoption**:
   - Upon completing the download, the feeder validates the MD5 checksum, updates its boot partition, reboots into ESPHome, and connects to your local Home Assistant instance.
   - Third-party cloud bearer tokens are immediately purged from Home Assistant storage post-adoption.

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

## 3. Serial UART Flashing & Unbricking (esptool)

If wireless flashing is unavailable or if you are recovering a bricked device:

### Hardware Connection:
1. Disassemble the base (see [README Hardware Teardown](README.md#-hardware-teardown-uart-pinout--flash-backuprestore-guide)).
2. Connect a 3.3V USB-to-UART serial adapter to the labeled test pads:
   - `TX` pad (ESP32-C3 `GPIO21`) -> Adapter `RX`
   - `RX` pad (ESP32-C3 `GPIO20`) -> Adapter `TX`
   - `GND` pad -> Adapter `GND`
   - *Do NOT connect 3.3V* (power the feeder from its 5V DC adapter).
3. Put the device into download mode: connect `BOOT` (`GPIO9`) to `GND`, plug in 5V DC power, release `GPIO9` after 2 seconds.

### Flashing via esptool:
```bash
# Complete factory image (bootloader, partition table, and app at offset 0x0)
esptool.py --chip esp32c3 --port /dev/ttyUSB0 --baud 921600 write_flash 0x0 .esphome/build/pawsync-feeder/build/firmware.factory.bin

# Or app partition only (ota_0 slot at offset 0x10000 matching partitions.csv)
esptool.py --chip esp32c3 --port /dev/ttyUSB0 --baud 921600 write_flash 0x10000 .esphome/build/pawsync-feeder/build/pawsync-feeder.bin
```

---

## 4. Hardware Pinout Reference

### External Serial Pads (UART0 - Service & Flashing)
| Test Pad | ESP32-C3 Pin | Function | Notes |
| :--- | :---: | :--- | :--- |
| **`TX`** | `GPIO21` | UART0 TX (115200 Baud) | Connect to USB-UART Adapter RX |
| **`RX`** | `GPIO20` | UART0 RX (115200 Baud) | Connect to USB-UART Adapter TX |
| **`GND`** | `GND` | Ground Reference | Connect to USB-UART Adapter GND |
| **`BOOT`** | `GPIO9` | Strapping / Bootloader Pin | Pull to GND during power-up for bootloader mode |

### Internal Coprocessor Bus (UART1 - Dedicated Peripheral Link)
| Bus Line | ESP32-C3 Pin | SC95F8766P Coprocessor Pin | Description |
| :--- | :---: | :---: | :--- |
| **UART1 TX** | `GPIO19` | `RXD` (Pin 4) | Commands to Motor/Scale Coprocessor (115200 Baud 8N1) |
| **UART1 RX** | `GPIO18` | `TXD` (Pin 5) | Telemetry & Scale Weight Packets (115200 Baud 8N1) |
| **Status LED** | `GPIO3` | - | Wi-Fi / Pairing Indicator |

> [!NOTE]
> GPIO18/GPIO19 multiplex with the ESP32-C3 USB-Serial-JTAG interface. Because these pins are hardwired to the coprocessor UART, internal USB-JTAG CDC is not exposed. Serial recovery must use UART0 test pads.
