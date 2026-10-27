# 05 Opcode & Command Dictionary: Pawsync PPF-R361S

This dictionary covers all 16-bit little-endian opcodes extracted from the `PPF-R361S` firmware image.

| Opcode | Direction | Description | Sub-Cmd | Key-Length-Value (KLV) Structure |
| :--- | :--- | :--- | :--- | :--- |
| **`0x5018`** | ESP $\to$ MCU | **Manual / Scheduled Feed Request** | `0x04` | **Key 1** (`u8`): Feed Mode (`1` = immediate portion, `2` = gram-calibrated)<br>**Key 2** (`u16`): Portions / Weight ($1\text{–}20$ portions)<br>**Key 3** (`u16`): Timeout / Target limit ($0\text{–}60$ s)<br>**Key 4** (`u8`): Audio Call Prompt flag (`0` = silent, `1` = play voice) |
| **`0x5104`** | ESP $\to$ MCU | **Child Lock Toggle** | `0x04` | **Key 1** (`u8`): Lock state (`0x00` = buttons unlocked, `0x01` = physical buttons locked) |
| **`0x5105`** | ESP $\to$ MCU | **Night / Sleep Mode** | `0x04` | **Key 1** (`u8`): Sleep enable (`0x00` = normal, `0x01` = LEDs/sounds disabled)<br>**Key 2** (`u8`): Extra flag |
| **`0x5107`** | ESP $\to$ MCU | **Slow Feed Mode** | `0x05` | **Key 1** (`u8`): Slow feed switch (`0x00` = fast/normal, `0x01` = staged interval feed) |
| **`0x5140`** | ESP $\to$ MCU | **Wi-Fi LED & Indicator Mode** | `0x14` | **Key 1** (`u8`): LED Mode (`0` = Off, `1` = Pairing / Slow Blink, `2` = Solid Connected) |
| **`0x5141`** | ESP $\to$ MCU | **Buzzer Mute / Sound Switch** | `0x04` | **Key 1** (`u8`): Buzzer state (`0x00` = muted, `0x01` = enabled) |
| **`0x5590`** | ESP $\to$ MCU | **Status Poll Request** | `0x05` | Empty payload / poll trigger |
| **`0x5592`** | ESP $\to$ MCU | **Intelligent Feeding Mode** | `0x04` | **Key 1** (`u8`): Intelligent mode switch (`0x00` = off, `0x01` = on) |
| **`0x5593`** | MCU $\to$ ESP | **Full Telemetry Status Report** | `0x14` | **Key 1** (`u16`): Firmware version string / code<br>**Key 2** (`u16`): MCU version string / code<br>**Key 3** (`u8`): `child_lock` state (`0`/`1`)<br>**Key 4** (`u8`): `food_remind` (Hopper food low = `1`, OK = `0`)<br>**Key 5** (`u8`): `battery_percent` ($0\text{–}100\%$) |
| | | *(continued)* | | **Key 6** (`u8`): `work_mode`<br>**Key 7** (`u8`): `powerAdapter` (`0` = Battery, `1` = DC Adapter connected)<br>**Key 8** (`u16`): `bowlWeight` (Signed bowl weight in grams, e.g. `0` to `500` g) |
| **`0x5594`** | MCU $\to$ ESP | **Dispense In-Progress Telemetry** | `0x14` | **Key 1** (`u16`): Current motor run counter / pulses<br>**Key 2** (`u16`): Portions completed so far |
| **`0x5595`** | MCU $\to$ ESP | **Sleep Mode & Local Clock Sync** | `0x14` | **Key 1** (`u32`): `local_clk_sec` (Current MCU internal RTC epoch seconds) |
| **`0x5596`** | MCU $\to$ ESP | **Dispense Result Telemetry** | `0x14` | **Key 1** (`u8`): `output_type` (`1` = manual, `2` = schedule)<br>**Key 2** (`u8`): `output_cnt` (Portions actually dispensed)<br>**Key 3** (`u8`): `output_code` (`0x00` = OK, `0x01` = Jammed / Overcurrent, `0x02` = Outlet Blocked) |
| **`0x5597`** | MCU $\to$ ESP | **Physical Button Event (Pairing / Reset)** | `0x14` | **Key 1** (`u8`): Trigger event (`0x01` = 5s Long-Press / Pair, `0x02` = 10s Factory Reset) |
| **`0x5598`** | MCU $\to$ ESP | **Autonomous Meal Schedule Trigger** | `0x14` | **Key 1** (`u32`): `local_clk_sec`<br>**Key 2** (`u8`): `output_type` (Signals ESP32 to play meal audio chime!) |
| **`0x5599`** | Dual | **Single Meal Calibration** | `0x14` | **Key 1** (`u8`): `measult_result`<br>**Key 2** (`u16`): `meal_gram`<br>**Key 3** (`u8`): `serving_cnt` |
| **`0x55A0`** | Dual | **Scale Calibration Points** | `0x14` | **Key 1** (`u32`): `point0GramAD`<br>**Key 2** (`u32`): `point500GramAD`<br>**Key 3** (`u32`): `point1000GramAD` |
| **`0x55A1`** | ESP $\to$ MCU | **Clock Sync (Epoch Seconds)** | `0x14` | **Key 1** (`u32`): Current UTC/local Unix epoch timestamp |
| **`0x55A2`** | ESP $\to$ MCU | **Scale Zero Measurement Request** | `0x14` | Calibration measurement trigger |
| **`0x55A3`** | Dual | **Bowl Tare / Zero Command & ACK** | `0x05` | ESP $\to$ MCU: Empty payload (0 bytes)<br>MCU $\to$ ESP: **Key 1** (`u8`): `s_zero_result` (`0x00` = Tare OK, `0x01` = Weight Fluctuating, `0x02` = Bowl Disconnected / Off Scale) |
| **`0x55A4`** | MCU $\to$ ESP | **Motor Diagnostics & Current** | `0x14` | **Key 1** (`u16`): `motor_current` (mA)<br>**Key 2** (`u8`): `motor_status`<br>**Key 3** (`u8`): `lack_food_cnt` |
| **`0x55A5`** | MCU $\to$ ESP | **Raw Load-Cell ADC Telemetry** | `0x14` | **Key 1** (`u32`): `currentAD` (Raw ADC counts)<br>**Key 2** (`u16`): `currentADConverGram*10`<br>**Key 3** (`u16`): `adVariance`<br>**Key 4** (`u16`): `compareAd` |
| **`0x55A6`** | ESP $\to$ MCU | **Feeding Plan Push / Schedule Sync** | `0x14` | Packed binary schedule records for autonomous offline battery dispensing |
