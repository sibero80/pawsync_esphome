# PawSync Smart Pet Feeder for Home Assistant

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![ESPHome Version](https://img.shields.io/badge/ESPHome-2024.6%2B-blue.svg)](https://esphome.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![HA Minimum](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue.svg)](https://home-assistant.io)

**100% Local, Cloud-Free Control of the Pawsync PPF-R361S Smart Pet Feeder in Home Assistant.**

Convert your factory stock Pawsync feeder over Wi-Fi directly inside Home Assistant's UI without opening a terminal, soldering, or taking the device apart. Enjoy zero latency, zero cloud dependency, an authentic mobile-app-replica Lovelace card, and instant rollback safety.

---

## Key Features

- **Guided In-HA Adoption Wizard**:
  - Connects to your Pawsync or VeSync account to capture device hardware credentials (CID, MAC, tokens).
  - Multi-feeder discovery: adopt one or multiple feeders simultaneously.
  - Automated wireless flashing over your local Wi-Fi network using an embedded, paced HTTP stager.
- **Official App-Replica Lovelace Feeder Card (v1.2.0)**:
  - Bundled automatically—no manual JavaScript resource installation required.
  - **Live Bowl Scale**: Animated stainless steel bowl filling dynamically with kibble, featuring a glowing pulsing indicator when your pet is eating.
  - **Dynamic Calibrated Density**: Portions calculate in real time using your measured grams-per-portion density (e.g. 11.5g).
  - **4 Essential Daily Stats**:
    1. *Today's Planned Serving* (calculated sum of all active scheduled meal portions).
    2. *Last Eaten* (exact grams consumed and human-readable time).
    3. *Total Eaten Today* (accumulated consumption with automatic midnight rollover).
    4. *Next Scheduled Meal* (name, target time, and portion breakdown).
  - **Collapsible 7-Plan Schedule Manager**:
    - Manage up to 7 distinct feeding plans with 10 meal slots each.
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

The integration automatically registers `/pawsync/pawsync-feeder-card.js` in your Home Assistant frontend.

To add the card to your dashboard:
1. Click **Edit Dashboard** -> **Add Card**.
2. Select **Custom: PawSync Feeder Card** or paste the following YAML into a Manual card:

```yaml
type: custom:pawsync-feeder-card
# Optional overrides:
# title: "Fluffy's Feeder"
# default_collapsed: true
```

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
| **Communication Bus** | Full-Duplex UART @ 9600 Baud (ESP32 `GPIO20`/`GPIO21` <-> Coprocessor) |
| **Local Framework** | ESPHome (ESP-IDF Framework with Native API) |
| **Home Assistant Compatibility** | HA Core 2024.1+ through 2026.x |

---

## License

This project is licensed under the [MIT License](LICENSE).
