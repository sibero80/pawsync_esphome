# PawSync Smart Pet Feeder for Home Assistant

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![ESPHome Version](https://img.shields.io/badge/ESPHome-2024.6%2B-blue.svg)](https://esphome.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![HA Minimum](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue.svg)](https://home-assistant.io)
[![Support Matruska](https://img.shields.io/badge/Donate-Matruska%20Cat%20Shelter-ea4c89.svg?logo=paypal&logoColor=white)](https://www.paypal.com/ncp/payment/KMWR984RL7M6G)

**100% Local, Cloud-Free Control of the Pawsync PPF-R361S Smart Pet Feeder in Home Assistant.**

Convert your factory stock Pawsync feeder over Wi-Fi directly inside Home Assistant's UI without opening a terminal, soldering, or taking the device apart. Enjoy zero latency, zero cloud dependency, an authentic mobile-app-replica Lovelace card, and instant rollback safety.

---

> [!CAUTION]
> ### ⚠️ EXPERIMENTAL SOFTWARE & LIABILITY DISCLAIMER
> **PLEASE READ CAREFULLY BEFORE PROCEEDING:**
> - **Community Project**: This integration, custom component, and ESPHome firmware are independent, community-driven reverse-engineering projects. They are **not** affiliated with, sponsored by, or endorsed by Pawsync, VeSync, or Etekcity.
> - **No Warranty / Use At Your Own Risk**: This software is provided "AS IS", without warranty of any kind, express or implied. **The author and contributors accept NO RESPONSIBILITY or LIABILITY** for any bricked devices, damaged hardware, lost food, missed or incorrect pet feedings, or voided manufacturer warranties.
> - **Risk of Bricking**: Modifying IoT device firmware carries inherent risks. A sudden power loss, interrupted wireless transfer, network failure, or an unverified hardware revision may render the feeder unbootable ("bricked"). If a device is bricked, wireless recovery is impossible and **physical disassembly with a 3.3V USB-to-UART serial adapter will be required** to restore it.
> - **Strong Pre-Flash Recommendation**: While the in-HA wireless OTA wizard has been engineered with dual-partition failsafes and automated staging, **we STRONGLY RECOMMEND physically disassembling your feeder and taking a full 4MB byte-for-byte flash backup via UART before flashing custom firmware for the first time.** Instructions are provided below.

---

## 🐾 Support Matruska Cat Shelter (Medellín)

Instead of buying the developer a coffee, please consider helping rescued cats in need!

<table>
  <tr>
    <td width="220" align="center" valign="middle">
      <img src="docs/images/matruska_rescue.jpg" width="200" alt="Rescued kitten at Matruska shelter" style="border-radius: 8px;" />
    </td>
    <td valign="middle">
      <p>
        <strong><a href="https://matruska.co">Matruska</a></strong> is a grassroots, non-profit cat shelter and foster home based in the Medellín metropolitan area (Envigado, Colombia). They specialize in rescuing, rehabilitating, and finding forever homes for abandoned, sick, and special-needs cats—including vulnerable newborn kittens requiring around-the-clock bottle feeding and cats with mobility disabilities.
      </p>
      <p>
        If this free, open-source project gave you local control over your pet feeder, saved you subscription fees, or brought peace of mind to your feeding routine, please consider redirecting your appreciation to help fund life-saving veterinary care, medicines, and food for these sweet kitties.
      </p>
      <p>
        <a href="https://www.paypal.com/ncp/payment/KMWR984RL7M6G" target="_blank" rel="noopener noreferrer">
          <img src="https://img.shields.io/badge/Donate%20to%20Matruska%20via%20PayPal-00457C?style=for-the-badge&logo=paypal&logoColor=white" alt="Donate to Matruska via PayPal" />
        </a>
      </p>
    </td>
  </tr>
</table>

---

## 📑 Table of Contents

- [⚠️ Disclaimer & Liability](#️-experimental-software--liability-disclaimer)
- [🐾 Support Matruska Cat Shelter](#-support-matruska-cat-shelter-medellín)
- [✨ Key Features](#key-features)
- [🚀 Quick Start Installation](#quick-start-installation)
  - [Method 1: HACS (Recommended)](#method-1-hacs-recommended)
  - [Method 2: Manual Installation](#method-2-manual-installation)
- [📱 Feeder Dashboard Card](#feeder-dashboard-card)
- [🔄 Routine Firmware Updates (In-Home Assistant)](#-routine-firmware-updates-in-home-assistant)
  - [How Routine Updates Work](#how-routine-updates-work)
  - [Safety & Overwrite Protection Interlock](#safety--overwrite-protection-interlock)
- [⏪ 1-Click Factory Stock Rollback (Zero Teardown)](#-1-click-factory-stock-rollback-zero-teardown)
  - [Zero-Teardown Wireless Restore](#zero-teardown-wireless-restore)
  - [Where Backups Are Stored](#where-backups-are-stored)
  - [Step-by-Step UI Procedure](#step-by-step-ui-procedure)
- [🛠️ Hardware Teardown, UART Pinout & Flash Backup/Restore](#️-hardware-teardown-uart-pinout--flash-backuprestore-guide)
  - [Step 1: Safe Disassembly](#step-1-safe-disassembly)
  - [Step 2: UART Pinout & Wiring](#step-2-uart-pinout--wiring)
  - [Step 3: Enter Bootloader Mode](#step-3-enter-bootloader-download-mode)
  - [Step 4: Full 4MB Byte-for-Byte Factory Backup](#step-4-perform-full-4mb-byte-for-byte-factory-backup)
  - [Step 5: Disaster Recovery via Serial](#step-5-disaster-recovery-restoring-full-factory-backup)
- [📚 Detailed Documentation](#detailed-documentation)
- [⚙️ Technical Specifications](#technical-specifications)
- [📄 License](#license)

---

## Key Features

- **Guided In-HA Adoption Wizard**:
  - Connects to your Pawsync or VeSync account to capture device hardware credentials (CID, MAC, tokens).
  - Multi-feeder discovery: adopt one or multiple feeders simultaneously.
  - Automated wireless flashing over your local Wi-Fi network using an embedded, paced HTTP stager.
- **Official App-Replica Lovelace Feeder Card (v1.3.0)**:
  - Bundled automatically—no manual JavaScript resource installation required.
  - **Live Bowl Scale**: Animated stainless steel bowl filling dynamically with kibble, featuring a glowing pulsing indicator when your pet is eating.
  - **Dynamic Calibrated Density**: Portions calculate in real time using your measured grams-per-portion density (e.g. 11.5g).
  - **Active Safety & Parity Banners**: Real-time warnings for bowl overflow (>150g), chute cleaning due (30-day countdown), hopper level categories (Empty/Low/Sufficient), and low battery failover.
  - **4 Essential Daily Stats**:
    1. *Today's Planned Serving* (calculated sum of all active scheduled meal portions).
    2. *Last Eaten* (exact grams consumed, eating speed in g/min, and human-readable time).
    3. *Total Eaten Today* (accumulated consumption with automatic midnight rollover).
    4. *Next Scheduled Meal* (name, target time, and portion breakdown).
  - **Collapsible 7-Plan Schedule Manager**:
    - Manage up to 7 distinct feeding plans with 10 meal slots each.
- **100% Native Feeder Alert Parity Blueprint**:
  - Pre-configured Home Assistant notification blueprint ([`blueprints/automation/pawsync_notifications.yaml`](blueprints/automation/pawsync_notifications.yaml)) covering all 14 official mobile app channels: motor jam, bowl overflow, food empty, food low, AC outage, battery low, 30-day chute cleaning reminder, 30-day desiccant replacement, dispense confirmations, meal sessions, scale disconnection, bowl removed, abnormal eating speed, and scale overload.
    - Compact collapsed state by default to conserve dashboard screen real estate.
    - Graphical meal editor with time picker, day pills (Daily, Weekdays, Weekends), and chime toggles.
  - **Quick Manual Feed**: Radial portion selector with instant dispense and one-click bowl scale tare.
- **100% Local ESPHome Architecture**:
  - Operates over ESPHome Native API directly on your local network.
  - Runs autonomously on-device even if your home Wi-Fi or Home Assistant temporarily goes offline.
- **Failsafe Factory Firmware Rollback**:
  - Dual-partition SPI flash architecture preserves the factory stock firmware in partition `ota_1`.
  - A software-locked switch allows you to roll back to stock firmware with 2 clicks from Home Assistant anytime.

---

## Quick Start Installation

### Method 1: HACS (Recommended)

1. Ensure [HACS](https://hacs.xyz/) is installed in your Home Assistant.
2. In Home Assistant, open **HACS** -> **Integrations** -> **Custom repositories** (three dots top right).
3. Add repository URL:
   ```text
   https://github.com/sibero80/pawsync_esphome
   ```
   - Category: **Integration**
4. Click **Add**, locate **PawSync Smart Pet Feeder**, and click **Download**.
5. Restart Home Assistant.
6. Go to **Settings** -> **Devices & Services** -> **Add Integration**, search for **PawSync**, and follow the guided wizard!

### Method 2: Manual Installation

1. Copy the `custom_components/pawsync` folder from this repository into your Home Assistant's `config/custom_components/` directory.
2. Restart Home Assistant.
3. In **Settings** -> **Devices & Services**, click **Add Integration** and select **PawSync Smart Pet Feeder**.

---

## Feeder Dashboard Card

The integration automatically registers and serves the bundled Lovelace card at both `/pawsync/pawsync-feeder-card.js` and `/local/pawsync-feeder-card.js`.

To add the card to your dashboard:
1. Click **Edit Dashboard** -> **Add Card**.
2. Select **Custom: PawSync Feeder Card** or paste the following YAML into a Manual card:

```yaml
type: custom:pawsync-feeder-card
# Optional overrides:
# title: "Fluffy's Feeder"
# default_collapsed: true
```

> [!TIP]
> If Home Assistant shows `Custom element doesn't exist: pawsync-feeder-card`:
> 1. Perform a hard browser refresh (**Ctrl + Shift + R** on Windows/Linux or **Cmd + Shift + R** on Mac) to clear stale cached scripts.
> 2. Alternatively, in Home Assistant go to **Settings** -> **Dashboards** -> **Three dots (top right)** -> **Resources** -> **Add Resource**:
>    - **URL**: `/local/pawsync-feeder-card.js`
>    - **Resource type**: JavaScript Module (`module`)

---

## 🔄 Routine Firmware Updates (In-Home Assistant)

Once your feeder is running PawSync ESPHome firmware, subsequent updates (such as upgrading from `v1.4.x` to `v1.5.0`) are executed seamlessly from your Home Assistant dashboard via the native `update` entity (`update.<feeder_name>_firmware`).

### How Routine Updates Work
1. **GitHub Release Discovery**: Home Assistant periodically polls for new official releases and displays a notification banner when a newer version is published.
2. **Encrypted Native OTA Transfer (Port 3232)**: When you click **Install / Update**:
   - Home Assistant retrieves and validates the release binary (`pawsync_ota_update.bin`), stripping container wrappers for native ESPHome flashing.
   - It establishes a direct TCP connection to the feeder's OTA listener on port `3232`.
   - It executes a cryptographic SHA-256 challenge-response handshake using the unique per-device OTA password assigned during initial provisioning.
   - It streams the firmware blocks with a live progress bar (0% → 100%) directly in your dashboard.
3. **Dual-Partition Ping-Pong Switching**: The ESP32 writes the firmware to its secondary partition, validates partition CRC integrity, and updates the bootloader otadata record.
4. **Autonomous Adoption**: The feeder reboots in ~30–45 seconds and reconnects to your local Wi-Fi network and ESPHome Native API (`port 6053`). **All feeding schedules, portion gram calibrations, eating speed sensors, and Lovelace cards remain 100% preserved.**

### Safety & Overwrite Protection Interlock
To ensure you never accidentally overwrite your factory stock firmware:
- When you first onboard a factory feeder, the alternate partition still contains pristine stock firmware.
- The feeder's embedded zero-teardown backup server automatically transfers a complete copy of the stock firmware and NVS calibration directly to Home Assistant storage (`/config/pawsync_backups/<mac>/`).
- **Safety Interlock**: If you trigger an update before this backup has completed, PawSync **blocks** the OTA process to protect you from losing your factory firmware. You can check `sensor.<feeder_name>_factory_firmware_backup` (which displays `Backed Up` when secured). Once safely archived, updates proceed smoothly.

---

## ⏪ 1-Click Factory Stock Rollback (Zero Teardown)

Unlike conventional ESPHome conversions where flashing custom firmware permanently replaces your stock software, PawSync includes a built-in **Zero-Teardown Wireless Rollback Engine**. You can revert your feeder to 100% factory VeSync operation at any time without opening the unit or using a screwdriver.

### Zero-Teardown Wireless Restore
- **Preserved Across Updates**: Even after upgrading through multiple ESPHome versions (e.g. `v1.4.1` → `v1.5.0`), your original factory stock firmware and factory load-cell calibration remain safely archived on your Home Assistant host:
  ```text
  /config/pawsync_backups/<mac>/stock_firmware.bin
  /config/pawsync_backups/<mac>/cal_<mac>.bin
  ```
- **Over-the-Air Re-flash**: Home Assistant connects to the feeder running ESPHome on port `3232` and flashes the archived genuine stock firmware binary directly over Wi-Fi.
- **Factory Operation**: The feeder reboots into genuine stock VeSync firmware, developer TCP port `55555` reopens, and the feeder can be immediately adopted back into the official VeSync smartphone app with calibrated weight measurements intact.

### Step-by-Step UI Procedure
1. In Home Assistant, navigate to **Developer Tools** -> **Actions** (or **Services** in older versions).
2. Select action: **`pawsync.restore_stock_firmware`**.
3. Toggle **Confirm Factory Restore** to `true` (checked).
   *(If you have multiple feeders configured, specify the feeder's `host` IP or `mac`).*
4. Click **Perform Action**.
5. Home Assistant streams the stock binary over Port 3232. Within 15–30 seconds, the feeder reboots back into factory stock firmware and is ready for the official VeSync mobile app.

> [!TIP]
> For advanced recovery methods, partition layout diagrams, or hardware serial recovery, refer to the [Stock Firmware Rollback & Disaster Recovery Runbook](STOCK_ROLLBACK_AND_RECOVERY.md).

---

## 🛠️ Hardware Teardown, UART Pinout & Flash Backup/Restore Guide

Even though the Home Assistant integration offers 100% wireless OTA flashing, **creating a physical flash backup before modifying any firmware is the safest best practice.** If anything goes wrong, a 4MB hardware flash backup guarantees your feeder can always be restored to its exact factory state.

### Tools Required
- **Phillips #1 screwdriver**
- **3.3V USB-to-UART Serial Adapter** (e.g. CP2102, FT232RL, CH340G, or Raspberry Pi) — *Must be set to 3.3V logic level!*
- **Dupont jumper wires** or test probes (pogo pins / alligator clips)
- **Computer with Python 3 and `esptool` installed**:
  ```bash
  pip install esptool
  ```

---

### Step 1: Safe Disassembly
1. **Disconnect Power**: Unplug the 5V DC power adapter from the feeder.
2. **Remove Batteries**: Open the battery compartment on the bottom and remove all 4 AA backup batteries.
3. **Remove Removable Parts**: Remove the food hopper, lid, and stainless steel food bowl.
4. **Expose Base Screws**: Flip the base upside down. Using a flat tool or fingernail, gently peel back the 4 circular rubber feet to expose the 4 recessed Phillips screws underneath.
5. **Open Bottom Shell**:
   - Unscrew the 4 Phillips screws.
   - **CAUTION**: When lifting the bottom base plate, lift slowly and gently! The load cell scale wiring, motor cable, and front button harness connect between the lower and upper base. Do not pull or snap these wires.
   - Locate the main logic board hosting the **Espressif ESP32-C3** module and the **Sinowealth SC95F8766P** coprocessor.

---

### Step 2: UART Pinout & Wiring

Locate the labeled test pads adjacent to the ESP32-C3 module on the logic board:

| Test Pad / Pin | ESP32-C3 Function | USB-to-UART Adapter Pin | Notes |
| :--- | :--- | :--- | :--- |
| **`GND`** | Ground | **`GND`** | Common ground reference |
| **`TX`** | `GPIO21` (UART0 TX / Serial) | **`RX`** | Adapter receives from ESP32 |
| **`RX`** | `GPIO20` (UART0 RX / Serial) | **`TX`** | Adapter transmits to ESP32 |
| **`BOOT`** | `GPIO9` (Strapping Pin) | **`GND`** (Temporary) | Hold to GND during power-on for download mode |
| **`3V3`** | 3.3V VDD | *Leave Disconnected* | **Do NOT connect adapter 3.3V!** |

> [!NOTE]
> **UART Architecture Disambiguation:**
> - **UART0 (`GPIO21` TX / `GPIO20` RX)**: Dedicated to the service test pads for serial flashing and ESP-IDF console logs at 115200 baud.
> - **UART1 (`GPIO19` TX / `GPIO18` RX)**: Dedicated internal serial bus hardwired to the Sinowealth SC95F8766P motor/scale coprocessor at 115200 baud (8N1).
> - **USB-Serial-JTAG**: Because the ESP32-C3 uses `GPIO18` (D-) and `GPIO19` (D+) for its internal USB-JTAG controller, wiring them to the coprocessor disables native USB-JTAG. Flashing over wire must be performed via the UART0 test pads using a 3.3V USB-to-UART serial adapter.

> [!WARNING]
> **CRITICAL ELECTRICAL SAFETY RULES:**
> 1. **3.3V LOGIC ONLY**: The ESP32-C3 is NOT 5V tolerant. Connecting 5V to the ESP32 GPIOs will permanently destroy the chip. Ensure your USB-UART adapter has its logic jumper set to **3.3V**!
> 2. **POWER THE FEEDER FROM ITS DC ADAPTER**: Do **not** power the ESP32 from the USB-to-UART adapter's 3.3V power pin. Wi-Fi calibration and flash writes cause transient current spikes (>500mA) that will brown out or damage the serial adapter. Plug the feeder's original 5V DC power cable into the wall, and connect only `TX`, `RX`, and `GND` to your USB-UART adapter.

---

### Step 3: Enter Bootloader (Download) Mode
1. Ensure the feeder is powered OFF (unplugged, no batteries).
2. Connect `TX`, `RX`, and `GND` to your 3.3V USB-to-UART adapter, and plug the adapter into your computer.
3. Use a jumper wire or paperclip to temporarily connect the **`BOOT` (`GPIO9`)** test pad to **`GND`**.
4. While holding `GPIO9` to `GND`, plug in the feeder's 5V DC power cable.
5. After 2 seconds, release `GPIO9`.
6. Verify your computer detects the serial port (e.g. `/dev/ttyUSB0` on Linux, `/dev/cu.usbserial-*` on macOS, or `COM3` on Windows).
7. Test communication:
   ```bash
   esptool.py --chip esp32c3 -p /dev/ttyUSB0 chip_id
   ```
   You should see: `Detecting chip type... ESP32-C3`.

---

### Step 4: Perform Full 4MB Byte-for-Byte Factory Backup
Run the following command to create an exact, complete image of the entire 4MB SPI Flash:

```bash
esptool.py --chip esp32c3 -p /dev/ttyUSB0 -b 921600 read_flash 0x0 0x400000 pawsync_factory_4MB_backup.bin
```

> [!TIP]
> **Verify Backup Integrity:**
> - Ensure the resulting file is **exactly 4,194,304 bytes** (4MB):
>   ```bash
>   ls -la pawsync_factory_4MB_backup.bin
>   ```
> - Store this file in a safe location (cloud storage, external drive). This file contains your unit's unique factory calibration, MAC address, and pristine stock firmware.

#### (Optional) Individual Partition Backups
You can also back up individual partitions according to `partitions.csv`:
```bash
# Bootloader (0x0 - 0x8000)
esptool.py --chip esp32c3 -p /dev/ttyUSB0 read_flash 0x0 0x8000 bootloader_backup.bin

# Partition Table (0x8000 - 0x9000)
esptool.py --chip esp32c3 -p /dev/ttyUSB0 read_flash 0x8000 0x1000 partitions_backup.bin

# App Slot 0 / ota_0 (0x10000 - 0x150000, 1.25MB)
esptool.py --chip esp32c3 -p /dev/ttyUSB0 read_flash 0x10000 0x140000 ota0_backup.bin

# App Slot 1 / ota_1 (0x150000 - 0x290000, 1.25MB)
esptool.py --chip esp32c3 -p /dev/ttyUSB0 read_flash 0x150000 0x140000 ota1_backup.bin
```

---

### Step 5: Disaster Recovery (Restoring Full Factory Backup)
If your feeder ever becomes unresponsive, fails an update, or is completely bricked:

1. Put the device into bootloader mode (hold `GPIO9` to `GND` during power-up).
2. Flash your 4MB backup image back to offset `0x0`:
   ```bash
   esptool.py --chip esp32c3 -p /dev/ttyUSB0 -b 921600 write_flash 0x0 pawsync_factory_4MB_backup.bin
   ```
3. Once completed, power-cycle the feeder (unplug and replug the 5V DC cable without holding `GPIO9`).
4. The feeder will boot immediately into its original stock factory firmware with factory calibration and cloud credentials 100% restored.

---

## Detailed Documentation

- [**Guided Onboarding Walkthrough**](ONBOARDING_GUIDE.md): Visual, step-by-step adoption guide.
- [**Flashing & Firmware Architecture**](FLASHING_WIZARD.md): Deep dive into wireless OTA, WebSerial, and ESPHome CLI methods.
- [**Stock Rollback & Recovery Runbook**](STOCK_ROLLBACK_AND_RECOVERY.md): Exact instructions for rolling back to factory stock firmware to test clean onboarding from scratch.

---

## Technical Specifications

| Parameter | Specification |
| :--- | :--- |
| **Target Hardware** | Pawsync PPF-R361S Smart Pet Feeder |
| **Microcontroller** | Espressif ESP32-C3FH4 (Single-core RISC-V @ 160MHz) |
| **Flash Memory** | 4MB Embedded SPI NOR Flash |
| **Coprocessor** | Sinowealth SC95F8766P (Motor drive, scale ADC, button handling) |
| **Communication Bus** | Full-Duplex UART1 @ 115200 Baud 8N1 (ESP32 `GPIO19` TX / `GPIO18` RX <-> Coprocessor). UART0 (`GPIO21` TX / `GPIO20` RX @ 115200) is dedicated to external flashing/debug test pads. |
| **Local Framework** | ESPHome (ESP-IDF Framework with Native API) |
| **Home Assistant Compatibility** | HA Core 2024.1+ through 2026.x |

---

## License

This project is licensed under the [MIT License](LICENSE).
