# Technical Blueprint: Dedicated HACS Home Assistant App (`pawsync_esphome`)

> **Target Repository:** `pawsync_esphome` (Standalone HACS Integration & App)  
> **Staging Directory:** [`staging/`](file:///root/pawsync_esphome/staging/)  
> **Companion Firmware Repository:** [`sibero80/pawsync`](https://github.com/sibero80/pawsync)  
> **Status:** Architecture Blueprint & Implementation Specification

---

## 1. Executive Summary

This blueprint defines the architecture and implementation specification for **`pawsync_esphome`**, a dedicated Home Assistant integration and app distributed via HACS. 

It is tailored for non-technical users who want to take full local control of their **Pawsync PPF-R361S Smart Pet Feeder** without terminal commands, hardware soldering, or manual YAML editing.

### Key Pillars:
1. **Zero-Terminal In-HA Adoption Wizard**: Converts a factory stock feeder over Wi-Fi directly inside Home Assistant's UI using an embedded local HTTP stager and authorized cloud command relay.
2. **Automated ESPHome Add-on Provisioning**: Generates `/config/esphome/pawsync-feeder.yaml` referencing remote packages, so the device immediately appears in the user's ESPHome Builder dashboard.
3. **App-Replica Frontend Dashboard & Panel**: Fully replicates the official mobile application screens inside Home Assistant:
   - Real-time animated stainless steel bowl scale with live grams display.
   - Comprehensive **Feeding Schedules Manager** with interactive meal creation and editing across all 7 plans and 10 meal slots.
   - Intelligent Feeding leftover subtraction toggle with live calculations.
   - 1-click manual feed wheel, scale tare, automated kibble portion calibration, and desiccant lifecycle management.

---

## 2. Directory Layout in `staging/`

Everything in `staging/` represents the exact root of the new standalone `pawsync_esphome` repository:

```text
staging/
├── .gitignore
├── LICENSE
├── README.md                           # Documentation for the HACS app
├── hacs.json                           # HACS integration metadata
├── custom_components/
│   └── pawsync/
│       ├── __init__.py                 # Entry point & sidebar panel registration
│       ├── manifest.json               # Home Assistant integration manifest
│       ├── const.py                    # Constants, domains, and defaults
│       ├── config_flow.py              # 4-step interactive adoption wizard
│       ├── coordinator.py              # State coordinator & API wrappers
│       ├── ota_stager.py               # Paced 8s local HTTP staging server
│       ├── vesync_relay.py             # Authorized cloud command relay client
│       ├── esphome_provisioner.py      # Automated /config/esphome/ YAML writer
│       ├── services.py                 # Schedule management helper services
│       ├── services.yaml               # HA service definitions
│       ├── translations/
│       │   └── en.json                 # UI strings for wizard and entities
│       └── frontend/
│           ├── pawsync-app-panel.js    # Full-screen sidebar app
│           └── pawsync-feeder-card.js  # Embeddable Lovelace card
└── tests/
    ├── test_config_flow.py             # Config flow & wizard tests
    ├── test_ota_stager.py              # Staging server & pacing tests
    └── test_schedule_helpers.py        # Bitmask and schedule math tests
```

---

## 3. In-Home-Assistant Wireless Adoption Wizard

### The User Journey
```
[User opens Home Assistant]
      │
      ▼
[Settings -> Devices & Services -> Add Integration -> PawSync Feeder]
      │
      ├─► Step 1: Mode Selection
      │    • "Convert a Stock Feeder over Wi-Fi" (Default)
      │    • "Connect to already-flashed ESPHome Feeder"
      │
      ├─► Step 2: Network & Account Setup
      │    • Home Wi-Fi SSID & Password (baked into firmware)
      │    • VeSync Account Email & Password (used once to obtain temporary CID/token)
      │
      ├─► Step 3: Automated Wireless Conversion (Background Task)
      │    • Integration spins up local HTTP stager on HA port 8000
      │    • Integration calls VeSync bypassV2 upFirmware pointing to HA local IP
      │    • Stock feeder connects to Home Assistant
      │    • Stager sends 129-byte VeSync header, pauses 8.0s for SPI flash erase, streams binary
      │    • Feeder flashes ota_0 and reboots into ESPHome Native API
      │
      └─► Step 4: Completion & ESPHome Provisioning
           • Integration writes /config/esphome/pawsync-feeder.yaml
           • Device adopted into Home Assistant; PawSync sidebar panel appears!
```

---

## 4. Frontend Dashboard: Mobile App Replica

### Screen 1: Feeder Overview (Main Tab)
- **Live Bowl Scale**: An SVG graphic of the stainless bowl that fills with kibble dynamically as grams increase from $0\text{g}$ to $500\text{g}$.
- **Next Meal Countdown**: Large hero card showing next meal name, target portions, calculated grams, and a live countdown timer.
- **Portions Today Ring**: Circular progress bar tracking daily portion consumption vs target.
- **Manual Feed Control**: Radial portion wheel ($1\text{–}10$ portions) with immediate "Feed Now" button.
- **Quick Status Badges**:
  - AC Wall Power (`Connected` / `Battery Mode`)
  - Food Hopper Level (`Full` / `Low`)
  - Silica Desiccant Countdown (`X days remaining` + Reset button)
  - Child Lock switch

### Screen 2: Feeding Schedules Manager (Schedule Tab)
- **Plan Selector**: Dropdown / tabs to switch between **Plan 1 (Daily)** through **Plan 7**.
- **Active Meals List**: Cards showing configured meals for the active plan (Meal 1 to Meal 10).
- **Interactive Meal Editor (Modal Popup)**:
  - **Time Picker**: 24h or 12h AM/PM selector.
  - **Portion Slider**: $1\text{–}20$ portions, dynamically displaying calculated weight based on current calibrated density (e.g. `2 portions = 23.0g`).
  - **Day-of-Week Chips**: Toggleable buttons for `[M] [T] [W] [T] [F] [S] [S]`, plus presets `[Daily]`, `[Weekdays]`, `[Weekends]`.
  - **Meal Call Chime Switch**: Toggle sound prompt playback.
  - **Save Action**: Calls `esphome.pawsync_feeder_set_meal_schedule` with pre-computed day bitmask.
  - **Delete Action**: Disables meal and refreshes list.
- **Intelligent Feeding Switch**: Toggle automatic leftover deduction with an informative popup explaining the feature.

### Screen 3: Maintenance & Calibration (Settings Tab)
- **Bowl Scale Tare Button**: One-click zeroing with empty bowl prompt.
- **Kibble Density Portion Calibration Wizard**: Guided 4-step wizard (Tare -> Dispense 2 portions -> Settling delay -> Save calibrated grams/portion).
- **Silent Night Mode**: Toggle sleep mode (silences LEDs and chimes).
- **Slow Feed Mode**: Toggle staged interval dispensing.
- **Factory Firmware Rollback Tool**: One-click restore to stock factory firmware partition `ota_1` with confirmation unlock switch.

---

## 5. Verification & Quality Gates

1. **HACS Strict Compliance**: Verified against HACS validation rules (`hacs.json`, `manifest.json`, no root pollution).
2. **Zero-Terminal Validation**: The config flow must successfully run the local HTTP stager and dispatch the update without requiring any terminal access.
3. **ESPHome Add-on File Interoperability**: The generated YAML must be immediately parseable by the official ESPHome Builder Add-on.
4. **Schedule Bitmask Math**: Unit tests verify that bitwise day conversions (`0x7F` = 127 Daily, `0x3E` = 62 Weekdays, `0x41` = 65 Weekends) match the C++ engine in `ppf_r361s.cpp`.
