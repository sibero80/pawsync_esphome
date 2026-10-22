# Pawsync PPF-R361S: Hardware Architecture, Wiring & Stock Firmware Feature Catalog

> **Target Device:** Pawsync Smart Pet Feeder (Model `PPF-R361S` / `PPF-R361S-WUS`)  
> **VeSync Model Identifier:** `VS_WB_PFM_PPF-R361S-WUS_US` (BLE Model ID: `92`)  
> **Stock Firmware Version Extracted:** `v1.2.5` (Built Mar 5, 2025 09:35:10 CST)  
> **Source Evidence:** Extracted flash dump (`esp32c3_dump.bin`, SHA-256: `8d1970e78007f18975c255c625c37bccf2a5cfa7d76eff04f3af731fea3bb77a`) and companion Android APK (`com.pawsync.pet` v1.1.32).

---

## 1. System Overview & Dual-MCU Architecture

The Pawsync PPF-R361S pet feeder utilizes a master-coprocessor architecture. The high-level networking, cloud connectivity, timekeeping, and audio decoding are handled by an Espressif ESP32-C3 SoC, while all real-time motor control, ADC sampling, optical sensing, and safety interlocks are delegated to a dedicated Sinowealth 8051-based coprocessor.

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
  - Maintains 7 on-device feeding plan profiles in non-volatile storage (NVS).
  - Streams 32 kHz 16-bit mono audio over I2S to the onboard Class-D audio amplifier.
  - Translates user commands into binary KLV frames transmitted over UART to the coprocessor.

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
  - Monitors the physical front-panel manual feed button and controls device power gating.

### 1.3 Audio Amplifier & Transducer Subsystem
- **Amplifier IC:** NS4168 (or pin-compatible equivalent).
  - Class-D mono audio power amplifier delivering up to 3.2 W into a 4 Ω load.
  - Digital input via standard I2S (Inter-IC Sound) bus.
  - Hardware shutdown pin controlled by ESP32-C3 GPIO0 (`AMP_EN`).
- **Speaker:** 4 Ω, 2 W, 36 mm dynamic speaker housed in an acoustic resonance chamber inside the lower chassis.
- **Stock Audio Asset:** Meal call announcement stored at partition `0x110000` (length: 122,924 bytes), formatted as 32 kHz, 16-bit mono PCM.

---

## 2. Pinout, Wiring & Electrical Interconnects

### 2.1 ESP32-C3 Pin Allocation Matrix

| Pin | Function / Net | Signal Direction | Hardware Interface | Description |
|---|---|---|---|---|
| **GPIO0** | `AMP_EN` | ESP32 Output | Digital GPIO | Audio Amplifier Enable (Active **HIGH**; external pull-down keeps amp muted during boot). |
| **GPIO1** | `I2S_WS` | ESP32 Output | I2S Word Select | I2S LRCLK (Left/Right Clock / Frame Sync) at 32 kHz. |
| **GPIO4** | `I2S_BCK` | ESP32 Output | I2S Bit Clock | I2S BCLK (Continuous bit clock for 16-bit samples). |
| **GPIO5** | `I2S_DATA` | ESP32 Output | I2S Serial Data | I2S DOUT (Mono PCM audio data stream to NS4168). |
| **GPIO8** | `LED_STATUS` | ESP32 Output | Digital GPIO | Front-panel status / Wi-Fi indicator LED (Active **LOW**). |
| **GPIO9** | `BOOT_BTN` | ESP32 Input | Digital Input | Boot strap / physical setup push button (Internal pull-up; pulled LOW during boot enters ROM bootloader). |
| **GPIO18** | `UART_RX` | ESP32 Input | Hardware UART0 | UART RX receiving telemetry and ACKs from SC95F8766P coprocessor. |
| **GPIO19** | `UART_TX` | ESP32 Output | Hardware UART0 | UART TX transmitting commands to SC95F8766P coprocessor. |

> [!IMPORTANT]
> **UART Pin Collision Notice:** In ESP32-C3 silicon, GPIO18 and GPIO19 are multiplexed with the internal USB-Serial-JTAG controller. The stock firmware disables USB-Serial-JTAG and maps UART0 to GPIO18/19. In ESPHome, the UART component correctly reconfigures the GPIO matrix to release USB-JTAG pins to UART0.

### 2.2 SC95F8766P Coprocessor Peripheral Wiring

The SC95F8766P interfaces directly with high-voltage, analog, and mechanical components:

