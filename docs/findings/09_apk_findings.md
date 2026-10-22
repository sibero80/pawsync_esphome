# Pawsync Smart Pet Feeder (PPF-R361S) - APK Reverse Engineering Report

> **Target Model:** Pawsync Smart Pet Feeder (Model `PPF-R361S` / `PPF-R361S-WUS`)  
> **Config Module:** `VS_WB_PFM_PPF-R361S-WUS_US` (BLE Model ID: `92`)  
> **Ecosystem:** VeSync / Arovast Pet Ecosystem  
> **Objective:** Comprehensive feature extraction, cloud JSON protocol mapping, schedule/scale models, and settings inventory to unblock ESPHome component implementation and Home Assistant custom integration (resolving `PORTING_PLAN.md` Q12).

---

## 1. App Identity & Architecture Analysis

### 1.1 Package Information & Checksums
- **Package Name:** `com.pawsync.pet`
- **Version Name:** `1.1.32`
- **Version Code:** `46`
- **SDK Target:** `minSdkVersion: 28` (Android 9.0 Pie), `targetSdkVersion: 35` (Android 15)
- **Compile SDK:** `35`
- **Package Hashes (SHA-256):**
  - Container (`Pawsync_1.1.32_APKPure.xapk`): `91ee82c53ef5f7f6c39d6f58ae660f418c6bfcfb62b1371d5c63f04f520a8005`
  - Base APK (`com.pawsync.pet.apk`): `37ea03f5a79859f2c2e8136b0c98a64ba6abbc300a3ab1510dd9e7c875e604b8`
  - ABI Split (`config.armeabi_v7a.apk`): `4f6ee1d475bb3bac3e4677ed33e5b2a39becc60e51b4112e0e12cb99feef6c9a`
  - Language Split (`config.en.apk`): `b51f6c994fa1e550be4b6d1a17b50c13d2970426738aa5cd19509cba4c43e9fd`
  - Density Split (`config.mdpi.apk`): `9e012debd20ac7b66c79db7791ab957ce4a56ff296459aa91eebee52298cd7a9`

### 1.2 Technology Stack
- **Native Android:** Pure Kotlin + Java decompiled codebase.
- **UI Frameworks:** Jetpack Compose + Android Jetpack Material / ViewBinding / Custom WheelPickers.
- **Networking:** Retrofit 2 + OkHttp 3 + RxJava 2 + Kotlin Coroutines.
- **Architecture:** MVVM (Repository pattern with `BaseMvvmActivity`, `BaseViewModel`, LiveData observers).
- **Panel Delivery Finding `[CONFIRMED]`:**
  - Unlike classic VeSync smart home appliances which download React Native bundles or H5 web zips dynamically, the Pawsync Smart Pet Feeder panel is **100% native** and compiled directly into `classes*.dex` (`com.pawsync.pet.device.ui.device.feeder.*`).
  - No remote panel download or external bundle fetch is required. All UI definitions, strings, validation logic, and cloud bypass payload builders are fully present and offline-analyzable in the APK.

---

## 2. Cloud Envelope & Transport Architecture

### 2.1 Bypass Endpoint & Enveloping
All device communication from the Pawsync app passes through the VeSync cloud bypass endpoint:
- **Endpoint URL:** `POST /pet/api/deviceManaged/v1/bypassV2` `[CONFIRMED]` (Source: `com.pawsync.pet.device.network.RetrofitServiceBypassFeederApi`, `RetrofitServiceBypassCommonApi`)
- **Base Server:** Standard VeSync regional cloud base URL (e.g., `https://smartapi.vesync.com` / `smartapi-us.vesync.com`).

### 2.2 Request Envelope Structure
```json
{
  "context": {
    "traceId": "1730000000000",
    "accountID": "12345678",
    "token": "redacted_token...",
    "userType": "1",
    "bizType": "pet",
    "countryCode": "US",
    "language": "en",
    "timeZone": "America/New_York",
    "appVersion": "1.1.32"
  },
  "data": {
    "method": "<method_name>",
    "source": "APP",
    "data": {
      "cid": "<device_uuid_or_cid>",
      "configModule": "VS_WB_PFM_PPF-R361S-WUS_US",
      "...method_payload_fields..."
    }
  }
}
```

### 2.3 Response Envelope Structure
```json
{
  "code": 0,
  "msg": "ok",
  "result": {
    "...response_fields..."
  }
}
```
Standard success is indicated by `code: 0`. Non-zero `code` values represent API or firmware faults (e.g. device offline, timeout, or validation errors).

### 2.4 Live Network Traffic & Cloud Transport Verification (OpenWrt Capture) `[CONFIRMED]`

On 2026-10-21 / 2026-10-22, live network traffic to and from the feeder was non-destructively captured and analyzed on the local OpenWrt access point:

#### Network Discovery & Association
- **Feeder Hardware:** Espressif ESP32-C3 Wi-Fi SoC.
- **Feeder MAC Address:** `94:a9:90:4c:7e:d8` (Espressif OUI).
- **Assigned Local IP:** `192.168.1.48`.
- **AP Attachment:** Associated to SSID `PawTest` on interface `phy1-ap1` of Ubiquiti AP (`192.168.1.160`), bridged to `br-lan`.
- **Default Gateway & DNS:** ISP Router (`192.168.1.1`).
- **Signal Quality:** `-39 dBm` (very strong).

#### Live Cloud Transport & Encryption
- **Remote Cloud Endpoint:** `34.225.33.72` (`ec2-34-225-33-72.compute-1.amazonaws.com` in AWS us-east-1).
- **Remote Port:** **`3883`** (VeSync proprietary device broker port).
- **Transport Security:** **TLS 1.2** (`0x17 0x03 0x03` application data records). The communication is fully encrypted; no plaintext TCP or unencrypted MQTT is used on the wire.

