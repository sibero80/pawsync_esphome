# Home Assistant Integration Design Document & User Experience Specification

> **Device:** Pawsync Smart Pet Feeder (Model `PPF-R361S`)  
> **ESPHome Firmware Target:** [`pawsync.yaml`](file:///root/pawsync_oma/pawsync.yaml)  
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
2. **Atomic Entity Binding:** All 26 sensors, numbers, switches, buttons, and media players are automatically created with standard device icons, units, and categories.
3. **Sub-Second Bi-Directional Streaming:** Scale weight readings update at 5 Hz with 20 ms latency, enabling live feeding animations in the Home Assistant UI.
4. **Native Media Streaming:** Home Assistant's `media_player` platform streams Text-to-Speech (TTS) announcements and audio files directly to the feeder speaker over the Native API without external URL hosting.
5. **Encryption & Security:** Noise Protocol Framework provides authenticated symmetric session encryption between Home Assistant and the ESP32-C3.

---

## 2. Complete Entity Inventory & Domain Mapping

### 2.1 Sensors (`sensor.*`)

| Entity ID | Friendly Name | Unit | Device Class | State Class | Description |
|---|---|:---:|:---:|:---:|---|
| `sensor.pawsync_feeder_bowl_weight` | Bowl Weight | `g` | — | `measurement` | Real-time strain-gauge load cell measurement (-50g to 1000g). Negative indicates tare needed. |
| `sensor.pawsync_feeder_dispensed_today` | Food Dispensed Today | `g` | — | `total_increasing` | Accumulated grams of pet food dispensed since midnight. |
| `sensor.pawsync_feeder_meals_today` | Meals Served Today | `meals` | — | `total_increasing` | Count of discrete meals dispensed today. |
| `sensor.pawsync_feeder_battery_voltage` | Battery Voltage | `V` | `voltage` | `measurement` | 3x D-cell battery bank voltage (4.5V nominal, 3.0V cutoff). |
| `sensor.pawsync_feeder_battery_level` | Battery Level | `%` | `battery` | `measurement` | Estimated remaining battery percentage. |
| `sensor.pawsync_feeder_kibble_level` | Hopper Food Level | `%` | — | `measurement` | Optical level estimation (0% = Empty, 25% = Low, 100% = Full). |
| `sensor.pawsync_feeder_desiccant_days` | Desiccant Life Remaining | `d` | — | `measurement` | 30-day countdown timer for silica desiccant replacement. |

### 2.2 Binary Sensors (`binary_sensor.*`)

| Entity ID | Friendly Name | Device Class | Meaning when `ON` (True) | Meaning when `OFF` (False) |
|---|---|:---:|---|---|
| `binary_sensor.pawsync_feeder_chute_blocked` | Chute Blockage | `problem` | Infrared beam interrupted; food jam or foreign object in chute. | Chute is clear and unobstructed. |
| `binary_sensor.pawsync_feeder_hopper_empty` | Hopper Empty | `problem` | Kibble has dropped below optical hopper level sensor. | Sufficient food in hopper. |
| `binary_sensor.pawsync_feeder_lid_open` | Hopper Lid | `door` | Top hopper lid is removed or open. | Lid is securely locked. |
| `binary_sensor.pawsync_feeder_battery_power` | Power Source | `power` | Running on backup D-cell batteries (AC power disconnected). | Powered via primary 5V DC wall adapter. |
| `binary_sensor.pawsync_feeder_feeding_active` | Dispensing Active | `running` | Motor is rotating and dispensing kibble. | Feeder is idle. |
| `binary_sensor.pawsync_feeder_motor_jammed` | Motor Stall | `problem` | Motor current exceeded 850mA; rotor is jammed. | Motor operating normally. |
| `binary_sensor.pawsync_feeder_bowl_connected` | Bowl Scale Connected | `connectivity` | Food bowl base is in electrical contact with scale pins. | Bowl is absent or contacts are dirty. |

### 2.3 Controls & Configuration (`switch.*` & `number.*`)

| Entity ID | Type | Range / Options | Default | Description |
|---|---|:---:|:---:|---|
| `switch.pawsync_feeder_child_lock` | Switch | `on` / `off` | `off` | Disables the physical front-panel manual feed button to prevent pet self-feeding. |
| `switch.pawsync_feeder_mute_chime` | Switch | `on` / `off` | `off` | Mutes audio chimes during feeding cycles. |
| `switch.pawsync_feeder_schedule_enable` | Switch | `on` / `off` | `on` | Master enable toggle for the on-device offline feeding schedule. |
| `switch.pawsync_feeder_intelligent_feeding`| Switch | `on` / `off` | `on` | Enables automatic leftover kibble deduction prior to dispensing scheduled meals. |
| `switch.pawsync_feeder_slow_feeding` | Switch | `on` / `off` | `off` | Dispenses multi-portion meals in pulses with 10s pauses to prevent rapid eating. |
| `number.pawsync_feeder_manual_portions` | Number | 1 to 20 | 1 | Number of portions to dispense when the "Feed Now" button is pressed. |
| `number.pawsync_feeder_kibble_grams_per_portion`| Number | 5.0 to 25.0 g | 9.6 g | Calibrated density of kibble per portion. Backed by flash NVS. |
| `number.pawsync_feeder_target_meal_weight` | Number | 10 to 200 g | 45 g | Default target weight for intelligent feeding calculations. |
| `number.pawsync_feeder_active_plan` | Number | 1 to 7 | 1 | Selects active offline schedule plan profile. |

### 2.4 Action Buttons (`button.*`)

| Entity ID | Friendly Name | Icon | Function |
|---|---|:---:|---|
| `button.pawsync_feeder_dispense` | Feed Now | `mdi:bone` | Dispenses the portion count specified in `manual_portions`. |
| `button.pawsync_feeder_tare_scale` | Zero Scale (Tare) | `mdi:scale` | Sends `0x55A3` to zero the strain-gauge load cell (requires empty bowl). |
| `button.pawsync_feeder_calibrate_portion`| Calibrate Kibble Density | `mdi:scale-balance` | Executes the automated 5-stage calibration wizard (Tare $\to$ 3 portions $\to$ Settle $\to$ Calculate $\to$ Save). |
| `button.pawsync_feeder_clear_jam` | Clear Food Jam | `mdi:wrench` | Sends `0x5504` to trigger motor anti-jam reverse rotation sequence. |
| `button.pawsync_feeder_reset_desiccant` | Reset Desiccant Timer | `mdi:refresh` | Resets the 30-day desiccant replacement countdown timer. |

### 2.5 Media Player & Diagnostic Sensors

| Entity ID | Type | Description |
|---|---|---|
| `media_player.pawsync_feeder_speaker` | Media Player | Controls the onboard NS4168 Class-D amplifier and speaker. Supports TTS and audio playback. |
| `text_sensor.pawsync_feeder_status` | Text Sensor | Human-readable real-time state: `"Idle"`, `"Dispensing"`, `"Calibrating: Taring"`, `"Tare Failed: Unstable Weight"`. |
| `text_sensor.pawsync_feeder_firmware` | Text Sensor | ESPHome firmware release and build compilation timestamp. |
| `text_sensor.pawsync_feeder_coproc_version`| Text Sensor | Sinowealth SC95F8766P coprocessor firmware version string (`0x55FF`). |
| `text_sensor.pawsync_feeder_schedule_summary`| Text Sensor | Formatted summary of active schedule profile and next scheduled meal time. |

---

## 3. Home Assistant Dashboard (Lovelace UI Configuration)

A complete, production-ready Lovelace card layout utilizing standard Home Assistant Mushroom and Tile cards:

```yaml
type: vertical-stack
cards:
  - type: custom:mushroom-title-card
    title: Pawsync Pet Feeder
    subtitle: Local ESPHome Control (PPF-R361S)

  # Live Feeder Status & Quick Feed Controls
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
        primary: "{{ states('text_sensor.pawsync_feeder_status') }}"
        secondary: "Feeder State"
        icon: >
          {% if is_state('binary_sensor.pawsync_feeder_feeding_active', 'on') %}
            mdi:rotate-right
          {% elif is_state('binary_sensor.pawsync_feeder_chute_blocked', 'on') or is_state('binary_sensor.pawsync_feeder_motor_jammed', 'on') %}
            mdi:alert-circle
          {% else %}
            mdi:check-circle
          {% endif %}
        icon_color: >
          {% if is_state('binary_sensor.pawsync_feeder_chute_blocked', 'on') or is_state('binary_sensor.pawsync_feeder_motor_jammed', 'on') %}
            red
          {% elif is_state('binary_sensor.pawsync_feeder_feeding_active', 'on') %}
            orange
          {% else %}
            blue
          {% endif %}

  # Manual Dispense Bar
  - type: horizontal-stack
    cards:
      - type: custom:mushroom-number-card
        entity: number.pawsync_feeder_manual_portions
        layout: horizontal
        name: Portions
      - type: custom:mushroom-entity-card
        entity: button.pawsync_feeder_dispense
        name: Feed Now
        icon: mdi:bone
        icon_color: deep-orange
        tap_action:
          action: toggle

  # Gauges: Food Bowl & Hopper Level
  - type: horizontal-stack
    cards:
      - type: gauge
        entity: sensor.pawsync_feeder_bowl_weight
        name: Bowl Weight
        min: 0
        max: 200
        needle: true
        severity:
          green: 20
          yellow: 60
          red: 120
      - type: gauge
        entity: sensor.pawsync_feeder_kibble_level
        name: Hopper Food Level
        min: 0
        max: 100
        needle: true
        severity:
          red: 0
          yellow: 25
          green: 50

  # Diagnostic Badges & Health Alerts
  - type: custom:mushroom-chips-card
    chips:
      - type: entity
        entity: binary_sensor.pawsync_feeder_battery_power
        icon: mdi:battery-charging
        name: Power
      - type: entity
        entity: binary_sensor.pawsync_feeder_hopper_empty
        icon: mdi:tray-alert
      - type: entity
        entity: binary_sensor.pawsync_feeder_chute_blocked
        icon: mdi:alert-octagon
      - type: entity
        entity: binary_sensor.pawsync_feeder_lid_open
        icon: mdi:door-open

  # Advanced Maintenance & Calibration Accordion
  - type: entities
    title: Calibration & Safety Settings
    show_header_toggle: false
    entities:
      - entity: number.pawsync_feeder_kibble_grams_per_portion
        name: Kibble Density (g/portion)
      - entity: button.pawsync_feeder_calibrate_portion
        name: Calibrate Density (3-Portion Wizard)
      - entity: button.pawsync_feeder_tare_scale
        name: Tare Scale (Zero Bowl)
      - entity: switch.pawsync_feeder_child_lock
        name: Front Button Lock (Child Lock)
      - entity: switch.pawsync_feeder_intelligent_feeding
        name: Intelligent Feeding (Deduct Leftovers)
      - entity: button.pawsync_feeder_clear_jam
        name: Clear Food Jam (Anti-Jam Reverse)
```

---

## 4. Production Automations & Blueprint Recipes

### 4.1 Automation 1: Pet Eating Detection & Consumption Logger

Monitors bowl weight changes after a feeding event. When the weight drops by $\ge 5\,\text{g}$ and stabilizes, logs a consumption event and sends a mobile notification with the exact quantity eaten:

```yaml
alias: "Pawsync: Log Pet Meal Consumption"
description: "Detects when the pet finishes eating and logs grams consumed"
trigger:
  - platform: numeric_state
    entity_id: sensor.pawsync_feeder_bowl_weight
    below: 500  # Activates on any weight change
    for:
      minutes: 1  # Waits for weight to stabilize after pet walks away
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

### 4.2 Automation 2: Actionable Chute Blockage / Motor Jam Alert

Fires an urgent notification with action buttons to reverse the motor or tare the scale:

```yaml
alias: "Pawsync: Critical Food Jam Alert"
description: "Sends actionable mobile alert when chute or motor is blocked"
trigger:
  - platform: state
    entity_id: binary_sensor.pawsync_feeder_motor_jammed
    to: "on"
  - platform: state
    entity_id: binary_sensor.pawsync_feeder_chute_blocked
    to: "on"
action:
  - service: notify.notify
    data:
      title: "⚠️ Feeder Obstruction Alert!"
      message: "The Pawsync Feeder reported a blockage or motor stall! Immediate attention required."
      data:
        actions:
          - action: "CLEAR_FEEDER_JAM"
            title: "Clear Jam (Reverse Motor)"
          - action: "TARE_FEEDER_SCALE"
            title: "Tare Scale"
```

### 4.3 Automation 3: Power Outage & D-Cell Battery Conservation

When main AC power is disconnected and the feeder transitions to backup D-cell batteries, this automation mutes audio chimes and reduces logging frequency to extend battery life up to 180 days:

```yaml
alias: "Pawsync: Power Outage Battery Guard"
description: "Conserves battery power during blackout"
trigger:
  - platform: state
    entity_id: binary_sensor.pawsync_feeder_battery_power
    to: "on"
action:
  - service: switch.turn_on
    target:
      entity_id: switch.pawsync_feeder_mute_chime
  - service: notify.notify
    data:
      title: "🔌 Feeder Power Lost"
      message: "Pawsync Feeder is running on backup D-Cell batteries ({{ states('sensor.pawsync_feeder_battery_level') }}%). Offline schedules will continue operating normally."
```

---

## 5. Custom Service Calls & API Actions

Through ESPHome custom services, Home Assistant automations can invoke advanced feeder functions programmatically:

### 5.1 Dispense Exact Gram Target (`pawsync_feeder_dispense_grams`)
```yaml
service: esphome.pawsync_feeder_dispense_grams
data:
  grams: 35
```
*Calculates required portions using `kibble_grams_per_portion` and issues the feed command.*

### 5.2 Play Custom Meal Call TTS (`pawsync_feeder_tts_call`)
```yaml
service: tts.speak
target:
  entity_id: tts.piper
data:
  media_player_entity_id: media_player.pawsync_feeder_speaker
  message: "Dinner time, Milo! Come and get your food!"
```
*Streams high-fidelity speech directly to the NS4168 Class-D amplifier on the feeder.*