```
                      +--------------------------+
                      |    SC95F8766P (8051)     |
                      |                          |
   Load Cell E+/E- ---| 24-bit Sigma-Delta ADC   |
   Load Cell S+/S- ---| Differential Input Ch 0  |
                      |                          |
   Motor Forward   ---| Hardware PWM Output 1    |---> H-Bridge ---> DC Motor
   Motor Reverse   ---| Hardware PWM Output 2    |
   Motor Current   ---| 12-bit ADC Ch 1 (Shunt)  |
   Motor Index     ---| External Interrupt INT0  |<--- Hall Sensor / Cam Switch
                      |                          |
   Lid Switch      ---| Digital GPIO (Pull-Up)   |<--- Magnetic Reed / Microswitch
   Chute IR Emitter---| Digital GPIO (Pulsed)    |---> IR LED
   Chute IR Photodiode| 12-bit ADC / Comparator  |<--- Phototransistor
   Hopper IR Sensor---| Digital GPIO             |<--- Optical Level Sensor
                      |                          |
   Power Supply Det---| 12-bit ADC Ch 2          |<--- DC Jack Sensing Divider
   Battery Voltage ---| 12-bit ADC Ch 3          |<--- D-Cell Divider (3x1.5V)
                      |                          |
   Manual Feed Key ---| Digital GPIO (INT1)      |<--- Front Panel Pushbutton
                      +--------------------------+
```

1. **Load Cell Interface:** Differential strain gauge wired to 24-bit ADC channel. Measures deflection of the food bowl base. Coprocessor performs zero-point baseline tracking, thermal drift compensation, and calibrated gram output.
2. **Motor Driver & Encoder:** Geared brushed DC motor (approx. 30 RPM at 5V). Motor shaft connects to a segmented rotor wheel. A Hall-effect sensor detects each 60° compartment rotation, indexing exactly 1 portion per cycle. Motor current is measured across a low-side shunt resistor to detect physical jams (>850 mA).
3. **Chute & Hopper Sensors:**
   - **Chute Obstacle Sensor:** Infrared beam directed across the dispensing chute aperture. Continuous blockage indicates trapped food or foreign obstruction.
   - **Food Level Sensor:** Side-looking infrared emitter-receiver pair located 3 cm above the hopper base. When kibble drops below the beam, the sensor flags low food.
   - **Lid Sensor:** Microswitch detects when the top hopper lid is opened or removed.
4. **Power System:**
   - **Primary:** 5V DC barrel jack (USB-to-barrel or 5V 2A wall adapter).
   - **Backup:** 3x D-cell alkaline batteries in series (nominal 4.5V DC, dropping to 3.0V at cutoff).
   - An internal Schottky diode OR-ing circuit switches instantly between DC adapter and battery power without MCU reset.

### 2.3 Solderless Programming Test Points

On the bottom of the main PCB (accessible by removing 4 Phillips screws from the base plate), 6 gold test pads provide full access for non-destructive programming:

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

The ESP32-C3 internal 4 MB SPI flash is partitioned according to the standard Espressif two-stage OTA scheme with dedicated audio and parameter storage:

| Partition Name | Subtype | Flash Offset | Partition Size | Contents / Purpose |
|---|---|---|---|---|
| **`nvs`** | `0x00` (NVS) | `0x009000` | 20 KB (`0x005000`) | Non-volatile key-value storage (Wi-Fi credentials, tokens, calibration parameters). |
| **`otadata`** | `0x00` (OTA) | `0x00E000` | 8 KB (`0x002000`) | OTA boot selection register (points active boot to `ota_0` or `ota_1`). |
| **`app_cpu`** | `0x00` (Data) | `0x010000` | 64 KB (`0x010000`) | Reserved / coprocessor staging area. |
| **`ota_0`** | `0x10` (App) | `0x020000` | 960 KB (`0x0F0000`) | Primary application partition slot 0 (stock factory image). |
| **`ota_1`** | `0x11` (App) | `0x120000` | 960 KB (`0x0F0000`) | Secondary application partition slot 1 (**Active slot in stock dump: v1.2.5**). |
| **`audio`** | `0x80` (Custom)| `0x110000` | 128 KB (`0x020000`) | Uncompressed factory meal call prompt audio (`meal_call.wav`, 32 kHz 16-bit mono). |
| **`plan_param`**| `0x82` (Custom)| `0x210000` | 16 KB (`0x004000`) | Stored offline feeding schedules (7 plans × 10 meals). |
| **`misc`** | `0x83` (Custom)| `0x220000` | 16 KB (`0x004000`) | Device state flags, child lock status, sound settings. |
| **`dev_info`** | `0x84` (Custom)| `0x230000` | 16 KB (`0x004000`) | Factory serial number, MAC address, hardware revision string. |
| **`sec_key`** | `0x85` (Custom)| `0x240000` | 16 KB (`0x004000`) | Device-unique cryptographic private keys for VeSync cloud authentication. |
| **`spiffs`** | `0x82` (Data) | `0x250000` | 1,728 KB (`0x1B0000`)| General filesystem for logs, voice clips, and OTA staging. |

---

## 4. Discovered Firmware Features: Complete UART Opcode Dictionary

The communication protocol between the ESP32-C3 and the SC95F8766P coprocessor uses a binary frame structure:

$$\mathbf{[0xA5]} \quad \mathbf{[0x02]} \quad \mathbf{[Length_{LE}]} \quad \mathbf{[Opcode_{MSB}]} \quad \mathbf{[Opcode_{LSB}]} \quad \mathbf{[Payload\dots]} \quad \mathbf{[Checksum]}$$

