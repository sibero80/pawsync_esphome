# Home Assistant Integration Design Document & User Experience Specification

> **Device:** Pawsync Smart Pet Feeder (Model `PPF-R361S` / `PPF-R361S-WUS`)  
> **ESPHome Firmware Target:** [`pawsync.yaml`](file:///root/pawsync_oma2/pawsync.yaml)  
> **Integration Architecture:** ESPHome Native API (Port 6053, TCP Protobuf + Noise Encryption)  
> **Target Platform:** Home Assistant Core 2024.1+ / 2026.x

---

## 1. Transport & Architecture Overview

The Pawsync PPF-R361S communicates with Home Assistant exclusively via the **ESPHome Native API**:

```
+------------------------------------+              +------------------------------------+
|            Home Assistant          |              |       Pawsync Pet Feeder           |
|                                    |  TCP (6053)  |                                    |
|   +----------------------------+   |  Protobuf    |   +----------------------------+   |
|   |  ESPHome Integration Core  | <==============> |   |  ESPHome Native API Server |   |
|   +-------------+--------------+   |  Noise PSK   |   +-------------+--------------+   |
|                 |                  |              |                 |                  |
|   +-------------v--------------+   |              |   +-------------v--------------+   |
|   | Dashboard / Automations /  |   |              |   |  PPF-R361S Component Core  |   |
|   | Blueprints / Long-Term Stat|   |              |   +----------------------------+   |
|   +----------------------------+   |              +------------------------------------+
+------------------------------------+
```

### Why Native API Over MQTT?
1. **Zero Configuration / Zero Broker:** No external MQTT broker is required. Home Assistant discovers the feeder instantly via mDNS (`pawsync-feeder.local`).
2. **Atomic Entity Binding:** All sensors, numbers, switches, buttons, and media players are automatically created with standard device icons, units, and categories.
3. **Sub-Second Bi-Directional Streaming:** Scale weight readings update with sub-second latency, enabling live feeding animations in the Home Assistant UI.
4. **Native Media Streaming:** Home Assistant's `media_player` platform streams Text-to-Speech (TTS) announcements and audio files directly to the feeder speaker over the Native API without external URL hosting.
5. **Encryption & Security:** Noise Protocol Framework provides authenticated symmetric session encryption between Home Assistant and the ESP32-C3.

---

## 2. Complete Entity Inventory & Domain Mapping

All entities below are defined and generated directly from [`pawsync.yaml`](file:///root/pawsync_oma2/pawsync.yaml):

### 2.1 Sensors (`sensor.*`)

| Entity ID | Friendly Name | Unit | Device Class | State Class | Description |
|---|---|:---:|:---:|:---:|---|
| `sensor.pawsync_feeder_bowl_weight` | Bowl Weight | `g` | `weight` | `measurement` | Real-time strain-gauge load cell measurement (0g to 500g). Reported by coprocessor via `0x5593` Key 8. |
| `sensor.pawsync_feeder_battery_level` | Battery Level | `%` | `battery` | `measurement` | Estimated remaining 3× D-cell battery percentage. Reported via `0x5593` Key 5. |
| `sensor.pawsync_feeder_last_feed_weight` | Last Feed Weight | `g` | `weight` | `measurement` | Dispensed food weight in the most recent feeding cycle. |
| `sensor.pawsync_feeder_portions_today` | Portions Today | `portions` | — | `total_increasing` | Daily counter tracking dispensed food portions, resetting at midnight. |

### 2.2 Binary Sensors (`binary_sensor.*`)

| Entity ID | Friendly Name | Device Class | Meaning when `ON` (True) | Meaning when `OFF` (False) |
|---|---|:---:|---|---|
| `binary_sensor.pawsync_feeder_ac_power_connected` | AC Power Connected | `plug` | Powered via 5V DC wall adapter. | Running on backup D-cell batteries (Power blackout). |
| `binary_sensor.pawsync_feeder_food_level_low` | Food Level Low | `problem` | Kibble in hopper has dropped below the optical infrared sensor. | Sufficient food in hopper. |
| `binary_sensor.pawsync_feeder_motor_jammed` | Motor Jammed | `problem` | Motor overcurrent detected by coprocessor (>850 mA); jam active. | Motor operating normally. |
| `binary_sensor.pawsync_feeder_bowl_scale_connected` | Bowl Scale Connected | `connectivity` | Food bowl base is in electrical contact with scale load cell. | Bowl is removed or disconnected from dock. |

### 2.3 Controls & Configuration (`switch.*`, `number.*`, & `select.*`)

| Entity ID | Type | Range / Options | Default | Description |
|---|---|:---:|:---:|---|
| `switch.pawsync_feeder_child_lock` | Switch | `on` / `off` | `off` | Disables front physical button `K2` via `0x5104` to prevent pet tampering. |
| `switch.pawsync_feeder_slow_feed_mode` | Switch | `on` / `off` | `off` | Enables pulsed portion delivery with intervals via `0x5107`. |
| `switch.pawsync_feeder_sleep_mode` | Switch | `on` / `off` | `off` | Disables front status LEDs and audio chimes via `0x5105`. |
| `switch.pawsync_feeder_intelligent_feeding`| Switch | `on` / `off` | `off` | Enables automatic leftover kibble deduction prior to dispensing (`0x5592`). |
| `number.pawsync_feeder_manual_feed_portions`| Number | 1 to 20 | 1 | Portion selector for manual feed requests. |
| `number.pawsync_feeder_grams_per_portion` | Number | 3.0 to 20.0 g | 8.0 g | Calibrated density of kibble per portion. Backed by flash NVS. |
| `select.pawsync_feeder_active_feeding_plan` | Select | Plan 1 to Plan 7 | Plan 1 (Daily) | Switches active schedule plan profile; syncs plan to coprocessor via `0x55A6`. |

### 2.4 Action Buttons (`button.*`)

| Entity ID | Friendly Name | Icon | Function |
|---|---|:---:|---|
| `button.pawsync_feeder_feed_1_portion` | Feed 1 Portion | `mdi:food-drumstick` | Triggers immediate dispensing of 1 portion via opcode `0x5018`. |
| `button.pawsync_feeder_tare_bowl_scale` | Tare Bowl Scale | `mdi:scale-balance` | Sends opcode `0x55A3` to zero the strain-gauge bowl scale (requires empty bowl). |
| `button.pawsync_feeder_calibrate_kibble_density` | Calibrate Kibble Density | `mdi:scale-unbalanced` | Runs automated 3-portion calibration wizard to compute exact grams per portion. |

### 2.5 Media Player & Diagnostic Text Sensors

| Entity ID | Type | Description |
|---|---|---|
| `media_player.pawsync_feeder_meal_call_speaker` | Media Player | Controls onboard NS4168 Class-D amplifier with GPIO0 power gating. Streams HA TTS or WAV audio. |
| `text_sensor.pawsync_feeder_feeder_status` | Text Sensor | Real-time state: `"Idle / Standby"`, `"Feeding..."`, `"Calibrating: Settling scale..."`, `"Tare Failed"`. |
| `text_sensor.pawsync_feeder_next_scheduled_meal` | Text Sensor | Human-readable countdown and timestamp of the next upcoming meal today. |
| `text_sensor.pawsync_feeder_today_s_schedule_summary`| Text Sensor | Formatted summary of active schedule profile and configured meals. |

---

## 3. Automation Actions & Service Calls

Through ESPHome actions, Home Assistant automations can programmatically control the feeder:

| Action Name | Parameters | Description |
|---|---|---|
| **`ppf_r361s.feed`** | `portions` (1..20), `sound` (bool) | Triggers dispensing of specified portion count with optional audio prompt. |
| **`ppf_r361s.tare`** | None | Zeroes the load cell scale. |
| **`ppf_r361s.sync_clock`** | `epoch` (uint32) | Syncs local Unix timestamp down to the coprocessor RTC via `0x55A1`. |
| **`ppf_r361s.sync_schedules`** | None | Pushes active plan schedule table to coprocessor EEPROM via `0x55A6`. |
| **`ppf_r361s.set_schedule_meal`**| `plan` (1..7), `meal` (1..10), `enabled` (bool), `hour` (0..23), `minute` (0..59), `portions` (1..20), `days` (bitmask 1..127), `sound` (bool) | Programs an individual meal slot in NVS and syncs to coprocessor. |
| **`ppf_r361s.set_active_plan`** | `plan` (1..7) | Switches the active feeding plan profile. |

---

## 4. Production Lovelace Dashboard & Automation Blueprints

### 4.1 Production Mushroom Dashboard Card

```yaml
type: vertical-stack
cards:
  - type: custom:mushroom-title-card
    title: Pawsync Pet Feeder
    subtitle: Local ESPHome Control (PPF-R361S)

  # Live Bowl Weight & Status
  - type: horizontal-stack
    cards:
      - type: custom:mushroom-template-card
        primary: "{{ states('sensor.pawsync_feeder_bowl_weight') }} g"
        secondary: "Current Bowl Weight"
        icon: mdi:scale
        icon_color: green
        tap_action:
          action: more-info
          entity: sensor.pawsync_feeder_bowl_weight

      - type: custom:mushroom-template-card
        primary: "{{ states('text_sensor.pawsync_feeder_feeder_status') }}"
        secondary: "Feeder State"
        icon: >
          {% if is_state('binary_sensor.pawsync_feeder_food_level_low', 'on') or is_state('binary_sensor.pawsync_feeder_motor_jammed', 'on') %}
            mdi:alert-circle
          {% else %}
            mdi:check-circle
          {% endif %}
        icon_color: >
          {% if is_state('binary_sensor.pawsync_feeder_food_level_low', 'on') or is_state('binary_sensor.pawsync_feeder_motor_jammed', 'on') %}
            red
          {% else %}
            blue
          {% endif %}

  # Manual Feed Controls
  - type: horizontal-stack
    cards:
      - type: custom:mushroom-number-card
        entity: number.pawsync_feeder_manual_feed_portions
        layout: horizontal
        name: Portions
      - type: custom:mushroom-entity-card
        entity: button.pawsync_feeder_feed_1_portion
        name: Feed Now
        icon: mdi:food-drumstick
        icon_color: deep-orange
        tap_action:
          action: toggle

  # Active Feeding Plan Selector
  - type: custom:mushroom-select-card
    entity: select.pawsync_feeder_active_feeding_plan
    name: Active Plan Profile
    icon: mdi:calendar-clock

  # Diagnostic Chips
  - type: custom:mushroom-chips-card
    chips:
      - type: entity
        entity: binary_sensor.pawsync_feeder_ac_power_connected
        icon: mdi:power-plug
      - type: entity
        entity: sensor.pawsync_feeder_battery_level
        icon: mdi:battery
      - type: entity
        entity: binary_sensor.pawsync_feeder_food_level_low
        icon: mdi:tray-alert
      - type: entity
        entity: binary_sensor.pawsync_feeder_bowl_scale_connected
        icon: mdi:tray

  # Maintenance & Controls
  - type: entities
    title: Configuration & Calibration
    show_header_toggle: false
    entities:
      - entity: number.pawsync_feeder_grams_per_portion
        name: Kibble Density (g/portion)
      - entity: button.pawsync_feeder_calibrate_kibble_density
        name: Calibrate Density (3-Portion Wizard)
      - entity: button.pawsync_feeder_tare_bowl_scale
        name: Tare Scale (Zero Bowl)
      - entity: switch.pawsync_feeder_child_lock
        name: Child Lock (Disable Buttons)
      - entity: switch.pawsync_feeder_intelligent_feeding
        name: Intelligent Feeding (Deduct Leftovers)
      - entity: switch.pawsync_feeder_slow_feed_mode
        name: Slow Feed Mode
```

### 4.2 Pet Eating Behavior Logger Automation

```yaml
alias: "Pawsync: Log Pet Meal Consumption"
description: "Detects when the pet finishes eating and logs grams consumed"
trigger:
  - platform: numeric_state
    entity_id: sensor.pawsync_feeder_bowl_weight
    below: 500
    for:
      minutes: 1
condition:
  - condition: template
    value_template: >
      {{ states('sensor.pawsync_feeder_bowl_weight') | float(0) < 
         states('input_number.last_settled_bowl_weight') | float(0) - 5 }}
action:
  - variables:
      weight_before: "{{ states('input_number.last_settled_bowl_weight') | float(0) }}"
      weight_after: "{{ states('sensor.pawsync_feeder_bowl_weight') | float(0) }}"
      grams_eaten: "{{ (weight_before - weight_after) | round(1) }}"
  - service: logbook.log
    data:
      name: "Pawsync Pet Feeder"
      message: "Pet finished eating! Consumed {{ grams_eaten }}g of food."
      entity_id: sensor.pawsync_feeder_bowl_weight
  - service: notify.notify
    data:
      title: "🐾 Pet Finished Eating"
      message: "Your pet just ate {{ grams_eaten }}g of kibble. {{ weight_after }}g remaining in bowl."
  - service: input_number.set_value
    target:
      entity_id: input_number.last_settled_bowl_weight
    data:
      value: "{{ states('sensor.pawsync_feeder_bowl_weight') | float(0) }}"
mode: single
```

### 4.3 Blackout Alert & Power Failover Automation

```yaml
alias: "Pawsync: Blackout Battery Protection"
description: "Notifies owner when feeder transitions to backup batteries"
trigger:
  - platform: state
    entity_id: binary_sensor.pawsync_feeder_ac_power_connected
    to: "off"
action:
  - service: notify.notify
    data:
      title: "🔌 Feeder Running on Battery"
      message: "AC power lost! Pawsync Feeder has switched to backup D-cell batteries ({{ states('sensor.pawsync_feeder_battery_level') }}%). Scheduled feeding plans continue operating autonomously."
```
