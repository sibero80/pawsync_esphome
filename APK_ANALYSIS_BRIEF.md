# Pawsync APK Analysis Brief (for the APK Decompilation Agent)

> **Context:** We are replacing the stock ESP32-C3 firmware of a **Pawsync PPF-R361S-WUS** smart feeder (VeSync/Arovast ecosystem) with ESPHome. Main plan: [`PORTING_PLAN.md`](PORTING_PLAN.md). The ESP32-C3 talks to the **cloud** (JSON) and to a **SC95F8766P MCU** (binary UART). The MCU runs the motor, buttons, LEDs, IR sensors, the 4-wire weighing scale, and the RTC/schedule in battery mode.
>
> **Why the APK matters:** The app defines the **cloud JSON vocabulary** (method names, field names, enums, ranges, units, error codes) that the ESP firmware turns into UART opcodes. If we know the JSON side, the firmware decompilation agents can label the UART handlers quickly. Example: the handler for `"setFeedingPlan"` packs meal records X, Y, Z into opcode `0x01 0xAB 0xCD`. The APK also gives the **complete feature/settings list**, which becomes the Home Assistant entity set (PORTING_PLAN Q12, currently **PENDING**).
>
> **You do NOT need to:** reimplement the cloud or app login, or attack servers.

---

## 1. Rules
1. Work offline on the APK/XAPK files. Network activity (mitmproxy against the real app, downloading plugin bundles or firmware) only with the **owner's explicit OK**. Note in your report which items needed it.
2. **Redact secrets** (API keys, signing secrets, account tokens, certificates) in shared docs: first 4 chars + `…`. Raw copies go to `work/private/apk/`.
3. Every finding cites evidence: `file path:line` (jadx), class/method name, JS bundle offset, or Dart function name. Add a confidence tag: `[CONFIRMED]`, `[INFERRED]`, `[GUESS]`.
4. Output files (create these):
   - `docs/findings/09_apk_findings.md` – human-readable report (structure in §5).
   - `docs/findings/09_apk_api_schema.json` – machine-readable dictionary (schema in §6).
   - `work/apk/` – decompiled trees, extracted assets (git-ignored).

---

## 2. Step 0 – Identify the App Technology (decides the toolchain)

| Indicator in APK | Technology | Tools |
|---|---|---|
| `lib/*/libflutter.so` + `libapp.so` | Flutter (Dart AOT) | `blutter` (Dart object/pool dump), `reFlutter`, `strings` on `libapp.so` |
| `assets/index.android.bundle` (Hermes magic `c6 1f bc 03` or plain JS) | React Native | `hermes-dec` / `hbctool` for Hermes; prettier for plain JS |
| `assemblies/*.dll` / `libmonodroid.so` | Xamarin/.NET MAUI | `pyxamstore` + ILSpy |
| `assets/www/`, `assets/h5/`, `.zip` web panels | Hybrid / H5 panels | unzip + JS beautify |
| Only `classes*.dex` | Native Java/Kotlin | `jadx -d work/apk/jadx --show-bad-code`, `apktool d` for resources |

Also check for split APKs (`base.apk` + `split_config.*.apk`) and process all of them.

**VeSync-specific (critical):** VeSync apps often load **per-device "panels" or "plugins"** (React-Native bundles, H5 zips or config JSON) **downloaded at runtime** and keyed by `configModule` / `deviceType` / model code. The feeder UI and its JSON methods may **not be in the APK**. Find out:
- whether a plugin/panel download mechanism exists (search: `configModule`, `plugin`, `panel`, `bundle`, `rn_`, `h5`, `downloadUrl`, `md5`, `zip`, `deviceType`, `PPF`, `R361`, `feeder`, `pet`);
- which model identifiers map to which panel (look for `PPF-R361S`, `PPF-R361S-WUS`, `WUS`, `R361`, `wifi-bt-feeder` …);
- whether a cached panel is shipped in `assets/` as a fallback.

If the panels are remote, document the download endpoint/URL format and its request parameters, then **stop and ask the owner** before downloading. The owner could also pull the cached panel from a rooted phone/emulator at `/data/data/<pkg>/files/...`.