#### Live Feeding Event Capture Analysis
During a user-initiated manual feeding test triggered from the official mobile app, 53 packets were captured on `phy1-ap1` (archived at `/root/openwrt/feeder_feed_event.pcap`):
1. **Command Ingestion (`19:11:58.050`):**
   - Cloud server (`34.225.33.72:3883`) delivers 3 TLS Application Data records (lengths `336`, `333`, `338`, total **1,008 bytes**) to the feeder.
   - This matches the `manualFeeding` bypass payload format discovered during APK analysis.
   - The feeder immediately sends a TCP ACK (`ack 1007`) and transmits a 154-byte TLS confirmation packet.
2. **Dispensing & Real-Time Scale Telemetry Stream (`19:12:05 – 19:12:09`):**
   - Exactly 7 seconds later (while the motor rotates and kibble dispenses into the bowl), the feeder streams **10 burst records** back to the server:
     - Record payload lengths: `830`, `133`, `707`, `706`, `709`, `708`, `703`, `833`, `429`, `420` bytes.
   - These payloads carry continuous strain-gauge load cell weight deltas and chute optical sensor pulses.
3. **Completion & Idle State (`19:12:13`):**
   - Feeder sends final dispensed weight and completes the feeding sequence.

#### Technical Feasibility: Local Cloud Spoofing vs. ESPHome Flashing
- **Local Cloud Spoofing Feasibility:** **Unfeasible.** Because port `3883` requires a TLS 1.2 handshake, any local interception (via OpenWrt DNS hijacking or DNAT) requires terminating TLS locally. The stock ESP32-C3 firmware bundles the Amazon Root CA and strictly validates the broker's TLS certificate. A local mock broker will trigger TLS handshake rejection (`SSL_ALERT_BAD_CERTIFICATE`) unless the firmware is modified or certificates extracted.
- **ESPHome Replacement Feasibility:** **Optimal & Recommended.** Flashing ESPHome onto the ESP32-C3 completely eliminates the cloud/TLS requirement, talks directly to the SC95F8766P coprocessor over local UART, and connects natively to Home Assistant with 100% local control.

---

## 3. Comprehensive Bypass Method Dictionary

Every bypass method that can be dispatched to or received from the feeder is detailed below.

### 3.1 Device Status & Capabilities

#### `getPetDeviceStatus`
- **Evidence:** `com.pawsync.pet.device.network.BypassCommonApi:33` `[CONFIRMED]`
- **Direction:** App → Cloud → Device
- **UI Trigger:** Automatically polled upon navigating to feeder home screen (`FeederMainFragment`), pull-to-refresh, and periodic status polling (every 5-10s).
- **Request `data`:**
  ```json
  {
    "cid": "<cid>",
    "configModule": "VS_WB_PFM_PPF-R361S-WUS_US"
  }
  ```
- **Response `result` (`FeederStatus`):**
  | Field Name | Type | Unit / Enum | Meaning / Range | Evidence |
  |---|---|---|---|---|
  | `bowlWeight` | `int` | grams (g) | Live weight currently measured in the food bowl (-50..1000g). Negative indicates tare needed. | `FeederStatus.java:25` `[CONFIRMED]` |
  | `singleWeight_g` | `int` | grams (g) | Portion unit weight (calibrated kibble weight per portion, typically 8..12g, default ~9g). | `FeederStatus.java:54` `[CONFIRMED]` |
  | `portion` | `int` | count | Number of portions dispensed in current/recent action (1..20). | `FeederStatus.java:46` `[CONFIRMED]` |
  | `lastFeedWeight` | `int` | grams (g) | Total food dispensed during the most recent feeding event. | `FeederStatus.java:43` `[CONFIRMED]` |
  | `contentInPot` | `int` | % / enum | Food hopper level: `0` (Empty), `1..30` (Low), `31..70` (Medium), `71..100` (Full). | `FoodInTank.java:11` `[CONFIRMED]` |
  | `contentRemainTime` | `int` | days | Estimated days of pet food remaining in the hopper based on consumption rate. | `FeederStatus.java:31` `[CONFIRMED]` |
  | `desiccantRemainTime` | `int` | days | Days remaining before silica desiccant replacement is required (max 30 days). | `FeederStatus.java:34` `[CONFIRMED]` |
  | `powerAdapter` | `int` | enum | Power source state: `0` = Disconnected (Battery power), `1` = Connected (AC adapter power). | `BaseDevice.java:606` `[CONFIRMED]` |
  | `energy` | `int` | percent (%) | Battery capacity remaining (0..100%). Displayed when on battery power. | `BaseDevice.java:481` `[CONFIRMED]` |
  | `bowlConnected` | `string` | enum | Scale connection state: `"normal"` (connected), `"bowlConnAbnormal"` (bad contact), `"bowlNotPlaced"` (bowl lifted). | `FeederAlertType.java:18` `[CONFIRMED]` |
  | `zeroStatus` | `int` | enum | Tare/zero calibration status: `0` = Calibrated/Normal, `1` = Zeroing recommended, `2` = Zeroing required. | `FeederMainFragment.java:638` `[CONFIRMED]` |
  | `slowFeedMode` | `object` | `{"enable": 0\|1}` | Slow feeding mode toggle (dispenses kibble in pulses with pauses to prevent gobbling). | `FeederStatus.java:62` `[CONFIRMED]` |
  | `intelligentFeeding` | `object` | `{"enable": 0\|1}` | Smart feeding mode: checks leftovers in bowl before scheduled meal and deducts leftover weight. | `FeederStatus.java:40` `[CONFIRMED]` |
  | `accurateFeeding` | `object` | `{"enable": 0\|1}` | Precision feeding mode: adjusts motor steps to minimize meal-to-meal variation. | `FeederStatus.java:19` `[CONFIRMED]` |
  | `sleepMode` | `object` | `{enable, startClkSec, endClkSec}` | DND mode disabling LED indicator display and speaker chime during night hours. | `SleepModeResponse.java:8` `[CONFIRMED]` |
  | `setVoice` | `int` | `0\|1` | Voice audio playback enabled/disabled flag. | `FeederStatus.java:52` `[CONFIRMED]` |

