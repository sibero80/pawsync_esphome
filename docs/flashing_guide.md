# Pawsync PPF-R361S Hardware Flashing & Stock Rollback Runbook

This guide describes the hardware interface, UART programming test points, initial firmware backup, ESPHome flashing, and the 100% bit-accurate factory rollback procedure for the **Pawsync PPF-R361S** smart pet feeder.

---

## 1. Hardware Overview & PCB Architecture

The Pawsync PPF-R361S employs a dual-microcontroller architecture:
1. **Espressif ESP32-C3** (4MB SPI Flash):
   - Handles 2.4 GHz Wi-Fi connectivity and Home Assistant integration.
   - Controls NS4168 I2S Mono Audio Amplifier for meal calls (`GPIO0` Enable, `GPIO1` LRCLK, `GPIO4` BCLK, `GPIO5` DOUT).
   - Communicates with coprocessor via UART (`GPIO18` RX, `GPIO19` TX @ 115,200 baud).
2. **Sinowealth SC95F8766P** (8051-core Coprocessor):
   - Handles real-time motor H-bridge, load-cell strain gauge ADC (bowl scale), IR hopper sensors, and battery charging logic.
   - **Important**: The SC95F8766P firmware is NOT modified. It remains in its pristine factory state.

---

## 2. Test Pads & Flashing Pinout

The bottom of the main PCB exposes labeled test points adjacent to the ESP32-C3 SoC shielding can:

| Test Point | ESP32-C3 Signal | Function / Programmer Connection |
| :--- | :--- | :--- |
| **`3V3`** | `VDD_3V3` | External 3.3V DC power (or power device via 5V barrel jack) |
| **`GND`** | `GND` | Ground reference (connect to USB-TTL adapter GND) |
| **`TX`** | `GPIO21` (UART0 TX) / `U0TXD` | Connect to USB-TTL **RX** |
| **`RX`** | `GPIO20` (UART0 RX) / `U0RXD` | Connect to USB-TTL **TX** |
| **`IO9`** | `GPIO9` (Boot Strap) | Pull to **GND** during reset/power-on to enter ROM bootloader |
| **`EN`** / **`RST`**| `CHIP_EN` | Momentarily ground to reset SoC |

> [!CAUTION]
> **Logic Level Warning**: Use a 3.3V USB-to-UART serial converter (e.g. FT232RL, CP2102, CH340G switched to 3.3V). Connecting 5V logic to the ESP32-C3 GPIO pins will permanently damage the microcontroller.

---

## 3. Pre-Flash Factory Backup (Mandatory)

Before writing any new firmware to the ESP32-C3, you **must** create a bit-accurate 4MB binary dump of the factory flash.

1. Connect your 3.3V USB-TTL adapter to `TX`, `RX`, and `GND`.
2. Connect `IO9` to `GND`.
3. Power on the device (or cycle `EN` to GND and release).
4. Verify the ESP32-C3 enters the ROM bootloader:
   ```bash
   esptool.py --chip esp32c3 -p /dev/ttyUSB0 chip_id
   ```
5. Extract the entire 4MB SPI flash:
   ```bash
   esptool.py --chip esp32c3 -p /dev/ttyUSB0 -b 921600 read_flash 0x0 0x400000 factory_dump_backup.bin
   ```
6. Compute the SHA-256 hash of the extracted image:
   ```bash
   sha256sum factory_dump_backup.bin
   ```
   Verify that the dump matches the reference image:
   - Reference SHA-256: `8d1970e78007f18975c255c625c37bccf2a5cfa7d76eff04f3af731fea3bb77a`
   - Flash Size: 4,194,304 bytes (4096 KB)
   - Store this backup file in a secure location.

---

## 4. Flashing ESPHome Firmware

Once the backup is secured, flash the open-source ESPHome firmware:

### Step 1: Configure Secrets
Copy or edit `secrets.yaml`:
```yaml
wifi_ssid: "Your_WiFi_Network"
wifi_password: "Your_WiFi_Password"
api_encryption_key: "Generated_Base64_Key"
```

### Step 2: Compile & Flash Initial Image via Serial
Ensure `IO9` is tied to `GND`, then run:
```bash
esphome run pawsync.yaml --device /dev/ttyUSB0
```

### Step 3: Normal Boot
Disconnect `IO9` from `GND` and reboot the device (or cycle power).
The device will join your local Wi-Fi network and announce itself via mDNS (`pawsync-feeder.local`). Subsequent updates can be flashed over-the-air (OTA).

---

## 5. 100% Bit-Accurate Rollback Procedure

If you ever wish to revert the feeder to 100% stock factory condition (e.g., for warranty return or stock VeSync cloud app usage):

1. Put the ESP32-C3 into download mode (`IO9` to `GND`, cycle power).
2. Write the factory backup back to flash offset `0x0`:
   ```bash
   esptool.py --chip esp32c3 -p /dev/ttyUSB0 -b 921600 write_flash 0x0 factory_dump_backup.bin
   ```
3. Disconnect `IO9` and reboot.
4. The feeder will immediately boot the stock `ota_1` partition (v1.2.5), reconnect to the VeSync cloud, and restore all factory scale calibration parameters stored in the pristine NVS partition.