* **Magic Header:** `0xA5`
* **Protocol Version:** `0x02`
* **Length:** 16-bit Little-Endian representing the count of bytes following the length field through the payload (excluding checksum).
* **Checksum:** $\sim\sum(\text{all bytes from header through end of payload}) \ \& \ 0\text{xFF}$.

### 4.1 Master-to-Coprocessor Commands

| Opcode | Command Name | Payload Structure | Function & Behavior |
|---|---|---|---|
| **`0x5501`** | `DISPENSE_PORTIONS` | `[count: u8]` (1..20) | Commands motor to dispense specified number of portions. Coprocessor pulses motor, indexes rotor pockets, and monitors Hall sensor. |
| **`0x5502`** | `GET_MOTOR_STATUS` | None (`len = 2`) | Queries motor state: `0x00` = Idle, `0x01` = Rotating/Dispensing, `0x02` = Jam Detected, `0x03` = Jam Clearing. |
| **`0x5504`** | `MANUAL_REVERSE` | None (`len = 2`) | Forces motor to execute an anti-jam reverse rotation cycle (reverses 180°, pauses, then advances). |
| **`0x5511`** | `SET_CHILD_LOCK` | `[enable: u8]` (`0x00` = Off, `0x01` = On) | Enables/disables the physical manual feed button on the front of the feeder. Prevents pets or children from self-dispensing. |
| **`0x5521`** | `GET_LID_STATE` | None (`len = 2`) | Queries top hopper lid status (`0x00` = Closed, `0x01` = Open). |
| **`0x5522`** | `GET_FOOD_LEVEL` | None (`len = 2`) | Queries optical hopper level sensor (`0x00` = Sufficient food, `0x01` = Food low/empty). |
| **`0x5523`** | `GET_CHUTE_STATE` | None (`len = 2`) | Queries chute optical beam (`0x00` = Clear, `0x01` = Blocked). |
| **`0x5531`** | `PLAY_AUDIO_PROMPT` | `[track_id: u8]` (`0x00` = Default Meal Call) | Triggers internal audio playback sequence and asserts GPIO0 `AMP_EN`. |
| **`0x5532`** | `SET_VOLUME` | `[volume: u8]` (0..100) | Sets output sound level or mutes speaker chime. |
| **`0x5541`** | `GET_POWER_TELEMETRY`| None (`len = 2`) | Queries power source (`0x00` = Battery, `0x01` = DC Jack) and raw 12-bit battery voltage ADC. |
| **`0x55A1`** | `GET_BOWL_WEIGHT` | None (`len = 2`) | Requests single-shot filtered bowl weight in signed 16-bit grams (`s16 LE`). Negative value indicates tare needed. |
| **`0x55A2`** | `STREAM_WEIGHT` | `[enable: u8]` (`0x00` = Stop, `0x01` = Start) | Starts continuous 5 Hz weight streaming for real-time meal consumption monitoring. |
| **`0x55A3`** | `TARE_SCALE` | None (`len = 2`) | Zeroes the bowl scale strain gauge. Requires empty bowl. Coprocessor recalculates baseline ADC zero offset. |
| **`0x55A4`** | `GET_CALIBRATION_ADCS`| None (`len = 2`) | Returns factory 3-point calibration ADCs: `point0GramAD`, `point500GramAD`, `point1000GramAD` from EEPROM. |
| **`0x55F0`** | `FACTORY_TEST_MODE`| `[mode: u8]` | Puts coprocessor into factory burn-in test mode (cycles motor, tests LEDs, verifies ADC span). |
| **`0x55FF`** | `GET_COPROC_VERSION` | None (`len = 2`) | Queries coprocessor firmware revision string (e.g., `"SC95_v1.0.8"`). |

### 4.2 Coprocessor-to-Master Telemetry & Acknowledgments

| Opcode | Telemetry Name | Payload Structure | Meaning & Error Flags |
|---|---|---|---|
| **`0x5503`** | `DISPENSE_RESULT` | `[status: u8, dispensed: u8, weight_g: s16_LE]` | Fired upon dispense completion. `status = 0x00` (Success), `0x01` (Motor Jammed), `0x02` (Hopper Empty), `0x03` (Chute Blocked). |
| **`0x5512`** | `BUTTON_PRESSED_EVENT`| `[button_id: u8, duration_ms: u16_LE]` | Fired when front-panel button is pressed (Short press = Manual feed 1 portion; Long press >5s = Wi-Fi reset). |
| **`0x55A3`** | `TARE_RESPONSE` | `[result: u8]` | Return code for zeroing request: `0x00` = Success, `0x01` = Weight fluctuating / unstable, `0x02` = Bowl disconnected / absent. |
| **`0x5541`** | `POWER_REPORT` | `[source: u8, raw_adc: u16_LE, pct: u8]` | Periodic or interrupt-driven power status: `source = 0x01` (DC Adapter), `0x00` (D-Cell Batteries). |
| **`0x5524`** | `SENSOR_ALERT_EVENT` | `[sensor_mask: u8, fault_state: u8]` | Asynchronous interrupt: Bit 0 = Lid opened, Bit 1 = Chute blocked, Bit 2 = Hopper empty. |