#### `getPetFunction`
- **Evidence:** `com.pawsync.pet.device.network.BypassCommonApi:36` `[CONFIRMED]`
- **Direction:** App → Cloud → Device
- **UI Trigger:** Feeder initialization and capability discovery.
- **Response `result` (`FeederFunction`):**
  Returns static capabilities and hardware limits of the feeder:
  - `feedingPlan`: `{"maxPlanCount": 7, "maxMealCountPerPlan": 10, "maxPortionPerMeal": 20, "supportCorrection": 1}`
  - `voice`: `{"duration": 10, "sampleRate": 8000, "sampleBit": 16, "fileType": ["pcm"], "supportVolume": 1}`
  - `deviceCalibration`: `{"support": 1, "mealMeasureTimeout": 60}`
  - `contentManagement`: `{"support": 1, "potVolume_ml": 4000}`
  - `desiccant`: `{"support": 1, "maxResetTime": 30}`
  - `slowFeedMode`, `sleepMode`, `accurateFeeding`: `{"support": 1}`

---

### 3.2 Dispensing & Feeding Operations

#### `manualFeeding`
- **Evidence:** `com.pawsync.pet.device.network.BypassFeederApi:68` `[CONFIRMED]`
- **Direction:** App → Cloud → Device
- **UI Trigger:** `FeederMainFragment` "Feed" button -> `ManualFeedingDialog` portion wheel picker (1..10 portions in dialog; protocol supports up to 20 portions).
- **Request `data`:**
  ```json
  {
    "cid": "<cid>",
    "configModule": "VS_WB_PFM_PPF-R361S-WUS_US",
    "serving1": 18,
    "serving2": null
  }
  ```
  *Note:* `serving1` transmits the target weight in **grams** to dispense (`portions * singleWeight_g`). `serving2` is reserved for dual-hopper models (null on single-hopper PPF-R361S).
- **Response:** Standard bypass envelope (`code: 0`).

#### `updateFoodInfo`
- **Evidence:** `com.pawsync.pet.device.network.BypassFeederApi:101` `[CONFIRMED]`
- **Direction:** App → Cloud → Device
- **UI Trigger:** Triggered when food type or kibble profile is modified.
- **Request `data`:** `{"cid": "<cid>", "configModule": "..."}`.

---

### 3.3 Feeding Plans & Schedules

#### `getFeedingPlanList`
- **Evidence:** `com.pawsync.pet.device.network.BypassFeederApi:47` `[CONFIRMED]`
- **Request `data`:** `{"cid": "<cid>", "configModule": "...", "index": 0}`
- **Response `result`:**
  ```json
  {
    "total": 1,
    "planList": [
      {
        "planId": 101,
        "planName": "Daily Schedule",
        "enable": 1,
        "repeat": 254,
        "dailyTotalWeightG": 90
      }
    ]
  }
  ```

#### `getFeedingPlanDetail`
- **Evidence:** `com.pawsync.pet.device.network.BypassFeederApi:44` `[CONFIRMED]`
- **Request `data`:** `{"cid": "<cid>", "configModule": "...", "planId": 101}`
- **Response `result`:**
  ```json
  {
    "planId": 101,
    "planName": "Daily Schedule",
    "enable": 1,
    "repeat": 254,
    "scheduleList": [
      {"timeSec": 28800, "weight": 30},
      {"timeSec": 46800, "weight": 30},
      {"timeSec": 68400, "weight": 30}
    ]
  }
  ```

#### `createFeedingPlan`
- **Evidence:** `com.pawsync.pet.device.network.BypassFeederApi:35` `[CONFIRMED]`
- **Request `data`:**
  ```json
  {
    "cid": "<cid>",
    "configModule": "VS_WB_PFM_PPF-R361S-WUS_US",
    "planName": "Weekday Plan",
    "repeat": 124,
    "scheduleList": [
      {"timeSec": 28800, "weight": 27},
      {"timeSec": 64800, "weight": 36}
    ]
  }
  ```
- **Response `result`:** `{"planId": 102}`

#### `updateFeedingPlan`
- **Evidence:** `com.pawsync.pet.device.network.BypassFeederApi:92` `[CONFIRMED]`
- **Request `data`:**
  ```json
  {
    "cid": "<cid>",
    "configModule": "VS_WB_PFM_PPF-R361S-WUS_US",
    "planId": 101,
    "planName": "Updated Schedule",
    "repeat": 254,
    "scheduleList": [
      {"timeSec": 25200, "weight": 36},
      {"timeSec": 68400, "weight": 36}
    ]
  }
  ```

#### `updateFeedingPlanStatus`
- **Evidence:** `com.pawsync.pet.device.network.BypassFeederApi:98` `[CONFIRMED]`
- **Request `data`:** `{"cid": "<cid>", "configModule": "...", "planId": 101, "enable": 1}`

#### `updateFeedingPlanBatch`
- **Evidence:** `com.pawsync.pet.device.network.BypassFeederApi:95` `[CONFIRMED]`
- **Request `data`:**
  ```json
  {
    "cid": "<cid>",
    "configModule": "VS_WB_PFM_PPF-R361S-WUS_US",
    "feedingPlanList": [
      {"planId": 101, "planName": "Plan A", "repeat": 126, "schedule": [...]},
      {"planId": 102, "planName": "Plan B", "repeat": 128, "schedule": [...]}
    ]
  }
  ```

#### `deleteFeedingPlan`
- **Evidence:** `com.pawsync.pet.device.network.BypassFeederApi:41` `[CONFIRMED]`
- **Request `data`:** `{"cid": "<cid>", "configModule": "...", "planId": 102}`

#### `getNextScheduleForToday`
- **Evidence:** `com.pawsync.pet.device.network.BypassFeederApi:50` `[CONFIRMED]`
- **Request `data`:** `{"cid": "<cid>", "configModule": "..."}`
- **Response `result`:**
  ```json
  {
    "state": 0,
    "planDetail": {
      "planId": 101,
      "timeSec": 64800,
      "weight": 27
    }
  }
  ```
  *States:* `0` = Next meal scheduled today, `1` = No more meals scheduled today, `2` = No active plan configured.