---

## 3. What We Want to Know (Priority Ordered)

### P1 – Device ↔ Cloud command dictionary (MOST IMPORTANT)
VeSync devices typically use a "bypass" envelope, e.g. `POST /cloud/v2/deviceManaged/bypassV2` with `{"cid": …, "configModule": …, "payload": {"method": "<name>", "source": "APP", "data": {…}}}`. Confirm or correct this for the feeder. Then, for **every method** the feeder panel can send, extract:
- method name (exact string), direction (app→device, device→app report, app→cloud only);
- request `data` fields: name, JSON type, unit, range/min/max/step, enum values + meaning, default;
- response/`result` fields, the same detail;
- which UI screen/control triggers it;
- error codes returned (`code`, `msg`) and their user-facing strings.

Feature areas to cover (non-exhaustive; list anything else you find):

| Area | Specific questions |
|---|---|
| **Status query** | Name of the "get status" method and **every field** in its response (motor/feeding state, error bits, food level, weight, lock, sleep, power source, battery, Wi-Fi RSSI, firmware versions MCU+ESP). |
| **Manual feed** | Method, portion field name, **range 1–20** (owner confirmed max 20 – verify), any extra fields (play meal call? source?). Is there a "cancel feed"? |
| **Feeding plan / schedule** | Method(s) to get/set/add/delete/enable meals. **Max meals**, fields per meal (id, hour, minute, portions, weekdays bitmask & bit order, enabled, meal-call flag, name/label), time zone handling (local time vs UTC + tz offset), "skip next meal"/"one-time meal" support. How the app shows meals that ran in battery/offline mode. |
| **Feed records / history** | Method/report for feed events: timestamp format, portions planned vs actual, **grams dispensed/eaten**, source (button/schedule/remote), result/error codes. Offline-log upload behaviour. |
| **Scale / weight** | Live weight field (units, resolution, sign), "food eaten" / "remaining in bowl" calculations (done in app, cloud or device?), **tare/zero** method + result codes, scale-disconnected flag, excess-food (>150 g) threshold field, any calibration factor method, grams-per-portion setting (is portion size user-adjustable, e.g. kibble type/size?), unit preference (g/oz). |
| **Food level** | Low-food / empty flags, number of levels. |
| **Faults** | Jam / blockage / motor errors / scale errors / low battery / power outage notifications: codes → meaning → UI text. |
| **Child lock** | Method, fields; is auto-lock timeout configurable? |
| **Sleep mode / Do-Not-Disturb** | Fields: on/off, start/end time, what it disables (LEDs, sound, buttons?). |
| **Indicators & sound** | LED brightness/on-off, key beep, speaker **volume** range, mute. |
| **Meal call / voice** | Record flow: **audio format** (codec, sample rate, bit depth, channels), **max duration**, file size, upload endpoint and how the device gets it (URL pushed to device? chunked?), "play now" method, per-meal enable. Built-in sounds selectable? |
| **Power** | Adapter vs battery state field, battery level representation (%, levels, low flag), battery-mode notification. |
| **Device settings** | Name, time zone, units, desiccant replacement reminder, any "slow feed"/"portion size"/"kibble size" setting, factory reset/remove device. |
| **Firmware update** | Endpoint & fields for update check; are **ESP and MCU firmware versioned separately** (e.g. `mainFw`/`mcuFw`)? Field names for current versions. Do **not** download images without owner OK; just document URL format. |

### P2 – Complete settings/UI inventory (unblocks PORTING_PLAN Q12)
Make a table of **every screen and control** in the feeder panel: screen → control type (toggle/slider/picker/button) → label (English string) → backing method/field → range/enum. Include hidden/debug/engineering screens and features gated by firmware version or region.

### P3 – Provisioning (BLE) protocol (nice to have)
The ESP firmware contains the device side of this. Document: BLE service/characteristic UUIDs, the advertising name pattern, and the message framing (header, opcode, length, checksum, encryption?). This helps the firmware agents recognise and **skip** BLE code during decompilation. Also document what the app sends to the device during setup (SSID/PSK, server URL, account ID, time zone, `configKey`?), because those values end up in the ESP's NVS.

