# 06 Audio Subsystem Specification: Pawsync PPF-R361S

## 1. Hardware Architecture
- **Audio Amplifier**: Nsiway `NS4168` Class-D mono amplifier (`IC3`).
- **Input Protocol**: Direct I2S digital audio (no external DAC or analog conversion needed).
- **Control Interface**:
  - `GPIO 0`: `CTRL` / `PA_ENABLE` (Output: `HIGH` = Enable, `LOW` = Standby / Mute).
  - `GPIO 1`: `LRCLK` / `WS` (Word Select / Left-Right Clock).
  - `GPIO 4`: `BCLK` (Bit Clock).
  - `GPIO 5`: `SDATA` / `DOUT` (Serial Audio Data Out).

---

## 2. Audio Format & Codec Parameters
Statically decompiled from `0x42007200` (`vhal_i2s_init`) and `work/parts/custom_data.bin`:
- **Sample Rate**: **`32,000 Hz`** (32 kHz).
- **Bit Depth**: **`16-bit` Linear PCM**.
- **Channels**: **`1` (Mono)**.
- **Byte Order**: Little-Endian (`int16_le`).
- **Bitrate**: $32,000 \times 16 = 512\text{ kbps}$ ($64\text{ kB/s}$).

---

## 3. Stock Recorded Meal Prompt
- Carved from flash partition `custom_data` (`0x2FF000`) into [`work/parts/meal_call.wav`](file:///root/pawsync_oma/work/parts/meal_call.wav).
- Header: Standard RIFF WAVE format, 256,228 bytes total (~4.00 seconds).
- Trigger: Played automatically when a feeding event occurs or when requested via cloud/HA service (`playPetVoice`).

---

## 4. ESPHome Integration
The `i2s_audio` component in ESPHome is configured as:
```yaml
i2s_audio:
  - id: i2s_bus
    i2s_lrclk_pin: GPIO1
    i2s_bclk_pin: GPIO4

speaker:
  - platform: i2s_audio
    id: feeder_speaker
    i2s_audio_id: i2s_bus
    dac_type: external
    i2s_dout_pin: GPIO5
    mode: mono

output:
  - platform: gpio
    pin: GPIO0
    id: ns4168_enable
```
Before playback starts, `GPIO0` is set `HIGH`; upon playback completion, `GPIO0` is set `LOW` to prevent amplifier idle hiss.