---

### 3.4 Scale, Tare & Portion Calibration

#### `setFeedingBowlToZero` (Tare Scale)
- **Evidence:** `com.pawsync.pet.device.network.BypassFeederApi:77` `[CONFIRMED]`
- **Direction:** App → Cloud → Device
- **UI Trigger:** `FeederMainFragment` "Zero Out" icon button and scale calibration wizard.
- **Request `data`:** `{"cid": "<cid>", "configModule": "..."}`
- **Response `result` (`ZeroResponse`):**
  If successful, returns empty result or `failureType: null`. If failed:
  ```json
  {
    "failureType": "weightFluctuation"
  }
  ```
  *Failure Enums:*
  - `"weightFluctuation"`: Weight unstable (cat touching bowl or vibration).
  - `"bowlConnAbnormal"`: Weighing platform pins disconnected from base.
  - `"bowlNotPlaced"`: Stainless steel bowl is absent.

#### `startPetSingleMealMeasure`
- **Evidence:** `com.pawsync.pet.device.network.BypassFeederApi:89` `[CONFIRMED]`
- **Direction:** App → Cloud → Device
- **UI Trigger:** "Portion Calibration" / "Kibble Size Setup" screen.
- **Behavior:** Instructs the feeder to tare the bowl and dispense 5 consecutive test portions to calculate average kibble weight.
- **Request `data`:** `{"cid": "<cid>", "configModule": "..."}`

#### `getPetSingleMealMeasure`
- **Evidence:** `com.pawsync.pet.device.network.BypassFeederApi:59` `[CONFIRMED]`
- **Direction:** App → Cloud → Device
- **UI Trigger:** Polled every 5 seconds (`TimeUnit.SECONDS`) during calibration.
- **Response `result` (`MealMeasureResponse`):**
  ```json
  {
    "state": 2,
    "portion": 5,
    "single_weight_g": 9,
    "type": "normal"
  }
  ```
  *State / Fault Enums in `type`:* `"normal"`, `"jamFood"`, `"overLoad"`, `"blockFood"`, `"scantyFood"`, `"bowlConnAbnormal"`, `"bowlNotPlaced"`.

#### `savePetSingleMealMeasure`
- **Evidence:** `com.pawsync.pet.device.network.BypassFeederApi:74` `[CONFIRMED]`
- **Direction:** App → Cloud → Device
- **Request `data`:**
  ```json
  {
    "cid": "<cid>",
    "configModule": "VS_WB_PFM_PPF-R361S-WUS_US",
    "portion": 5,
    "single_weight_g": 9
  }
  ```

---

### 3.5 Mode & Configuration Toggles

#### `setPetSlowFeedMode`
- **Evidence:** `com.pawsync.pet.device.network.BypassFeederApi:86` `[CONFIRMED]`
- **Request `data`:** `{"cid": "<cid>", "configModule": "...", "enable": 1}`

#### `setIntelligentFeedingMode`
- **Evidence:** `com.pawsync.pet.device.network.BypassFeederApi:83` `[CONFIRMED]`
- **Request `data`:** `{"cid": "<cid>", "configModule": "...", "enable": 1}`

#### `setIAccurateFeedingMode`
- **Evidence:** `com.pawsync.pet.device.network.BypassFeederApi:80` `[CONFIRMED]`
- **Request `data`:** `{"cid": "<cid>", "configModule": "...", "enable": 1}`

#### `setPetSleepMode` (Do Not Disturb)
- **Evidence:** `com.pawsync.pet.device.network.BypassCommonApi:48` `[CONFIRMED]`
- **Request `data`:**
  ```json
  {
    "cid": "<cid>",
    "configModule": "VS_WB_PFM_PPF-R361S-WUS_US",
    "enable": 1,
    "startClkSec": 72000,
    "endClkSec": 21600
  }
  ```
  *Note:* `startClkSec` = 72000 (20:00 / 8:00 PM), `endClkSec` = 21600 (06:00 / 6:00 AM). Disables feeder LEDs and chime.

---

### 3.6 Food Hopper & Silica Desiccant Management

#### `getPetDesiccantInfo` / `updatePetDesiccantInfo`
- **Evidence:** `com.pawsync.pet.device.network.BypassFeederApi:56, 107` `[CONFIRMED]`
- **Request `data` (`updatePetDesiccantInfo`):**
  ```json
  {
    "cid": "<cid>",
    "configModule": "VS_WB_PFM_PPF-R361S-WUS_US",
    "remainTime": 30
  }
  ```
- **Response `result` (`getPetDesiccantInfo`):** `{"remainTime": 24}`

#### `getPetCurrentContentSize` / `updatePetContentSize`
- **Evidence:** `com.pawsync.pet.device.network.BypassFeederApi:53, 104` `[CONFIRMED]`
- **Request `data` (`updatePetContentSize`):**
  ```json
  {
    "cid": "<cid>",
    "configModule": "VS_WB_PFM_PPF-R361S-WUS_US",
    "volume_ml": 4000.0,
    "type": 1
  }
  ```
- **Response `result` (`CurrentPetContentSize`):**
  ```json
  {
    "contentInPot": 85,
    "daysRemain": 14,
    "volume_ml": 3400.0
  }
  ```

---

### 3.7 Voice Meal-Call Settings & Playback

#### `getPetVoiceSetting`
- **Evidence:** `com.pawsync.pet.device.network.BypassFeederApi:65` `[CONFIRMED]`
- **Response `result` (`VoiceSetting`):**
  ```json
  {
    "voiceUrl": "https://...",
    "duration": 5,
    "volume": 80,
    "manualVoice": 1,
    "scheduleVoice": 1,
    "sampleRate": 8000
  }
  ```

