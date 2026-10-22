# Pawsync PPF-R361S: Hardware Architecture, Wiring & Stock Firmware Feature Catalog

> **Target Device:** Pawsync Smart Pet Feeder (Model `PPF-R361S` / `PPF-R361S-WUS`)  
> **VeSync Model Identifier:** `VS_WB_PFM_PPF-R361S-WUS_US` (BLE Model ID: `92`)  
> **Stock Firmware Version Extracted:** `v1.2.5` (Built Mar 5, 2025 15:05:20 CST, active partition `ota_1`)  
> **Source Evidence:** Extracted flash dump ([`esp32c3_dump.bin`](file:///root/pawsync_oma2/esp32c3_dump.bin), SHA-256: `8d1970e78007f18975c255c625c37bccf2a5cfa7d76eff04f3af731fea3bb77a`) and companion Android APK (`com.pawsync.pet` v1.1.32).

---

## 1. System Overview & Dual-MCU Architecture

The Pawsync PPF-R361S pet feeder utilizes an asymmetric master-coprocessor architecture. High-level networking, cloud connectivity, timekeeping, and audio decoding are handled by an Espressif ESP32-C3 SoC, while all real-time motor control, ADC sampling, optical sensing, tactile buttons, and safety interlocks are delegated to a dedicated Sinowealth 8051-based coprocessor.

```
                      +------------------------------------------+
                      |         Pawsync PPF-R361S Feeder         |
                      |                                          |
                      |   +----------------------------------+   |
                      |   |      Espressif ESP32-C3FH4       |   |
                      |   |      (Wi-Fi / BLE / Audio /      |   |
                      |   |       High-Level Scheduling)     |   |
                      |   +-----------------+----------------+   |
                      |                     |                    |
                      |         Full Duplex UART (115200 8N1)    |
                      |         GPIO18 (RX) <--- TXD             |
                      |         GPIO19 (TX) ---> RXD             |
                      |                     |                    |
                      |   +-----------------+----------------+   |
                      |   |    Sinowealth SC95F8766P MCU     |   |
                      |   |     (Real-Time Motor / Scale /   |   |
                      |   |       Sensors / Power Telemetry) |   |
                      |   +---+---------+---------+------+---+   |
                      |       |         |         |      |       |
                      +-------|---------|---------|------|-------+
                              |         |         |      |
                              v         v         v      v
                          Load Cell   Motor     Optical  Battery /
                         (Bowl Scale) H-Bridge  Sensors  DC Power
```

### 1.1 Master Microcontroller: Espressif ESP32-C3FH4
- **Core Architecture:** 32-bit RISC-V single-core processor running at 160 MHz.
- **Embedded Memory:** 400 KB internal SRAM, 384 KB ROM, 8 KB RTC memory.
- **Embedded Flash:** 4 MB internal SPI flash (Quad SPI @ 80 MHz, chip ID: `0x204016`).
- **Wireless Interface:** 2.4 GHz 802.11b/g/n Wi-Fi + Bluetooth 5.0 LE.
- **Role in Feeder:**
  - Manages network connectivity, SNTP time synchronization, and Home Assistant integration via ESPHome Native API.
  - Maintains 7 on-device feeding plan profiles in non-volatile storage (NVS / `ESPPreferences`).
  - Streams 32 kHz 16-bit mono audio over I2S to the onboard Class-D audio amplifier.
  - Translates user commands into binary KLV frames transmitted over UART to the coprocessor.
  - Synchronizes wall-clock Unix time (`0x55A1`) and pushes meal schedules (`0x55A6`) to the coprocessor for autonomous battery execution.

### 1.2 Dedicated Coprocessor: Sinowealth SC95F8766P
- **Core Architecture:** High-speed 1T 8051 core operating at 32 MHz.
- **Memory:** 64 KB on-chip Flash memory, 4 KB SRAM, integrated EEPROM.
- **Analog Front End (AFE):** Built-in high-precision 24-bit Sigma-Delta ADC designed for strain-gauge weight measurements.
- **PWM / Motor Drivers:** Hardware complementary PWM generator driving an internal H-bridge for bidirectional motor rotation.
- **Role in Feeder:**
  - Continuously samples the 24-bit load cell in the bowl base and performs digital filtering.
  - Stores factory 3-point strain-gauge calibration offsets in internal EEPROM (`point0GramAD`, `point500GramAD`, `point1000GramAD`).
  - Controls auger motor rotation, measures motor current for stall/jam detection, and automatically executes anti-jam reverse rotation.
  - Drives and samples infrared optocouplers for kibble low-level detection and food chute blockage.
  - Monitors the physical front-panel manual feed (`K2`) and lock/reset (`K4`) buttons autonomously.
  - Drives front-panel status/Wi-Fi LEDs and internal buzzer.
  - Executes autonomous feeding schedules on internal hardware RTC even when AC power is disconnected and Wi-Fi is sleeping.

### 1.3 Audio Amplifier & Transducer Subsystem
- **Amplifier IC:** NS4168 (Class-D mono audio power amplifier, delivering up to 3.2 W into a 4 Ω load).
  - Digital input via standard I2S (Inter-IC Sound) bus.
  - Hardware shutdown pin controlled by ESP32-C3 GPIO0 (`AMP_EN` / `NS4168_CTRL`). Active **HIGH** during playback; pulled LOW during idle to eliminate quiescent current and audio hiss.
- **Speaker:** 4 Ω, 2 W, 36 mm dynamic speaker housed in an acoustic resonance chamber inside the lower chassis.
- **Stock Audio Asset:** Meal call announcement stored at partition `custom_data` at flash offset `0x2FF000` (length: 256,228 bytes), formatted as standard RIFF WAVE, 32 kHz, 16-bit mono PCM.

---

## 2. Pinout, Wiring & Electrical Interconnects

### 2.1 ESP32-C3 Pin Allocation Matrix
Verified via static disassembly of `vhal_i2s_init` (`0x42007210`), `vhal_gpio_init`, and `ves_uart_init` (`0x4201AA38`):

| ESP32-C3 Pin | Net Name | Direction | Bus / Interface | Connected Peripheral / Hardware Trace |
|---|---|:---:|:---:|---|
| **GPIO0** | `NS4168_CTRL` | Output | Digital GPIO | `NS4168` Pin 1 (PA Enable). Active **HIGH** for playback; external pull-down keeps amp muted during boot. |
| **GPIO1** | `I2S_WS` | Output | I2S Word Select | `NS4168` Pin 2 (LRCLK / Frame Sync at 32 kHz). |
| **GPIO4** | `I2S_BCK` | Output | I2S Bit Clock | `NS4168` Pin 3 (Continuous BCLK for 16-bit mono samples). |
| **GPIO5** | `I2S_DATA_OUT` | Output | I2S Serial Data | `NS4168` Pin 4 (Serial PCM audio data stream to amplifier). |
| **GPIO9** | `BOOT_BTN` | Input | Digital Input | Boot strap / pull-down test pad for flashing mode (`LOW` on boot enters ROM bootloader). |
| **GPIO18** | `UART_RX` | Input | Hardware UART0 | Connected to `SC95F8766P` TXD (115200 8N1). Receives telemetry, weight, and ACKs. |
| **GPIO19** | `UART_TX` | Output | Hardware UART0 | Connected to `SC95F8766P` RXD (115200 8N1). Transmits commands and schedule tables. |
| **GPIO20** | `UART0_RXD` | Input | Console UART | Test pad / Console Debug Header (`RXD0`). Standard ESP32-C3 console UART. |
| **GPIO21** | `UART0_TXD` | Output | Console UART | Test pad / Console Debug Header (`TXD0`). Standard ESP32-C3 console UART. |
| **GPIO2** | `NC / STRAP` | - | Floating | ESP32-C3 boot strap pin (unrouted). |
| **GPIO8** | `NC / STRAP` | - | Pull-up | ESP32-C3 boot strap pin (internally pulled up; unrouted). **Status LEDs are on coprocessor.** |

> [!IMPORTANT]
> **UART Pin Multiplexing:** In ESP32-C3 silicon, GPIO18 and GPIO19 are shared with the internal USB-Serial-JTAG controller. The firmware reconfigures the GPIO matrix to release USB-JTAG pins and attach UART0 peripheral to GPIO18/19. The ESPHome logger UART must have `baud_rate: 0` to prevent collision on GPIO18/19.

### 2.2 SC95F8766P Coprocessor Peripheral Wiring
The following hardware peripherals are **NOT connected to the ESP32-C3**; they are controlled solely by the `SC95F8766P` coprocessor and accessed by ESPHome through the UART protocol:

| Peripheral | Component | Physical Connection | Controlled Via |
| :--- | :--- | :--- | :--- |
| **Dispense Motor** | `JS50T-5V-8R` | Mainboard 4-pin motor connector | UART Opcode `0x5018` |
| **Food Scale Bridge** | Detachable load cell | 4-wire dock (Red, Black, Green, White) directly to SC95F ADC | UART Opcodes `0x5593` (read), `0x55A3` (tare) |
| **Food Chute IR Sensors**| `TX1DM/RX1DM`, `TX2DM/RX2DM` | UI daughterboard ribbon cable to SC95F GPIOs | UART Opcode `0x5593` (Key 4) |
| **Tactile Buttons** | `K2` (Feed), `K4` (Lock/Reset) | UI daughterboard ribbon cable to SC95F GPIOs | Handled autonomously by MCU |
| **Status LEDs** | `LED1`, `LED3` (Wi-Fi, Status) | UI daughterboard ribbon cable to SC95F GPIOs | UART Opcode `0x5140` / `0x5105` |
| **Audible Buzzer** | `BUZZ1` | Mainboard footprint to SC95F PWM | UART Opcode `0x5141` |

### 2.3 Solderless Programming Test Points
Accessible by removing 4 Phillips screws from the chassis base plate:

| PCB Pad Silkscreen | Connected Net | Programmer Connection |
|---|---|---|
| `3V3` | 3.3V System Rail | 3.3V Output of USB-to-UART Adapter (or powered via 5V DC Jack) |
| `GND` | System Ground | GND of USB-to-UART Adapter |
| `TX` | ESP32-C3 GPIO19 | RXD of USB-to-UART Adapter |
| `RX` | ESP32-C3 GPIO18 | TXD of USB-to-UART Adapter |
| `IO9` | ESP32-C3 GPIO9 | Jumper to `GND` during power-up to enter Bootloader mode |
| `EN` / `RST` | ESP32-C3 CHIP_EN | Momentary short to `GND` to reset SoC |

---

## 3. Stock Firmware Flash Layout & Partitions

The ESP32-C3 internal 4 MB SPI flash is partitioned according to standard ESP-IDF two-stage OTA layout (extracted from partition table at offset `0x008000` of `esp32c3_dump.bin`):

| Partition | Type | Subtype | Flash Offset | Size (Hex) | Size (Bytes) | Content / Format Summary |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `bootloader` | - | - | `0x000000` | `0x008000` | 32,768 | 2nd-stage bootloader (ESP-IDF) |
| `ptable` | - | - | `0x008000` | `0x001000` | 4,096 | Partition table & MD5 checksum |
| `nvs` | `0x01` (data) | `0x02` (nvs) | `0x009000` | `0x004000` | 16,384 | System NVS: `nvs.net80211`, `phy` cal |
| `otadata` | `0x01` (data) | `0x00` (ota) | `0x00D000` | `0x002000` | 8,192 | OTA selection records (`seq=2`, `ota_1` active) |
| `phy_init` | `0x01` (data) | `0x01` (phy) | `0x00F000` | `0x001000` | 4,096 | RF PHY initialization calibration |
| `ota_0` | `0x00` (app) | `0x10` (ota0) | `0x010000` | `0x140000` | 1,310,720 | Inactive app slot (built Nov 21 2024) |
| `ota_1` | `0x00` (app) | `0x11` (ota1) | `0x150000` | `0x140000` | 1,310,720 | **Active app slot (built Mar 5 2025: v1.2.5)** |
| `usercfg` | `0x01` (data) | `0x02` (nvs) | `0x290000` | `0x004000` | 16,384 | User NVS: schedules, plans, timezone |
| `fac_data` | `0x01` (data) | `0x02` (nvs) | `0x294000` | `0x002000` | 8,192 | Factory configuration data |
| `storage` | `0x01` (data) | `0x02` (nvs) | `0x296000` | `0x010000` | 65,536 | Storage / parameters |
| `historydata` | `0x01` (data) | `0x02` (nvs) | `0x2A6000` | `0x058000` | 360,448 | Feeding and device event history log |
| `log` | `0x01` (data) | `0x02` (nvs) | `0x2FE000` | `0x000400` | 1,024 | Crash / panic log storage |
| `custom_data` | `0x01` (data) | `0x02` (nvs) | `0x2FF000` | `0x100000` | 1,048,576 | RIFF WAVE recorded voice (`meal_call.wav`, 256,228 B, 32kHz 16-bit mono) |

---

## 4. Discovered Firmware Features: Complete UART Opcode Dictionary

### 4.1 Wire Frame Encapsulation
Every frame exchanged between ESP32-C3 and SC95F8766P conforms to the confirmed VeSync MCU binary framing:

```text
+------+------+------+---------+---------+----------+-----------------------+
| 0xA5 | Type | Seq  | Len LSB | Len MSB | Checksum | Payload (Len bytes)  |
+------+------+------+---------+---------+----------+-----------------------+
  0      1      2        3         4         5              6..(5+Len)
```

- **Byte 0 (`Header Magic`)**: Fixed `0xA5` sync byte.
- **Byte 1 (`Frame Type`)**: `0x02` (Standard Command / Response / Telemetry frame; Bit 4 = Async Event `0x10`, Bit 5 = ACK Request `0x20`).
- **Byte 2 (`Sequence Number`)**: 8-bit incrementing packet counter ($0\text{–}255$).
- **Bytes 3–4 (`Payload Length`)**: 16-bit little-endian integer ($N$) representing the length of trailing payload bytes (excluding checksum). Total wire frame size is $N + 6$ bytes.
- **Byte 5 (`Checksum`)**: One's complement of modulo-256 sum of all bytes with byte 5 treated as 0:
  $$\text{Checksum} = \left(\sim \sum_{i \neq 5} \text{Frame}[i]\right) \& \text{ 0xFF}$$
  Across all $N+6$ bytes, a valid frame sums to `0xFF` modulo 256.

### 4.2 Payload & KLV Architecture
The payload ($N$ bytes starting at frame byte 6) contains an inner command header followed by Key-Length-Value (KLV) fields:

```text
+---------+-------------+-------------+--------+-----------------------+
| Sub-Cmd | Opcode LSB  | Opcode MSB  | Status | KLV Data Elements ... |
+---------+-------------+-------------+--------+-----------------------+
    0            1             2          3           4..(N-1)
```

- **Byte 0 (`Sub-Cmd`)**: Sub-command category (`0x04` = normal command, `0x05` = ack/query, `0x14` = status/telemetry).
- **Bytes 1–2 (`Opcode`)**: 16-bit little-endian command identifier (e.g. `0x5018`, `0x5593`, `0x55A6`).
- **Byte 3 (`Status`)**: Result code (`0x00` = Success, non-zero = Error / Busy).
- **Bytes 4+ (`KLV Elements`)**: Packed TLV entries (`Key ID [u8]`, `Length [u16 LE]`, `Value [Length bytes]`).

### 4.3 Master-to-Coprocessor Commands

| Opcode | Command Name | Sub-Cmd | Key-Length-Value Structure & Behavior |
|---|---|:---:|---|
| **`0x5018`** | `MANUAL_FEED` | `0x04` | **Key 1** (`u8`): Feed Mode (`1` = immediate portion, `2` = gram-calibrated)<br>**Key 2** (`u16`): Portions / Weight ($1\text{–}20$ portions)<br>**Key 3** (`u16`): Timeout / Target limit ($0\text{–}60$ s)<br>**Key 4** (`u8`): Audio Call Prompt flag (`0` = silent, `1` = play voice) |
| **`0x5104`** | `CHILD_LOCK` | `0x04` | **Key 1** (`u8`): Lock state (`0x00` = buttons unlocked, `0x01` = physical buttons locked) |
| **`0x5105`** | `SLEEP_MODE` | `0x04` | **Key 1** (`u8`): Sleep enable (`0x00` = normal, `0x01` = LEDs/sounds disabled)<br>**Key 2** (`u8`): Extra flag |
| **`0x5107`** | `SLOW_FEED` | `0x05` | **Key 1** (`u8`): Slow feed switch (`0x00` = fast/normal, `0x01` = staged interval feed) |
| **`0x5140`** | `WIFI_LED_MODE` | `0x14` | **Key 1** (`u8`): LED Mode (`0` = Off, `1` = Pairing / Slow Blink, `2` = Solid Connected) |
| **`0x5141`** | `BUZZER_SOUND` | `0x04` | **Key 1** (`u8`): Buzzer state (`0x00` = muted, `0x01` = enabled) |
| **`0x5590`** | `POLL_STATUS` | `0x05` | Empty payload / triggers full telemetry report (`0x5593`) |
| **`0x5592`** | `INTELLIGENT_FEED`| `0x04` | **Key 1** (`u8`): Leftover deduction switch (`0x00` = off, `0x01` = on) |
| **`0x55A1`** | `CLOCK_SYNC` | `0x14` | **Key 1** (`u32`): Current UTC/local Unix epoch timestamp in seconds |
| **`0x55A2`** | `SCALE_ZERO_MEASURE`| `0x14` | Trigger calibration zero measurement |
| **`0x55A3`** | `TARE_SCALE` | `0x05` | Empty payload (0 bytes). Instructs coprocessor to zero the bowl scale load cell |
| **`0x55A6`** | `PLAN_SYNC` | `0x14` | Packed binary feeding plan records (meal index, hour, minute, portions, repeat day bitmask) for autonomous offline battery dispensing |

### 4.4 Coprocessor-to-Master Telemetry & Acknowledgments

| Opcode | Telemetry Name | Sub-Cmd | Meaning & Key-Length-Value Structure |
|---|---|:---:|---|
| **`0x5593`** | `STATUS_REPORT` | `0x14` | **Key 1** (`u16`): Firmware version<br>**Key 2** (`u16`): MCU version<br>**Key 3** (`u8`): `child_lock` state (`0`/`1`)<br>**Key 4** (`u8`): `food_remind` (Hopper food low = `1`, OK = `0`)<br>**Key 5** (`u8`): `battery_percent` ($0\text{–}100\%$) |
| | | | **Key 6** (`u8`): `work_mode`<br>**Key 7** (`u8`): `powerAdapter` (`0` = Battery, `1` = DC Adapter connected)<br>**Key 8** (`u16`): `bowlWeight` (Signed bowl weight in grams, e.g. `0` to `500` g) |
| **`0x5594`** | `DISPENSE_PROGRESS`| `0x14` | **Key 1** (`u16`): Current motor run counter / pulses<br>**Key 2** (`u16`): Portions completed so far |
| **`0x5595`** | `CLOCK_REPORT` | `0x14` | **Key 1** (`u32`): `local_clk_sec` (Current MCU internal RTC epoch seconds) |
| **`0x5596`** | `DISPENSE_RESULT` | `0x14` | **Key 1** (`u8`): `output_type` (`1` = manual, `2` = schedule)<br>**Key 2** (`u8`): `output_cnt` (Portions actually dispensed)<br>**Key 3** (`u8`): `output_code` (`0x00` = OK, `0x01` = Jammed / Overcurrent, `0x02` = Outlet Blocked) |
| **`0x5597`** | `BUTTON_EVENT` | `0x14` | **Key 1** (`u8`): Trigger event (`0x01` = 5s Long-Press / Pair, `0x02` = 10s Factory Reset) |
| **`0x5598`** | `SCHEDULE_TRIGGER`| `0x14` | **Key 1** (`u32`): `local_clk_sec`<br>**Key 2** (`u8`): `output_type`. **Fired when coprocessor triggers an autonomous meal. Signals ESP32 to sound the NS4168 meal chime!** |
| **`0x5599`** | `MEAL_CALIBRATION` | `0x14` | **Key 1** (`u8`): `measult_result`<br>**Key 2** (`u16`): `meal_gram`<br>**Key 3** (`u8`): `serving_cnt` |
| **`0x55A0`** | `SCALE_CAL_POINTS` | `0x14` | **Key 1** (`u32`): `point0GramAD`<br>**Key 2** (`u32`): `point500GramAD`<br>**Key 3** (`u32`): `point1000GramAD` |
| **`0x55A3`** | `TARE_RESPONSE` | `0x05` | **Key 1** (`u8`): `s_zero_result` (`0x00` = Tare OK, `0x01` = Weight Fluctuating, `0x02` = Bowl Disconnected / Off Scale) |
| **`0x55A4`** | `MOTOR_DIAGNOSTICS`| `0x14` | **Key 1** (`u16`): `motor_current` (mA)<br>**Key 2** (`u8`): `motor_status`<br>**Key 3** (`u8`): `lack_food_cnt` |
| **`0x55A5`** | `RAW_ADC_TELEMETRY`| `0x14` | **Key 1** (`u32`): `currentAD`<br>**Key 2** (`u16`): `currentADConverGram*10`<br>**Key 3** (`u16`): `adVariance`<br>**Key 4** (`u16`): `compareAd` |
