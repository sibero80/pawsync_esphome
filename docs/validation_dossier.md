# Pawsync PPF-R361S Smart Pet Feeder: Technical Validation Dossier

> **Device:** Pawsync Smart Pet Feeder (`PPF-R361S` / `PPF-R361S-WUS`)  
> **Vendor Model ID:** `VS_WB_PFM_PPF-R361S-WUS_US` (BLE ID: `92`)  
> **Prepared For:** Independent Peer Agent Review & Verification  
> **Workspace:** [`/root/pawsync_oma`](file:///root/pawsync_oma)  
> **Firmware Target:** ESP32-C3FH4 (4MB Flash, RISC-V 160MHz) + Sinowealth SC95F8766P Coprocessor  
> **Repository Commit:** [`9f37d53`](file:///root/pawsync_oma)

---

## Executive Summary

This dossier compiles the four authoritative engineering documents reverse-engineered from the factory flash dump ([`esp32c3_dump.bin`](file:///root/pawsync_oma/esp32c3_dump.bin)) and the official companion Android application (`com.pawsync.pet` v1.1.32). These documents provide an exhaustive reference for an independent validating agent to verify hardware interconnects, UART protocol framing, feature parity, offline schedule persistence, and Home Assistant integration architecture.

```
+--------------------------------------------------------------------------------------------------+
|                                  VALIDATION DOSSIER SITEMAP                                      |
+-------------------+------------------------------------------------------------------------------+
| Document 1        | Hardware Architecture, Wiring & Stock Firmware Feature Catalog               |
|                   | Link: docs/01_hardware_and_discovered_features.md                            |
+-------------------+------------------------------------------------------------------------------+
| Document 2        | Companion App Feature Flows, Cloud Transport & Protocol Interaction          |
|                   | Link: docs/02_apk_feature_flow_and_protocol.md                               |
+-------------------+------------------------------------------------------------------------------+
| Document 3        | Stock Firmware to ESPHome Feature Parity Matrix & Architecture Specification |
|                   | Link: docs/03_stock_to_esphome_parity_matrix.md                              |
+-------------------+------------------------------------------------------------------------------+
| Document 4        | Home Assistant Integration Design Document & User Experience Specification   |
|                   | Link: docs/04_home_assistant_integration_design.md                           |
+-------------------+------------------------------------------------------------------------------+
```

---

## 1. Document 1: Hardware Components, Wiring & Discovered Features

*Full Document Reference:* [`docs/01_hardware_and_discovered_features.md`](file:///root/pawsync_oma/docs/01_hardware_and_discovered_features.md)

### 1.1 Microcontroller Breakdown
- **Master SoC:** Espressif **ESP32-C3FH4** (32-bit RISC-V @ 160 MHz, 400 KB SRAM, 4 MB embedded Quad-SPI flash). Handles Wi-Fi, BLE, SNTP, audio streaming, NVS schedule storage, and Home Assistant Native API.
- **Dedicated Coprocessor:** Sinowealth **SC95F8766P** (high-speed 1T 8051 @ 32 MHz, 64 KB Flash, 4 KB SRAM, integrated EEPROM). Handles motor H-bridge PWM, 24-bit strain-gauge Sigma-Delta ADC, optical sensors, and safety interlocks.
- **Audio Amplifier:** **NS4168** (3.2 W mono Class-D amplifier, standard I2S bus, GPIO0 shutdown control).

### 1.2 Interconnect Pinout & Signal Mapping

| Pin | Net Name | Direction | Bus / Interface | Function |
|---|---|:---:|:---:|---|
| **GPIO0** | `AMP_EN` | Output | Digital GPIO | NS4168 Class-D amplifier enable (Active HIGH; pulled low when idle). |
| **GPIO1** | `I2S_WS` | Output | I2S LRCLK | Word Select clock at 32 kHz. |
| **GPIO4** | `I2S_BCK` | Output | I2S BCLK | Continuous bit clock for 16-bit mono audio samples. |
| **GPIO5** | `I2S_DATA` | Output | I2S DOUT | Serial PCM audio data stream to amplifier. |
| **GPIO8** | `LED_STATUS`| Output | Digital GPIO | Front status LED (Active LOW). |
| **GPIO9** | `BOOT_BTN` | Input | Digital GPIO | Bootloader strap pin / physical setup button. |
| **GPIO18** | `UART_RX` | Input | UART0 | Telemetry and ACKs from SC95F8766P coprocessor (115200 8N1). |
| **GPIO19** | `UART_TX` | Output | UART0 | Commands to SC95F8766P coprocessor (115200 8N1). |

### 1.3 Binary UART Protocol Framing
$$\mathbf{[0xA5]} \quad \mathbf{[0x02]} \quad \mathbf{[Len_{LE}]} \quad \mathbf{[Opcode_{MSB}]} \quad \mathbf{[Opcode_{LSB}]} \quad \mathbf{[Payload\dots]} \quad \mathbf{[Checksum]}$$
* **Magic:** `0xA5`, Version: `0x02`, Length: 16-bit LE byte count from opcode through payload.
* **Checksum:** $\sim\sum(\text{Header}\dots\text{Payload}) \ \& \ 0\text{xFF}$.
* **Opcode Inventory (22 Discovered Opcodes):**
  - Dispense & Motor: `0x5501` (Dispense), `0x5502` (Motor State), `0x5503` (Result), `0x5504` (Anti-Jam Reverse).
  - Scale & Weight: `0x55A1` (Read Weight), `0x55A2` (Stream Weight), `0x55A3` (Tare Scale), `0x55A4` (Calibration ADCs).
  - Sensors & Peripherals: `0x5521` (Lid), `0x5522` (Hopper Level), `0x5523` (Chute Blockage), `0x5541` (Power/Battery ADC).
  - Configuration & Audio: `0x5511` (Child Lock), `0x5531` (Meal Chime), `0x5532` (Volume), `0x55FF` (Coprocessor Version).

---

## 2. Document 2: Companion App Feature Flows & Protocol Interaction

*Full Document Reference:* [`docs/02_apk_feature_flow_and_protocol.md`](file:///root/pawsync_oma/docs/02_apk_feature_flow_and_protocol.md)

### 2.1 APK Architecture Findings
- **Package:** `com.pawsync.pet` (v1.1.32, build 46, target SDK 35).
- **100% Native Implementation:** Device panel logic is compiled directly in `classes*.dex` (`com.pawsync.pet.device.ui.device.feeder.*`). No remote H5 or React Native bundles are required.
- **Cloud Transport:** All communication tunnels through `POST /pet/api/deviceManaged/v1/bypassV2` and AWS IoT broker `34.225.33.72:3883` over TLS 1.2.
- **Why Cloud Spoofing Fails:** Stock ESP32-C3 firmware bundles Amazon Root CA certificates and validates broker certificates strictly; local DNS/DNAT hijacking triggers SSL verification failure. Local ESPHome firmware replacement is the only clean architectural path.

### 2.2 Core Application Workflows
1. **Manual Dispense:** App user selects portions (1–20) $\to$ translates to target grams $\to$ cloud bypass $\to$ UART `0x5501` $\to$ live 5 Hz weight streaming $\to$ final dispense report.
2. **On-Device Offline Schedules:** Supports up to 7 plan profiles (`maxPlanCount = 7`) and 10 meals/day per plan (`maxMealCountPerPlan = 10`). Written to ESP32 flash partition `plan_param`. Runs autonomously offline without internet access.
3. **Kibble Portion Density Wizard:** Tares empty bowl (`0x55A3`) $\to$ Dispenses 3 portions $\to$ Settles 3.0s $\to$ Divides weight by 3 $\to$ Saves grams per portion to NVS.
4. **Intelligent Feeding:** Measures leftover food in bowl prior to scheduled feed; subtracts leftovers from target meal to prevent bowl overfilling.

---

## 3. Document 3: Stock-to-ESPHome Parity Matrix & Component Architecture

*Full Document Reference:* [`docs/03_stock_to_esphome_parity_matrix.md`](file:///root/pawsync_oma/docs/03_stock_to_esphome_parity_matrix.md)

### 3.1 Parity Summary Table

| Functional Domain | Discovered Features | Parity Status | Implementation Reference |
|---|:---:|:---:|---|
| **Motor & Dispensing** | 5 | **100% Parity** | Portions 1–20, target grams, stall detection, anti-jam reverse ([`ppf_r361s.cpp`](file:///root/pawsync_oma/components/ppf_r361s/ppf_r361s.cpp#L120-L165)) |
| **Scale & Weighing** | 5 | **100% Parity** | Calibrated grams, zero tare, automated 3-portion density wizard, manual density adjustment |
| **Offline Schedulers** | 5 | **100% Parity** | 7 plans × 10 meals (70 slots in flash NVS), repeat bitmasks, intelligent leftover deduction |
| **Sensors & Alarms** | 4 | **100% Parity** | Chute blockage, hopper low/empty, lid open, bowl disconnected |
| **Power Management** | 3 | **100% Parity** | Dual-power detection (AC vs 3x D-cells), battery voltage ADC, percentage sensor |
| **Audio & Prompts** | 3 | **Enhanced** | Stock `meal_call.wav` playback + modern ESPHome 2026.x `speaker`/`media_player` TTS streaming |
| **Safety & Rollback** | 2 | **Enhanced** | Child lock switch + 1-command bit-accurate factory flash rollback ([`docs/flashing_guide.md`](file:///root/pawsync_oma/docs/flashing_guide.md)) |

### 3.2 Non-Blocking C++ Architecture
The custom driver in [`components/ppf_r361s/`](file:///root/pawsync_oma/components/ppf_r361s) implements:
- Asynchronous UART state machine reading bytes without FreeRTOS task delays.
- Calibration wizard state machine coordinating tare, dispense, and settling timers.
- Automatic anti-jam recovery sequence triggering `0x5504` on motor stall.
- ESPHome `global_preferences` NVS storage for feeding schedules and calibration parameters.

---

## 4. Document 4: Home Assistant Integration Design & Blueprints

*Full Document Reference:* [`docs/04_home_assistant_integration_design.md`](file:///root/pawsync_oma/docs/04_home_assistant_integration_design.md)

### 4.1 Native API Protocol vs. MQTT
- Uses ESPHome Native API (Port 6053 TCP Protobuf with Noise encryption).
- Eliminates external MQTT broker requirements.
- Automatic entity discovery, sub-second latency, and native TTS media streaming.

### 4.2 Entity Inventory Breakdown
- **Sensors (7):** Bowl Weight (`g`), Dispensed Today (`g`), Meals Today (`count`), Battery Voltage (`V`), Battery Level (`%`), Hopper Food Level (`%`), Desiccant Remaining (`d`).
- **Binary Sensors (7):** Chute Blockage, Hopper Empty, Lid Open, Battery Power, Dispensing Active, Motor Stall, Bowl Scale Connected.
- **Controls (5 Switches, 4 Numbers):** Child Lock, Mute Chime, Schedule Master Enable, Intelligent Feeding, Slow Feeding; Manual Portions, Kibble Density (g/portion), Target Weight, Active Plan ID.
- **Buttons (5):** Feed Now, Zero Scale (Tare), Calibrate Density Wizard, Clear Jam, Reset Desiccant Timer.
- **Media Player (1):** Feeder Speaker (announcements, TTS, sound clips).
- **Text Sensors (4):** Feeder Status, Firmware Version, Coprocessor Version, Schedule Summary.

### 4.3 Blueprint Automations
1. **Pet Eating Detection:** Logs meal consumption events when bowl weight drops $\ge 5\,\text{g}$ and sends actionable push notifications.
2. **Actionable Jam Alert:** High-priority notification with mobile action buttons to reverse the motor or tare the scale.
3. **Power Outage Battery Guard:** Disables audio and reduces polling frequency during blackouts to extend D-cell battery life up to 180 days.

---

## 5. Independent Build & Verification Runbook for Validating Agent

The peer validating agent will be working in an isolated directory and independent git repository to independently build, test, and confirm all deliverables without inheriting prior build artifacts or cache cross-contamination.

### 5.1 Tool Inventory & Absolute Execution Paths

| Tool / Binary | Absolute Filesystem Path | Version / Environment | Purpose |
|---|---|---|---|
| **ESPHome CLI** | `/root/esphome/venv/bin/esphome` | ESPHome 2026.9.1 | Firmware compilation, config validation, and binary generation. |
| **Python Virtualenv** | `/root/esphome/venv/bin/python3` | Python 3.13.x (with ESPHome dependencies) | Executing ESPHome and associated tooling in dedicated virtualenv. |
| **System Python** | `/usr/bin/python3` | Python 3.13.3 (Standard Library) | Executing protocol unit tests (`vesync_proto.py`) and ELF scripts. |
| **Esptool** | `/root/esphome/venv/bin/esptool.py` | esptool v4.12.0 | ESP32-C3 image generation, flash inspection, and serial flashing. |
| **ESP-IDF Framework** | `/root/.cache/esphome/idf/frameworks/5.5.5` | ESP-IDF v5.5.5 | Underlying RTOS framework used by ESPHome for ESP32-C3. |
| **RISC-V Toolchain** | `/root/.cache/esphome/idf/tools/riscv32-esp-elf/esp-14.2.0_20260121/riscv32-esp-elf/bin/riscv32-esp-elf-objdump` | GCC 14.2.0 (riscv32-esp-elf) | ELF disassembler, symbol inspection, and header verification. |
| **Ninja Build System**| `/usr/bin/ninja` | Ninja 1.12.1 | Fast parallel C/C++ compilation engine invoked by CMake. |
| **CMake Engine** | `/usr/bin/cmake` | CMake 3.31.6 | Build script generator for ESP-IDF components. |
| **Git Version Control**| `/usr/bin/git` | Git 2.47.2 | Workspace isolation, branching, and commit auditing. |

---

### 5.2 Isolated Workspace & Separate Git Setup

To set up an independent validation environment in a separate directory (e.g., `/root/pawsync_validation`), execute the following commands:

```bash
# 1. Clone a fresh, independent working tree from the primary repository
git clone /root/pawsync_oma /root/pawsync_validation
cd /root/pawsync_validation

# 2. Verify git history and commit hash
git log -n 3 --oneline
# Expected HEAD: 9f37d53 "docs: add comprehensive validation documents 1 through 4"

# 3. Create independent secrets configuration from the template
cp secrets.yaml.example secrets.yaml

# 4. Verify the factory flash dump is present and untampered
sha256sum esp32c3_dump.bin
# Expected: 8d1970e78007f18975c255c625c37bccf2a5cfa7d76eff04f3af731fea3bb77a
```

---

### 5.3 Independent Step-by-Step Validation Procedure

#### Test 1: Protocol Codec & Checksum Verification
Run the standalone Python protocol test suite in the isolated workspace:
```bash
/usr/bin/python3 tools/proto/vesync_proto.py
```
* **Expected Outcome:** `OK (all tests passed)`.
* **Validation Criteria:** Verifies frame synchronization magic (`0xA5 0x02`), 16-bit little-endian length packing, 1's complement inverted checksum calculation (`~sum & 0xFF`), and bidirectional opcode serialization for all 22 discovered opcodes.

#### Test 2: Clean Firmware Build & Binary Generation
Invoke the ESPHome CLI to independently build the complete firmware image from scratch:
```bash
/root/esphome/venv/bin/esphome compile pawsync.yaml
```
* **Expected Compilation Metrics:**
  - **Exit Code:** `0` (Success)
  - **RAM Usage:** ~33.5% (approx. 107,734 bytes used of 321,296 bytes)
  - **Flash Usage:** ~62.0% (approx. 1,136,956 bytes used of 1,835,008 bytes allocated partition)
* **Generated Artifact Verification:**
  Verify that three build binaries are created in `.esphome/build/pawsync-feeder/build/`:
  1. `firmware.factory.bin` (Complete flashable binary starting at offset `0x0000`, containing bootloader, partition table, and app)
  2. `firmware.ota.bin` (OTA update binary for flashing over Wi-Fi / Native API)
  3. `firmware.elf` (Full ELF image containing debugging symbols for GDB / objdump)

#### Test 3: Binary Symbol & Entity Export Verification
Inspect exported symbols using the isolated RISC-V toolchain to verify that the C++ class hierarchy and state machines are linked:
```bash
/root/.cache/esphome/idf/tools/riscv32-esp-elf/esp-14.2.0_20260121/riscv32-esp-elf/bin/riscv32-esp-elf-objdump -t .esphome/build/pawsync-feeder/build/firmware.elf | grep -i "PPFR361SComponent"
```
* **Expected Outcome:** Lists symbol entries for:
  - `PPFR361SComponent::loop()`
  - `PPFR361SComponent::start_kibble_calibration()`
  - `PPFR361SComponent::dispense_portions(unsigned char)`
  - `PPFR361SComponent::tare_scale()`

#### Test 4: Solderless Factory Rollback Readiness
Verify that the factory rollback image can be parsed by `esptool.py`:
```bash
/root/esphome/venv/bin/esptool.py --chip esp32c3 image_info esp32c3_dump.bin
```
* **Expected Outcome:** Valid ESP32-C3 image report with entry point and segment headers, confirming 100% bit-accurate factory restoration capability.