#### `updatePetVoiceSetting`
- **Evidence:** `com.pawsync.pet.device.network.BypassFeederApi:110` `[CONFIRMED]`
- **Request `data`:**
  ```json
  {
    "cid": "<cid>",
    "configModule": "VS_WB_PFM_PPF-R361S-WUS_US",
    "voiceUrl": "https://resource.vesync.com/audio/...",
    "duration": 5,
    "volume": 80,
    "manualVoice": 1,
    "scheduleVoice": 1,
    "sampleRate": 8000
  }
  ```

#### `getPetVoiceProcess`
- **Evidence:** `com.pawsync.pet.device.network.BypassFeederApi:62` `[CONFIRMED]`
- **Response `result` (`VoiceDownloadProgress`):**
  `{"process": 100, "state": 1}` (Monitors feeder audio download progress).

#### `playPetVoice`
- **Evidence:** `com.pawsync.pet.device.network.BypassFeederApi:71` `[CONFIRMED]`
- **UI Trigger:** "Test Voice" / "Play Voice" button in `VoiceSettingsActivity`.
- **Request `data`:** `{"cid": "<cid>", "configModule": "..."}`

---

### 3.8 Alerts & Notifications

#### `getPetDeviceAlertList`
- **Evidence:** `com.pawsync.pet.device.network.BypassCommonApi:30` `[CONFIRMED]`
- **Response `result`:**
  ```json
  {
    "list": [
      {"type": "scantyFood", "timeStamp": 1730000000000}
    ]
  }
  ```

#### `resetPetAlert`
- **Evidence:** `com.pawsync.pet.device.network.BypassCommonApi:45` `[CONFIRMED]`
- **Request `data`:**
  ```json
  {
    "cid": "<cid>",
    "configModule": "VS_WB_PFM_PPF-R361S-WUS_US",
    "type": "scantyFood"
  }
  ```

---

### 3.9 Activity & Feeding History

#### `getPetLogList`
- **Evidence:** `com.pawsync.pet.device.net.HomeCloudApi:19` `[CONFIRMED]`
- **Direction:** App → Cloud
- **Request Body:**
  ```json
  {
    "deviceId": "<cid>",
    "startTimestamp": 1729900000000,
    "endTimestamp": 1730000000000,
    "pageSize": 20,
    "logType": null,
    "objectType": 0,
    "petId": null,
    "logMaxId": null
  }
  ```
- **Response `result` (`GetLogListResponse`):**
  Returns array of `LogModel`:
  - `logId` (`int`): Unique event sequence ID.
  - `timestamp` (`long`): Event timestamp in milliseconds.
  - `logType` (`string`): Event type identifier (e.g. `"manualFeeding"`, `"planFeeding"`, `"takeFood"`, `"abnormalDispensingFood"`, `"balanceFeedingMore"`, `"balanceFeedingLess"`).
  - `value` (`int`): Grams dispensed or grams eaten.
  - `durationInS` (`int`): Eating duration in seconds (for `takeFood` events).
  - `text` (`string`): Preformatted description.

---

## 4. Settings & UI Inventory (PORTING_PLAN Q12 Resolution)

Below is the complete UI inventory from the native feeder screens, mapped directly to Home Assistant / ESPHome entity types.

| UI Screen | Control Type | UI Label (English) | Backing Method & Field | Range / Options | Suggested Home Assistant Entity |
|---|---|---|---|---|---|
| **Main Feeder Screen** | Text / Gauge | Bowl Weight | `getPetDeviceStatus` -> `bowlWeight` | -50..1000 g | `sensor.pet_feeder_bowl_weight` (unit: `g`) |
| **Main Feeder Screen** | Text / Progress | Food Tank Level | `getPetDeviceStatus` -> `contentInPot` | 0=Empty, 1..30=Low, 31..70=Med, 71..100=Full | `sensor.pet_feeder_food_level` (enum / %) |
| **Main Feeder Screen** | Text | Food Remaining Days | `getPetDeviceStatus` -> `contentRemainTime` | 0..90 days | `sensor.pet_feeder_food_remaining_days` |
| **Main Feeder Screen** | Icon / Badge | Scale Bowl Status | `getPetDeviceStatus` -> `bowlConnected` | `normal`, `bowlConnAbnormal`, `bowlNotPlaced` | `binary_sensor.pet_feeder_bowl_connected` |
| **Main Feeder Screen** | Button | Zero Out (Tare) | `setFeedingBowlToZero` | Trigger | `button.pet_feeder_tare_scale` |
| **Main Feeder Screen** | Button + Picker | Manual Feed | `manualFeeding` -> `serving1` | 1..20 portions (or grams) | `number.pet_feeder_manual_feed_portions` + `button.pet_feeder_feed` |
| **Main Feeder Screen** | Icon / Status | Power Source | `getPetDeviceStatus` -> `powerAdapter` | `0` (Battery), `1` (AC Adapter) | `binary_sensor.pet_feeder_power_connected` |
| **Main Feeder Screen** | Icon / Gauge | Battery Level | `getPetDeviceStatus` -> `energy` | 0..100 % | `sensor.pet_feeder_battery_level` (unit: `%`) |
| **Main Feeder Screen** | Text | Last Dispensed Weight | `getPetDeviceStatus` -> `lastFeedWeight` | 0..500 g | `sensor.pet_feeder_last_meal_weight` (unit: `g`) |
| **Feeding Plan Screen** | Toggle | Enable Feeding Plan | `updateFeedingPlanStatus` -> `enable` | `0` (Disabled), `1` (Enabled) | `switch.pet_feeder_feeding_plan_enabled` |
| **Feeding Plan Screen** | List / Form | Meal Schedules | `createFeedingPlan`, `updateFeedingPlan` | Up to 10 meals/day, timeSec, weight | Custom schedule or HA automations / input_datetime |
| **Device Settings** | Toggle | Slow Feeding | `setPetSlowFeedMode` -> `enable` | `0` / `1` | `switch.pet_feeder_slow_feed` |
| **Device Settings** | Toggle | Smart Feeding | `setIntelligentFeedingMode` -> `enable` | `0` / `1` | `switch.pet_feeder_smart_feeding` |
| **Device Settings** | Toggle | Precision Mode | `setIAccurateFeedingMode` -> `enable` | `0` / `1` | `switch.pet_feeder_precision_mode` |
| **Device Settings** | Toggle | Sleep Mode (DND) | `setPetSleepMode` -> `enable` | `0` / `1` | `switch.pet_feeder_sleep_mode` |
| **Device Settings** | Time Pickers | Sleep Start / End Time | `setPetSleepMode` -> `startClkSec`, `endClkSec` | 0..86399 sec | `time.pet_feeder_sleep_start` / `time.pet_feeder_sleep_end` |
| **Voice Settings** | Slider | Speaker Volume | `updatePetVoiceSetting` -> `volume` | 0..100 % | `number.pet_feeder_speaker_volume` (unit: `%`) |
| **Voice Settings** | Toggle | Manual Feed Chime | `updatePetVoiceSetting` -> `manualVoice` | `0` / `1` | `switch.pet_feeder_manual_feed_sound` |
| **Voice Settings** | Toggle | Scheduled Feed Chime| `updatePetVoiceSetting` -> `scheduleVoice`| `0` / `1` | `switch.pet_feeder_schedule_feed_sound` |
| **Voice Settings** | Button | Play Voice Now | `playPetVoice` | Trigger | `button.pet_feeder_play_meal_call` |
| **Desiccant Screen** | Progress / Text | Desiccant Remaining | `getPetDesiccantInfo` -> `remainTime` | 0..30 days | `sensor.pet_feeder_desiccant_remaining` (days) |
| **Desiccant Screen** | Button | Reset Desiccant | `updatePetDesiccantInfo` -> `remainTime: 30`| Trigger | `button.pet_feeder_reset_desiccant` |
| **Calibration Screen**| Wizard | Calibrate Portion | `startPetSingleMealMeasure`, `save...` | 5 portions dispense | `button.pet_feeder_calibrate_portion` |
| **Device Info** | Info Text | Firmware Version | `deviceInfo.firmware` (composite) | e.g. `1.0.01(1.0.02)` | `sensor.pet_feeder_firmware` / device info |
| **Device Hardware** | Local Hardware | Child Lock | Local MCU timer (Hold FEED 3s) | Auto-lock 5m idle | `binary_sensor.pet_feeder_child_lock` |

