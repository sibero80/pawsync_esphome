# Stock Firmware Rollback & Disaster Recovery Runbook

This guide provides step-by-step instructions for safely rolling back the **Pawsync PPF-R361S Smart Pet Feeder** from ESPHome back to its original **factory stock firmware** (`ota_1` partition).

This allows you to test the entire zero-touch wireless onboarding flow from a completely clean slate, or return the feeder to the official Pawsync/VeSync smartphone app at any time with zero hardware disassembly.

---

## Architecture: Why Rollback is 100% Non-Destructive

The Pawsync PPF-R361S feeder contains a **4MB SPI Flash** with a dual OTA partition layout:

```
0x000000 ┌───────────────────────────────────────┐
         │ Bootloader (0x10000 bytes)            │
0x010000 ├───────────────────────────────────────┤
         │ Partition Table (0x1000 bytes)        │
0x020000 ├───────────────────────────────────────┤
         │ ota_0 (1.25 MB): ESPHome Local FW     │ ◄ Current Running Slot
0x160000 ├───────────────────────────────────────┤
         │ ota_1 (1.25 MB): Stock Factory FW     │ ◄ Pristine Factory Backup
0x290000 ├───────────────────────────────────────┤
         │ usercfg & NVS: Calibration & Wi-Fi    │
0x400000 └───────────────────────────────────────┘
```

When you initially flashed ESPHome, the flashing process installed the ESPHome image strictly into partition **`ota_0`**. The factory stock firmware in partition **`ota_1`** was left completely intact.

---

## Method 1: Instant In-Home-Assistant Rollback (2 Clicks)

If your feeder is currently running ESPHome and connected to Home Assistant, you can roll back instantly from the Home Assistant UI without opening a terminal or unplugging the feeder.

### Step-by-Step UI Procedure

1. In Home Assistant, open **Developer Tools** -> **States** (or navigate to your Pawsync Feeder device page under **Settings -> Devices & Services**).
2. Locate the safety interlock switch:
   - **Entity:** `switch.pawsync_feeder_unlock_factory_firmware_rollback` (or `switch.*_unlock_factory_firmware_rollback`)
   - **Friendly Name:** `Unlock Factory Firmware Rollback`
   - Toggle this switch to **ON**.
   > **Note:** This switch is an intentional software safety interlock that prevents accidental rollback triggers.

3. Locate the rollback button:
   - **Entity:** `button.pawsync_feeder_rollback_to_factory_firmware_slot_ota_1` (or `button.*_rollback_to_factory_firmware*`)
   - **Friendly Name:** `Rollback to Factory Firmware (Slot ota_1)`
   - Click **Press** (or call the `button.press` service).

4. **Observe Feeder Behavior**:
   - The ESPHome log will confirm:
     ```
     [W][ppf_r361s:1404] Initiating software rollback to stock firmware partition 'ota_1'...
     [W][ppf_r361s:1416] Boot partition set to 'ota_1' successfully! Rebooting into stock factory firmware in 2 seconds...
     ```
   - In 2 seconds, the ESP32-C3 will reboot.
   - The Wi-Fi indicator on the feeder front panel will pulse or illuminate according to the stock firmware behavior.
   - The feeder is now running the factory stock firmware!

5. **Verify Stock Operation**:
   - Open your official **Pawsync** (or **VeSync**) mobile app on your smartphone.
   - The feeder will reconnect to your Wi-Fi network and show as **Online** in the mobile app.
   - Test a manual dispense or inspect the bowl weight from the phone app to confirm stock functionality.

---

## Method 2: Command-Line USB Rollback (esptool)

If your feeder is not connected to Home Assistant or you prefer using a USB-C data cable connected to your computer:

### Hardware Requirements
- A USB-C data cable connected to the feeder's USB-C port (or internal ESP32-C3 programming header).
- Python 3 with `esptool`:
  ```bash
  pip install esptool
  ```

### Step 1: Query Current Boot Partition
Run:
```bash
esptool.py --chip esp32c3 --port /dev/ttyACM0 read_flash 0xd000 0x2000 otadata.bin
```

### Step 2: Set Boot Partition to `ota_1`
To point the ESP32 bootloader back to partition `ota_1` (offset `0x160000`):
```bash
# Erase otadata partition to trigger bootloader fallback or write ota_1 sequence
esptool.py --chip esp32c3 --port /dev/ttyACM0 erase_region 0xd000 0x2000
```
Upon reboot, the ESP-IDF second-stage bootloader searches for the first valid partition or configured sequence and boots the stock factory partition.

---

## Method 3: Clean Slate Recovery from 4MB Flash Dump

If you ever need to restore the feeder to the 100% identical byte-for-byte factory state as it came out of the box:

```bash
esptool.py --chip esp32c3 -p /dev/ttyACM0 -b 921600 write_flash 0x0 /root/pawsync_esphome/esp32c3_dump.bin
```

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