### P4 – Device-side identity & transport (helps firmware RE)
- MQTT/WebSocket/HTTP endpoints, topic formats, and what the device publishes. Usually this is only visible in the firmware, but the app may document device-originated report method names.
- `deviceType`, `configModule`, model codes, `uuid`/`cid` formats.

### P5 – Value conversions
All conversion formulas visible in the app, e.g. portions → grams (≈9.1 g/portion per manual?), raw weight → g/oz, battery raw → %, RSSI. Note any constants (e.g. `excessFoodThreshold = 150`).

---

## 4. Search Hints
- String sweeps (all decompiled code + resources + JS bundles + `libapp.so` strings):
  `bypassV2|bypass|method|payload|configModule|deviceType|cid|PPF|R361|feeder|feed|meal|plan|portion|grain|weigh|weight|tare|zero|calib|scale|bowl|eat|remain|lowFood|food|jam|block|lock|childLock|sleep|dnd|volume|voice|record|mealCall|audio|battery|power|adapter|firmware|mcu|ota|upgrade|desiccant`.
- `res/values*/strings.xml` and JS i18n maps: error/notification texts → codes.
- Enum classes / `switch` over error codes; Dart `const` maps; RN `Object.freeze({...})` maps.
- Look for model-specific JSON configs (`*.json` in assets) listing capabilities per model.
- Public references to check: `pyvesync` (Python VeSync client; see if a pet-feeder class exists), Home Assistant VeSync integration, Homebridge VeSync plugins, GitHub searches for `PPF-R361S`, `Pawsync`, `bypassV2 feeder`. Cite any external source used.

---

## 5. Report Structure – `docs/findings/09_apk_findings.md`
1. App identity: package name, version code/name, SHA256 of APK(s), technology stack, where the feeder panel code lives (APK vs remote plugin, plus plugin version).
2. Cloud envelope & transport (endpoints, headers *redacted*, request/response envelopes).
3. **Method dictionary**: one subsection per method, with request/response examples (JSON), field tables, ranges, enums.
4. Settings/UI inventory table (P2) → **proposed Home Assistant entity** per control (platform, name, unit, min/max/step).
5. Schedule model (exact meal record, max meals, weekday bit order, tz handling).
6. Weight/scale model and conversions.
7. Error & notification code table (code → meaning → UI string → suggested HA entity/text).
8. Audio/meal-call format and flow.
9. Firmware/version fields (ESP vs MCU).
10. BLE provisioning summary (if done).
11. Open questions / items needing owner OK (network, rooted device, panel download).

## 6. Machine-Readable Schema – `docs/findings/09_apk_api_schema.json`
```json
{
  "app": {"package": "", "version": "", "panel_source": "apk|remote", "panel_version": ""},
  "envelope": {"endpoint": "", "fields": {}},
  "methods": [
    {
      "name": "setFeedingPlan",
      "direction": "app->device",
      "ui": "Feeding Plan > Save",
      "request": [{"field": "meals", "type": "array", "items": [
        {"field": "hour", "type": "int", "min": 0, "max": 23},
        {"field": "portions", "type": "int", "min": 1, "max": 20},
        {"field": "weekdays", "type": "bitmask", "bits": {"0": "Mon"}}
      ]}],
      "response": [],
      "errors": [{"code": 0, "meaning": "ok"}],
      "evidence": "com/pawsync/...:123",
      "confidence": "CONFIRMED"
    }
  ],
  "error_codes": [{"code": 0, "meaning": "", "ui_text": ""}],
  "settings_inventory": [{"screen": "", "control": "", "label": "", "method": "", "field": "", "range": ""}],
  "conversions": [{"name": "portion_to_grams", "formula": "", "evidence": ""}]
}
```

## 7. Hand-off
When done (or blocked), send the PORTING_PLAN owner/A4 (Protocol RE agent) a summary with:
- the full method/field list (the firmware agent will grep these strings in the ESP image to find the JSON→UART handlers),
- the schedule record format and limits,
- the settings inventory, so Q12 can be closed and the HA entity list (PORTING_PLAN §5.3) finalised.