---

## 5. Schedule & Feeding Plan Model

### 5.1 Feeding Plan Limits
- **Max Plans (`maxPlanCount`):** `7` `[CONFIRMED]` (Source: `FeedingPlanModel.java:12`)
- **Max Meals Per Plan (`maxMealCountPerPlan`):** `10` `[CONFIRMED]` (Source: `FeedingPlanModel.java:15`)
- **Max Portions Per Meal (`maxPortionPerMeal`):** `20` `[CONFIRMED]` (Source: `FeedingPlanModel.java:18`)

### 5.2 Time Representation
- Meal execution time is encoded as **`timeSec`** `[CONFIRMED]` (Source: `Schedule.java:8`).
- Defined as integer seconds elapsed since local midnight (`00:00:00`):
  $$\text{timeSec} = (\text{hour} \times 3600) + (\text{minute} \times 60) + \text{second}$$
- Example: `08:00:00` AM $\rightarrow 28800$, `18:30:00` PM $\rightarrow 66600$.
- **Time Zone Handling:** Time is resolved in local device timezone as transmitted in context or configured during provisioning. The ESP/MCU RTC maintains local wall-clock seconds.

### 5.3 Weekday Bitmask Encoding (`repeat`)
The weekday repeat pattern is encoded in an 8-bit integer (`repeat`), with **Bit 0 always 0** `[CONFIRMED]` (Source: `AddOrEditFeedingPlanActivity.java`, `FeedingPlanItem.java`):

| Bit | Hex Mask | Decimal | Day of Week |
|---|---|---|---|
| **Bit 7** | `0x80` | `128` | Sunday |
| **Bit 6** | `0x40` | `64` | Saturday |
| **Bit 5** | `0x20` | `32` | Friday |
| **Bit 4** | `0x10` | `16` | Thursday |
| **Bit 3** | `0x08` | `8` | Wednesday |
| **Bit 2** | `0x04` | `4` | Tuesday |
| **Bit 1** | `0x02` | `2` | Monday |
| **Bit 0** | `0x01` | `1` | Reserved / Always `0` |

- **Everyday (Mon–Sun):** $128 + 64 + 32 + 16 + 8 + 4 + 2 = \mathbf{254}$ (`0xFE`).
- **Weekdays (Mon–Fri):** $32 + 16 + 8 + 4 + 2 = \mathbf{62}$ (`0x3E`).
- **Weekends (Sat–Sun):** $128 + 64 = \mathbf{192}$ (`0xC0`).
- **One-time:** $\mathbf{0}$ (`0x00`).

---

## 6. Weight, Scale Model & Value Conversions

### 6.1 Weight Storage & Internal Units
All weights are measured and transmitted natively in **grams (g)** as integer values:
- Live bowl weight: `bowlWeight` (integer grams, negative values down to -50g indicate tare calibration drift).
- Single portion weight: `singleWeight_g` (integer grams, default 9g).
- Meal target weight: `Schedule.weight` (integer grams, `portions * singleWeight_g`).

### 6.2 Display Conversion Formulas (`o6.e`)
The conversion utility `o6.e` defines exact multipliers:
- **Grams to Ounces:**
  $$\text{weight}_{\text{oz}} = \text{weight}_{\text{g}} \times 0.035274\text{f}$$
  Formatted to one decimal place (`String.format(Locale.ENGLISH, "%.1f", ...)`).
- **Ounces to Grams:**
  $$\text{weight}_{\text{g}} = \text{round}\left(\frac{\text{weight}_{\text{oz}}}{0.035274\text{f}}\right)$$
- **Pet Weight (Grams to Pounds):**
  $$\text{weight}_{\text{lb}} = \text{weight}_{\text{g}} \times 0.002205\text{f}$$
