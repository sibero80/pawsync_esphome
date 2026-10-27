# 03 GPIO & Peripheral Pin Map: Pawsync PPF-R361S

## 1. ESP32-C3-SOLO-1 Pin Allocation
Every pin on the ESP32-C3 module is statically verified through disassembly of `vhal_i2s_init`, `vhal_gpio_init`, and `ves_uart_init`:

| ESP32-C3 GPIO | Function / Signal | Direction | Connected Peripheral | Verification Source / Hardware Trace |
| :--- | :--- | :--- | :--- | :--- |
| **`GPIO 0`** | `NS4168_CTRL` | Output | `NS4168` Pin 1 (PA Enable / Channel Select) | `gpio_config` caller at `0x42007210` (mask `0x01`, output) |
| **`GPIO 1`** | `I2S_WS / LRCLK` | Output | `NS4168` Pin 2 (Word Select / Frame Clock) | `i2s_set_pin` config at `0x420072A8` (`ws_io_num = 1`) |
| **`GPIO 4`** | `I2S_BCK` | Output | `NS4168` Pin 3 (Continuous Serial Clock) | `i2s_set_pin` config at `0x42007290` (`bck_io_num = 4`) |
| **`GPIO 5`** | `I2S_DATA_OUT` | Output | `NS4168` Pin 4 (Serial Data Input) | `i2s_set_pin` config at `0x42007296` (`data_out_num = 5`) |
| **`GPIO 18`** | `UART_RX` | Input | `SC95F8766P` UART TXD | `ves_uart` init at `0x4201AA38` (`rx_pin = 18`, 115200 baud) |
| **`GPIO 19`** | `UART_TX` | Output | `SC95F8766P` UART RXD | `ves_uart` init at `0x4201AA3C` (`tx_pin = 19`, 115200 baud) |
| **`GPIO 20`** | `UART0_RXD` | Input | Test pad / Console Debug Header (`RXD0`) | Standard ESP32-C3 console UART |
| **`GPIO 21`** | `UART0_TXD` | Output | Test pad / Console Debug Header (`TXD0`) | Standard ESP32-C3 console UART |
| **`GPIO 9`** | `BOOT / STRAP` | Input | Pull-down test pad for flashing mode | Strapping pin (`LOW` on boot enters ROM download mode) |
| **`GPIO 2`** | `NC / STRAP` | - | Floating / Not routed | ESP32-C3 boot strap |
| **`GPIO 8`** | `NC / STRAP` | - | Floating / Internally pulled up | ESP32-C3 boot strap |

---

## 2. SC95F8766P Coprocessor Peripheral Wiring
The following hardware peripherals are **NOT connected to the ESP32-C3**; they are controlled solely by the `SC95F8766P` coprocessor and accessed by ESPHome through the UART protocol:

| Peripheral | Component | Physical Connection | Controlled Via |
| :--- | :--- | :--- | :--- |
| **Dispense Motor** | `JS50T-5V-8R` | Mainboard 4-pin motor connector | UART Opcode `0x5018` |
| **Food Scale Bridge** | Detachable load cell | 4-wire dock (Red, Black, Green, White) directly to SC95F ADC | UART Opcodes `0x5593` (read), `0x55A3` (tare) |
| **Food Chute IR Sensors**| `TX1DM/RX1DM`, `TX2DM/RX2DM` | UI daughterboard ribbon cable to SC95F GPIOs | UART Opcode `0x5593` (Key 4) |
| **Tactile Buttons** | `K2` (Feed), `K4` (Lock/Reset) | UI daughterboard ribbon cable to SC95F GPIOs | Handled autonomously by MCU |
| **Status LEDs** | `LED1`, `LED3` (Wi-Fi, Status) | UI daughterboard ribbon cable to SC95F GPIOs | UART Opcode `0x5140` / `0x5105` |
| **Audible Buzzer** | `BUZZ1` | Mainboard footprint to SC95F PWM | UART Opcode `0x5141` |
