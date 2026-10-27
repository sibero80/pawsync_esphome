# 02 Firmware Identity & Architecture Report: Pawsync PPF-R361S

## 1. Executive Summary
- **Device Brand**: Pawsync (Arovast / VeSync ecosystem)
- **Model Number**: `PPF-R361S` / `PPF-R361S-WUS_US`
- **VeSync Cloud Identifier**: `VS_WB_PFM_PPF-R361S-WUS_US`
- **Firmware Version (Stock Active)**: `v1.2.5`
- **Build Timestamp**: `Mar 5 2025 15:05:20`
- **ESP-IDF Toolchain Commit**: `264e1242` (ESP-IDF v4.4.x / v5.1 branch)
- **Primary Wireless SoC**: Espressif ESP32-C3 (RISC-V 32-bit `rv32imc` @ 160 MHz)
- **Secondary Coprocessor**: SinOne `SC95F8766P` (High-speed 1T 8051-core MCU)

---

## 2. Dual-MCU System Architecture
The Pawsync PPF-R361S uses a master-coprocessor topology:
1. **ESP32-C3-SOLO-1 (`U10`) - Network & Audio Gateway**:
   - Manages Wi-Fi (802.11 b/g/n) and BLE provisioning.
   - Synchronizes time (NTP / wall-clock RTC) and feeding plans down to the coprocessor.
   - Drives digital audio playback through the `NS4168` Class-D amplifier via I2S.
   - Communicates with the `SC95F8766P` over high-speed hardware UART (`UART0`, 115200 baud).
2. **SinOne SC95F8766P (`IC1`) - Hardware Controller & Offline Feeder Engine**:
   - Drives the 5V geared motor (`JS50T-5V-8R`) with anti-jam current monitoring.
   - Reads the bowl strain-gauge scale bridge directly via internal high-precision ADC.
   - Scans physical tactile buttons (`K2` manual feed, `K4` lock/reset).
   - Controls front panel indicator LEDs (`LED1`, `LED3`).
   - Monitors food chute infrared break-beam sensors (`TX1DM/RX1DM`, `TX2DM/RX2DM`).
   - **Autonomous Battery Operation**: Maintains its own internal hardware RTC timer and schedule table. Scheduled feedings execute reliably on backup battery power even with the ESP32 in deep sleep or Wi-Fi off.

---

## 3. Stock Software Stack & Components
- **OS**: FreeRTOS on RISC-V core.
- **Protocol Driver**: `ves_uart` (VeSync UART driver layer).
- **Audio Driver**: `vhal_i2s` driving NS4168 @ 32,000 Hz 16-bit mono PCM.
- **Local Storage**:
  - `nvs`: Wi-Fi calibration and station configuration.
  - `usercfg`: Stored feeding plans (`sche_cfg_0`, `sche_cfg_1`), timezone (`America/Bogota`), feed state (`feed_param`).
  - `custom_data`: Raw 32 kHz WAV audio asset for custom recorded meal call.