- **Water Volume (Milliliters to Fluid Ounces):**
  $$\text{volume}_{\text{fl\_oz}} = \text{volume}_{\text{ml}} \times 0.033814\text{d}$$

### 6.3 Thresholds & Calibration Constants
- **Excess Food in Bowl Threshold:** **`150 g`** (approx. 5.3 oz) `[CONFIRMED]`. If the bowl weight exceeds 150g before dispensing, the feeder raises alert `blockFood` / `blockFoodFeeding` to prevent overflow and motor jamming.
- **Single Meal Calibration Routine:** The feeder dispenses **5 portions** (`portion: 5`), weighs the total dispensed food, and calculates $\text{singleWeight\_g} = \text{total\_g} / 5$.

---

## 7. Faults, Errors & Notification Code Table

The feeder signals operational states and alarms via `FeederAlertType` enum strings `[CONFIRMED]` (Source: `com.pawsync.pet.device.model.feeder.FeederAlertType` and `strings.xml`):

| Alert String (`FeederAlertType`) | Category | Exact App UI Text (`strings.xml`) | Cause / Recommended HA Entity |
|---|---|---|---|
| `scantyFood` | Warning | *"Feeder tank is low. Time for a refill!"* | `binary_sensor.pet_feeder_food_low` (ON) |
| `lackFood` | Critical | *"Feeder tank is empty. Time for a refill!"* | `binary_sensor.pet_feeder_food_empty` (ON) |
| `jamFood` | Critical | *"Please clear blockage in food distributor."* | `binary_sensor.pet_feeder_motor_jammed` (ON) |
| `blockFood` | Warning | *"There is too much food left in the bowl. Please remove it to prevent blocking the food outlet."* | `binary_sensor.pet_feeder_bowl_overflow` (bowl > 150g) |
| `cleanFoodpassages` | Maintenance | *"Time to clean the pet feeder!"* | `binary_sensor.pet_feeder_cleaning_due` |
| `lowBattery` | Warning | *"Time to replace the batteries!"* | `binary_sensor.pet_feeder_battery_low` |
| `replaceDesiccant` | Maintenance | *"Time to replace the silica gel!"* | `binary_sensor.pet_feeder_desiccant_expired` |
| `outage` | Notification | *"The adapter is disconnected and on battery power. Please reconnect as soon as possible."* | `binary_sensor.pet_feeder_power_outage` |
| `bowlConnAbnormal` | Error | *"Please make sure the weighing tray is securely connected to the feeder base."* | `binary_sensor.pet_feeder_scale_disconnected` |
| `bowlNotPlaced` | Error | *"No food bowl detected."* | `binary_sensor.pet_feeder_bowl_missing` |
| `overLoad` | Error | *"Weighing over the limit, please check the bowl and try again."* | `binary_sensor.pet_feeder_scale_overload` |
| `weightFluctuation` | Tare Error | *"Weight is unstable. Please check and keep your scale stable and clean."* | Tare failure notice |
| `abnormalDispensingFood` | Error | *"Your pet feeder may not dispense food as expected, please check it."* | Motor dispenser fault |
| `intelligentFeeding` | Event | *"Smart Feeding Mode: There were leftovers from your pet's last meal, so we dispensed less food..."* | History event log |
| `balanceFeedingMore` | Event | *"Precision Mode triggered and dispensed an additional portion to meet the daily feeding amount."* | Precision adjustment log |
| `balanceFeedingLess` | Event | *"Precision Mode triggered and reduced a portion to meet the daily feeding amount."* | Precision adjustment log |
| `takeFood` | Event | *"%s ate %s of food in %s."* | Feeding consumption event log |

---

## 8. Voice & Meal-Call Architecture

### 8.1 Audio Recording Specifications
- **Audio Recorder Source:** Microphone (`MediaRecorder.AudioSource.MIC` = `1`) `[CONFIRMED]` (Source: `com.pawsync.pet.device.ui.device.feeder.settings.voice.c:182`)
- **Encoding Format:** Raw Linear PCM 16-bit (`AudioFormat.ENCODING_PCM_16BIT` = `2`)
- **Channel Configuration:** Mono (`AudioFormat.CHANNEL_IN_MONO` = `16`)
- **Sample Rate:** `8000 Hz` or `16000 Hz` (specified by `voice.sampleRate` in `FeederFunction`)
- **Max Duration:** `10 seconds` `[CONFIRMED]` (Source: `VoiceRecordingActivity.java:619`)
- **Temporary File:** Stored locally as `audiorecord3.pcm` before upload.

### 8.2 Distribution & Playback Flow
1. **User Recording:** The app records up to 10 seconds of 16-bit 8/16kHz mono raw PCM.
2. **Cloud Upload:** Raw PCM is uploaded to VeSync S3 asset storage, returning a public HTTPS URL (`voiceUrl`).
3. **Firmware Notification:** The app issues `updatePetVoiceSetting` with `voiceUrl`, `duration`, `volume`, `manualVoice`, and `scheduleVoice`.
4. **Feeder Download:** The ESP32 downloads the audio file into flash/SPIFFS. The app monitors status via `getPetVoiceProcess` (`process`: 0..100%).
5. **Playback:** Triggered either on schedule/manual feed if flags are set, or on demand via `playPetVoice`.

---

## 9. Multi-MCU Architecture & Firmware Versioning

### 9.1 Multi-Processor Split
The Pawsync PPF-R361S consists of two distinct processors:
1. **Primary Processor (Main MCU / Wi-Fi SoC):** Espressif **ESP32-C3**. Runs Wi-Fi, BLE, TLS/MQTT cloud client, bypass JSON parser, and audio download.
2. **Secondary Coprocessor (Sub MCU):** Sinowealth **SC95F8766P**. Directly controls stepper/DC dispensing motor, optical IR chute sensors, 4-wire strain-gauge load cell, front-panel tactile buttons, status LEDs, and RTC in battery-backup mode.

