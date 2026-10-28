# Stock Firmware Rollback & Disaster Recovery Runbook

> [!CAUTION]
> ### ⚠️ DISCLAIMER & TESTING NOTICE
> This documentation and tools are provided "AS IS" for community testing. The authors take **no responsibility** for damaged hardware, bricked feeders, or voided warranties. Flashing custom firmware always carries risk. If an over-the-air update fails or bricks the unit, physical disassembly and a 3.3V USB-to-UART adapter are required to recover. **Always back up your full 4MB flash before flashing custom firmware.**

This guide provides step-by-step instructions for safely rolling back the **Pawsync PPF-R361S Smart Pet Feeder** from ESPHome back to its original **factory stock firmware** (`ota_1` partition).

This allows you to test the entire zero-touch wireless onboarding flow from a completely clean slate, or return the feeder to the official Pawsync/VeSync smartphone app at any time with zero hardware disassembly.

---

## Architecture: Why Rollback is 100% Non-Destructive

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

When you initially transitioned from stock factory firmware to ESPHome via wireless OTA, stock firmware was in one slot and ESPHome was flashed into the alternate slot (e.g., `ota_0`). The factory stock firmware in the alternate partition (`ota_1`) was initially left intact.

> [!WARNING]
> ### ⚠️ A/B Ping-Pong Lifecycle vs Full Factory Restore
> The software rollback switch (`switch.pawsync_feeder_unlock_factory_firmware_rollback` + `button.pawsync_feeder_rollback_to_factory_firmware_slot_ota_1`) instructs the ESP-IDF bootloader to toggle between `ota_0` and `ota_1`.
> - **Initial State**: Immediately after the first wireless conversion, toggling slots reboots back into original stock factory firmware.
> - **Subsequent ESPHome OTAs**: Once an ESPHome-to-ESPHome OTA is performed, ESPHome writes to the alternate slot. At this point, **both slots contain ESPHome builds** (current and previous version). Toggling rollback will switch between ESPHome versions, not factory firmware.
> - **Permanent Factory Recovery**: To permanently restore pristine stock factory firmware at any point, flash your full 4MB factory backup image (`pawsync_factory_4MB_backup.bin`) via esptool (Method 3).

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

## Method 2: Command-Line Serial Rollback (esptool)

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

## Method 3: Clean Slate Recovery from 4MB Flash Dump (Hardware Unbrick)

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
