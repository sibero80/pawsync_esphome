# Stock Firmware Rollback & Disaster Recovery Runbook

> [!CAUTION]
> ### ⚠️ DISCLAIMER & TESTING NOTICE
> This documentation and tools are provided "AS IS" for community testing. The authors take **no responsibility** for damaged hardware, bricked feeders, or voided warranties. Flashing custom firmware always carries risk. If an over-the-air update fails or bricks the unit, physical disassembly and a 3.3V USB-to-UART adapter are required to recover. **Always back up your full 4MB flash before flashing custom firmware.**

This guide provides step-by-step instructions for safely rolling back the **Pawsync PPF-R361S Smart Pet Feeder** from ESPHome back to its original **factory stock firmware**.

This allows you to test the entire zero-touch wireless onboarding flow from a completely clean slate, or return the feeder to the official Pawsync/VeSync smartphone app at any time with zero hardware disassembly.

---

## 📑 Table of Contents

- [Architecture: Dual-Layer Safety & Zero-Teardown Engine](#architecture-dual-layer-safety--zero-teardown-engine)
- [Method 1: 1-Click Wireless Restore via Home Assistant (Recommended)](#method-1-1-click-wireless-restore-via-home-assistant-recommended)
- [Method 2: Immediate Post-Conversion Slot Toggle (Bootloader Ping-Pong)](#method-2-immediate-post-conversion-slot-toggle-bootloader-ping-pong)
- [Method 3: Command-Line Serial Slot Reset (esptool otadata)](#method-3-command-line-serial-slot-reset-esptool-otadata)
- [Method 4: Clean Slate Recovery from 4MB Flash Dump (Hardware Unbrick)](#method-4-clean-slate-recovery-from-4mb-flash-dump-hardware-unbrick)
- [How to Test Clean Onboarding After Rollback](#how-to-test-clean-onboarding-after-rollback)

---

## Architecture: Dual-Layer Safety & Zero-Teardown Engine

The Pawsync PPF-R361S feeder contains a **4MB SPI Flash** with an ESP-IDF dual OTA partition layout matching `partitions.csv`:

```
0x000000 ┌───────────────────────────────────────┐
         │ Bootloader (0x8000 bytes)             │
0x008000 ├───────────────────────────────────────┤
         │ Partition Table (0x1000 bytes)        │
0x009000 ├───────────────────────────────────────┤
         │ NVS (0x4000), otadata (0x2000), phy   │
0x010000 ├───────────────────────────────────────┤
         │ ota_0 (1.25 MB / 0x140000 bytes)      │ ◄ Active Running Slot
0x150000 ├───────────────────────────────────────┤
         │ ota_1 (1.25 MB / 0x140000 bytes)      │ ◄ Alternate Slot (Stock / Previous FW)
0x290000 ├───────────────────────────────────────┤
         │ usercfg, fac_data, storage, history   │
0x400000 └───────────────────────────────────────┘
```

PawSync provides two levels of rollback safety:

1. **Persistent Automated Factory Backup (Host-Level Archive)**:
   During initial onboarding, the feeder's embedded HTTP backup server (`port 32769`) automatically transfers the pristine factory firmware partition and NVS calibration directly to Home Assistant storage:
   ```text
   /config/pawsync_backups/<mac>/stock_firmware.bin
   /config/pawsync_backups/<mac>/cal_<mac>.bin
   ```
   Because this binary is preserved on Home Assistant disk, **you can roll back wirelessly at any time**, even after upgrading through multiple ESPHome versions (`v1.4.x` → `v1.5.0`, etc.)!

2. **On-Device Alternate Slot (Initial Conversion State)**:
   Immediately after the first transition from stock firmware to ESPHome, the stock firmware still resides physically in the alternate slot (`ota_1`). A software button can toggle back to it. However, once a subsequent ESPHome-to-ESPHome OTA is performed, both flash slots will contain ESPHome builds. At that stage, **Method 1 (Wireless Restore via Service)** is used to flash the archived factory firmware back.

---

## Method 1: 1-Click Wireless Restore via Home Assistant (Recommended)

This is the standard, zero-teardown method. It works at any time—regardless of whether you just converted your feeder or have installed multiple ESPHome updates.

### Prerequisites
- Feeder is online and connected to Home Assistant.
- Automated factory backup is completed (`sensor.<feeder_name>_factory_firmware_backup` shows `Backed Up`).

### Step-by-Step UI Procedure
1. In Home Assistant, navigate to **Developer Tools** -> **Actions** (or **Services**).
2. Select action: **`pawsync.restore_stock_firmware`**.
3. Toggle **Confirm Factory Restore** to `true` (checked).
   *(Optional: If you have multiple feeders, specify the target feeder's `host` IP or `mac`).*
4. Click **Perform Action**.
5. **Observe Feeder Behavior**:
   - Home Assistant validates the archived `stock_firmware.bin` (ESP-IDF header `0xE9` and partition segment integrity).
   - It connects to the feeder running ESPHome on port `3232` (ESPHome OTA).
   - It streams the stock firmware image wirelessly into flash.
   - The feeder validates the image and reboots into genuine factory VeSync firmware within 15–30 seconds.
6. **Verify Stock Operation**:
   - TCP developer port `55555` will reopen (`vesync_bypass_json_msg_handle`).
   - Open your official **Pawsync** (or **VeSync**) mobile app; the feeder will appear **Online** with factory weight calibration intact.

---

## Method 2: Immediate Post-Conversion Slot Toggle (Bootloader Ping-Pong)

If you have just converted your feeder to ESPHome for the first time and have **not** installed any subsequent ESPHome updates, the stock firmware is still physically resting in flash partition `ota_1`. You can toggle back using the onboard software switches.

### Step-by-Step UI Procedure
1. In Home Assistant, navigate to your Pawsync Feeder device page under **Settings -> Devices & Services**.
2. Locate the safety interlock switch:
   - **Entity:** `switch.pawsync_feeder_unlock_factory_firmware_rollback`
   - **Friendly Name:** `Unlock Factory Firmware Rollback`
   - Toggle this switch to **ON**.
3. Locate the rollback button:
   - **Entity:** `button.pawsync_feeder_rollback_to_factory_firmware_slot_ota_1`
   - **Friendly Name:** `Rollback to Factory Firmware (Slot ota_1)`
   - Click **Press**.
4. The ESP32 bootloader updates `otadata` and reboots into `ota_1` in 2 seconds.

---

## Method 3: Command-Line Serial Slot Reset (esptool otadata)

If your feeder is not connected to Home Assistant or you prefer resetting the boot slot via serial connection:

### Hardware Requirements
- A 3.3V USB-to-UART adapter connected to the logic board test pads (`TX` GPIO21, `RX` GPIO20, `GND`).
- Feeder powered by original 5V DC adapter.
- Python 3 with `esptool`:
  ```bash
  pip install esptool
  ```

### Step 1: Query Current Boot Partition
Run:
```bash
esptool.py --chip esp32c3 --port /dev/ttyUSB0 read_flash 0xd000 0x2000 otadata.bin
```

### Step 2: Set Boot Partition to `ota_1`
To erase otadata and force the ESP32 bootloader to fallback to slot `ota_1` (offset `0x150000`):
```bash
# Erase otadata partition to trigger bootloader fallback or write ota_1 sequence
esptool.py --chip esp32c3 --port /dev/ttyUSB0 erase_region 0xd000 0x2000
```
Upon reboot, the ESP-IDF second-stage bootloader searches for the first valid partition or configured sequence and boots the stock factory partition.

---

## Method 4: Clean Slate Recovery from 4MB Flash Dump (Hardware Unbrick)

If your device becomes completely unresponsive or bricked, you can restore your original factory flash image using a 3.3V USB-to-UART serial adapter:

1. **Disassemble the feeder** (remove rubber feet, 4 bottom screws, carefully lift base plate).
2. **Wire the UART adapter**:
   - `GND` $\to$ `GND`
   - `TX` (ESP32 `GPIO21`) $\to$ `RX` on adapter
   - `RX` (ESP32 `GPIO20`) $\to$ `TX` on adapter
   - Power the feeder using its **original 5V DC power adapter** (do **NOT** power via the UART adapter's 3.3V pin).
3. **Enter Bootloader Mode**: Hold `GPIO9` (BOOT) to `GND` while plugging in the 5V DC power.
4. **Flash the 4MB Backup**:
   ```bash
   esptool.py --chip esp32c3 -p /dev/ttyUSB0 -b 921600 write_flash 0x0 pawsync_factory_4MB_backup.bin
   ```
5. Power-cycle the feeder. It will boot into its pristine factory state.

---

## How to Test Clean Onboarding After Rollback

Once your feeder has booted into the factory firmware:

1. Confirm the feeder is listed in your **Pawsync** mobile app.
2. In Home Assistant:
   - Navigate to **Settings** -> **Devices & Services** -> **Add Integration**.
   - Search for **PawSync Smart Pet Feeder**.
   - Choose **Guided Onboarding for Stock Feeder (Pawsync Cloud)**.
   - Enter your Pawsync account email and password.
   - Select your feeder from the discovered list.
   - Choose **Automated Wireless OTA Flashing**.
   - Home Assistant will automatically stage the firmware, trigger the cloud bypass, flash the feeder over Wi-Fi, and adopt it locally!
