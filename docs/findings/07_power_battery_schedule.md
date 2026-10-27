# 07 Power, Battery & Hardware Lifecycle Forensics: Pawsync PPF-R361S

## 1. Power Supply Architecture
The feeder features a dual power path:
1. **Primary DC Power**: 5V DC via external adapter.
2. **Backup Battery Power**: Internal 3× D-cell (or 4× AA/D battery tray).
   - Monitored by the `SC95F8766P` hardware ADC.
   - Reported over UART via `0x5593` telemetry:
     - `Key 5` (1 byte): Battery percentage ($0\text{–}100\%$).
     - `Key 7` (1 byte): `powerAdapter` ($0 = \text{Battery Mode}$, $1 = \text{AC Adapter Connected}$).

---

## 2. Power-Fail & Battery Mode Lifecycle
- When AC adapter power is lost (`powerAdapter == 0`):
  - The `SC95F8766P` coprocessor keeps running continuously.
  - The `SC95F8766P` powers down front indicator LEDs and disables Wi-Fi pairing mode to conserve energy.
  - In stock firmware, string at `0x3C0C45F0` states: `"Battery power supply, cannot cfgnet!"`.
  - The ESP32-C3 power rail (`3V3/EN`) remains powered, but stock firmware suspends Wi-Fi transmissions to preserve battery life.
  - In ESPHome, we can configure automatic Wi-Fi power save or deep sleep wakeups when running on battery power.

---

## 3. Scheduled Meal Autonomous Execution
- The owner confirmed (Fact Q4) that when AC is disconnected, scheduled meals run on battery AND physical buttons continue to work.
- Static decompilation of `0x42009EA0` and `0x4200A15A` proves how this works:
  - The ESP32 synchronizes wall-clock time (`0x55A1`, epoch timestamp) and active meal schedules (`0x55A6`) to the coprocessor's non-volatile schedule memory.
  - The `SC95F8766P` coprocessor compares its internal hardware RTC against the schedule table. When a meal triggers:
    1. The coprocessor drives the motor to dispense the requested portions.
    2. If the ESP32 is awake or connected, the coprocessor sends UART telemetry `0x5598` (`Scheduled Meal Event`) to signal the ESP32 to trigger the voice prompt through `NS4168`!
    3. The coprocessor sends `0x5596` (`Dispense Result`) to report actual portions dispensed and error status.