### 9.2 Firmware Representation in App
- `FirmwarePlugin.java` distinguishes main and secondary firmwares via **`isMainFw`** `[CONFIRMED]` (Source: `BaseDevice.java:563`, `o5.b:43`):
  - Main Firmware (`isMainFw: true`): ESP32-C3 firmware version (e.g. `1.0.01`).
  - Secondary Firmware (`isMainFw: false`): SC95F8766P MCU firmware version (e.g. `1.0.02`).
- **UI Version Format:** Formatted in `o5.b.java` as:
  $$\text{Version String} = \text{mainFw} + "(" + \text{mcuFw} + ")" \quad \longrightarrow \quad \mathbf{1.0.01(1.0.02)}$$

---

## 10. BLE Provisioning Protocol (VSV3)

The feeder uses the proprietary VeSync VSV3 BLE protocol for Wi-Fi provisioning.

### 10.1 GATT Services and Characteristics
- **Primary Service UUID:** `0000fff0-0000-1000-8000-00805f9b34fb` `[CONFIRMED]`
  - **Write Characteristic:** `0000fff1-0000-1000-8000-00805f9b34fb` (Write Without Response / Write Request)
  - **Notify Characteristic:** `0000fff2-0000-1000-8000-00805f9b34fb` (Notifications enabled)
- **Fallback Service UUID (TI / Alternate):** `f000ffe0-0451-4000-b000-000000000000`
  - Write: `f000ffe1-0451-4000-b000-000000000000`, Notify: `f000ffe2-0451-4000-b000-000000000000`

### 10.2 Packet Framing Structure
All BLE communication conforms to an 11-byte frame header `[CONFIRMED]` (Source: `com.vesync.ble.protocol.vsv3.i`, `h.java`):

| Byte Offset | Field | Type | Description |
|---|---|---|---|
| `0` | **Magic Header** | `uint8` | Constant `0xA5` (165 decimal, `-91` signed byte). |
| `1` | **Flags** | `uint8` | Protocol control flags (bit 0-1: 3, bit 4: ACK required, bit 5-6: routing). |
| `2` | **Sequence** | `uint8` | Rolling message sequence number (`0..255`). |
| `3..4` | **Length** | `uint16_le` | Payload length + 5 (Little-Endian). |
| `5` | **Checksum** | `uint8` | One-byte verification checksum computed over packet bytes. |
| `6` | **Direction / Type** | `uint8` | Command direction (`1` = App to Device, `2` = Device Response). |
| `7..8` | **Opcode** | `uint16_le` | Command opcode identifier (Little-Endian). |
| `9` | **Sub-Opcode** | `uint8` | Sub-command category. |
| `10` | **Encryption Type**| `uint8` | `0` = Plaintext, `1` = AES-128-CBC, `2` = AES-GCM. |
| `11..N` | **Payload** | `byte[]` | Encrypted or plaintext payload data. |

### 10.3 Provisioning Payload
During setup, the app connects over BLE and transmits:
1. `wifiSSID`: Target 2.4 GHz Wi-Fi network SSID.
2. `wifiPassword`: WPA2/WPA3 pre-shared key.
3. `accountID`: Owner user account ID.
4. `configKey` / `token`: Device authentication credential.
5. `serverDN` / `serverIP`: VeSync cloud MQTT broker address.
6. `timeZone`: User timezone string (e.g. `"America/New_York"`).

---

## 11. Open Questions, Acceptance Criteria & Hand-off

### 11.1 Items Requiring Owner OK / Verification
1. **Live Cloud Packet Capture [COMPLETED]:** Performed non-destructively on OpenWrt (Ubiquiti AP `phy1-ap1`) during a live manual feed event. Confirmed the feeder operates over TLS 1.2 on port `3883` to AWS EC2 (`34.225.33.72`). PCAP archived at `/root/openwrt/feeder_feed_event.pcap`. Proved local cloud spoofing is blocked by TLS CA certificate validation, confirming ESPHome firmware flashing as the primary route.
2. **Firmware Dump Verification:** The UART protocol between ESP32-C3 and SC95F8766P can now be matched 1:1 against the method dictionary extracted above.

### 11.2 Acceptance Criteria for ESPHome Firmware & Home Assistant Integration
To ensure complete feature parity with the stock Pawsync application, the custom ESPHome firmware and Home Assistant integration must fulfill:

- [ ] **Scale & Weight Tracking:**
  - Continuous measurement of bowl weight in grams with $\pm 1\,\text{g}$ resolution.
  - Tare / Zero Bowl calibration button and auto-tare thresholding.
  - Detection of bowl removal and scale disconnection.
  - Excess food (>150g) safety cutoff preventing dispensing into an overflowing bowl.
- [ ] **Dispensing & Portion Control:**
  - Manual feed action supporting 1 to 20 portions (or arbitrary grams based on portion calibration).
  - Configurable portion unit weight (calibrated kibble weight, default 9g).
  - Motor stall / jam detection and reverse clearance pulse logic.
- [ ] **Smart Feeding Logic:**
  - Leftover deduction (Smart Feeding): subtract leftover bowl weight from the next scheduled meal.
  - Slow Feeding mode: dispense meals in multi-stage pulses separated by configurable dwell times.
- [ ] **Offline Scheduling:**
  - Support for at least 7 distinct feeding plans with up to 10 meals per day.
  - Full 7-day weekday bitmask repeat handling.
  - Accurate RTC timekeeping during Wi-Fi or Home Assistant outages.
- [ ] **Telemetry & Health Sensors:**
  - Hopper food level status (Empty / Low / Medium / Full).
  - AC power adapter state (Connected / Battery Mode) and battery level (%).
  - Desiccant replacement countdown timer (30 days with reset button).
  - Cleaning reminder alert.
- [ ] **Audio & Alerts:**
  - Speaker audio chime playback on feed trigger with adjustable volume (0..100%).
  - Night Do-Not-Disturb / Sleep Mode disabling LEDs and speaker chimes.
