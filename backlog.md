# PawSync ESPHome – Detailed Implementation Backlog
**Baseline:** v1.4.4  
**Target:** v1.5.0  
**Document Version:** 1.1  
**Date:** 2026-10-29  
**Repository:** https://github.com/sibero80/pawsync_esphome

---

## 1. Purpose

This document expands every item from the updated v1.5.0 engineering roadmap into concrete, actionable implementation specifications. Each entry contains:

- **Current State**: Exact code references, vulnerabilities, or limitations.
- **Desired End State**: Target architecture and behavior.
- **Detailed Implementation Steps**: File-by-file procedures and code changes.
- **Acceptance Criteria**: Testable requirements for PR verification.
- **Risk / Notes**: Failure modes, edge cases, and design constraints.

Items are grouped across three sequential delivery sprints.

---

## 2. Sprint 1 – Tactical Hotfixes (target: v1.4.5)

Focuses strictly on critical bugfixes, fail-closed validation, and memory/disk leak fixes in the Home Assistant integration Python codebase. Can be deployed immediately without flashing new firmware.

---

### S1-1. Add missing `import tempfile` in `ota_stager.py`

**Current State**  
In `custom_components/pawsync/ota_stager.py` (line 124):
```python
stager_cache_dir = os.path.dirname(self.firmware_path) or tempfile.gettempdir()
```
`tempfile` is referenced but never imported. When Wi-Fi credential injection is requested and the firmware path has no directory component (e.g. relative path in test environments), a fatal `NameError` is raised, crashing the config flow.

**Desired End State**  
The module imports `tempfile` at the top level and path resolution succeeds safely under all conditions.

**Implementation Steps**
1. Open `custom_components/pawsync/ota_stager.py`.
2. Add to top-level imports:
   ```python
   import tempfile
   ```
3. Verify no other unresolved symbols exist in `ota_stager.py`.

**Acceptance Criteria**
- [ ] `python -c "from custom_components.pawsync.ota_stager import PawsyncOtaStager"` succeeds without warning.
- [ ] Stager initialization with a path without a directory does not raise `NameError`.
- [ ] Automated staging unit tests pass.

**Risk / Notes**  
Trivial, zero-risk one-line fix.

---

### S1-2. Remove legacy untokenized stager routes & enforce one-shot downloads

**Current State**  
In `custom_components/pawsync/ota_stager.py` (lines 141–143):
```python
tokenized_path = f"/firmware_{self.token}.bin"
self._app.router.add_get(tokenized_path, self._handle_download)
# Retain standard paths for local development / testing
self._app.router.add_get("/firmware.bin", self._handle_download)
self._app.router.add_get("/pawsync_ota_update.bin", self._handle_download)
```
The stager exposes unauthenticated static routes (`/firmware.bin`, `/pawsync_ota_update.bin`) on the local network alongside the tokenized path. Anyone on the LAN can scrape the customized binary (which contains Wi-Fi credentials) during the staging window. Furthermore, routes remain open until timeout.

**Desired End State**  
Only the single random UUID route (`/firmware_<token>.bin`) is registered. The route is invalidated immediately after the feeder completes downloading (HTTP 200 stream complete).

**Implementation Steps**
1. Remove lines 142–143 (`/firmware.bin` and `/pawsync_ota_update.bin`) from `ota_stager.py`.
2. In `_handle_download()`, after `await response.write_eof()`, trigger an asynchronous shutdown callback `self.hass.async_create_task(self.async_stop())`.
3. Add a 30-second post-transfer safety grace timer before tearing down the HTTP socket to ensure the TCP connection closes gracefully.

**Acceptance Criteria**
- [ ] Requests to `/firmware.bin` and `/pawsync_ota_update.bin` return HTTP 404.
- [ ] Requests to `/firmware_<token>.bin` succeed on first attempt.
- [ ] Stager stops listening immediately after successful transfer.

**Risk / Notes**  
Ensures stock firmware receives clean TCP FIN/ACK before server socket closes.

---

### S1-3. Fail-closed + safe UTF-8 truncation in firmware patcher

**Current State**  
In `custom_components/pawsync/firmware_patcher.py`:
- Strings are truncated using raw character slicing `[:MAX_SSID_LEN]` (32) and `[:MAX_PASS_LEN]` (64). If an SSID is exactly 32 bytes, no null terminator (`\0`) is preserved, causing buffer overflow in ESP-IDF's Wi-Fi stack.
- Multi-byte UTF-8 sequences can be split across boundary slices, resulting in invalid UTF-8 and Wi-Fi association failure.
- If placeholders are missing or an exception occurs, the function logs a warning and returns the **unpatched** binary (fails open), causing the feeder to flash stock defaults and drop off the network.

**Desired End State**  
- SSIDs are safely truncated to a maximum of 31 bytes + null terminator (`\0`).
- Passwords are safely truncated to a maximum of 63 bytes + null terminator (`\0`).
- Multi-byte UTF-8 sequences are never split.
- Missing placeholders or patching errors immediately raise a dedicated exception `FirmwarePatchError` and abort the staging process (fails closed).

**Implementation Steps**
1. In `firmware_patcher.py`, implement `safe_truncate_utf8`:
   ```python
   def safe_truncate_utf8(text: str, max_bytes: int) -> bytes:
       """Truncate string to max_bytes preserving UTF-8 integrity and adding null termination."""
       if not text:
           return b"\x00" * (max_bytes + 1)
       encoded = text.encode("utf-8")
       while len(encoded) > max_bytes:
           text = text[:-1]
           encoded = text.encode("utf-8")
       return encoded.ljust(max_bytes + 1, b"\x00")
   ```
2. Replace raw slicing in `patch_raw_esp32_credentials()`:
   ```python
   ssid_bytes = safe_truncate_utf8(ssid, 31)
   pass_bytes = safe_truncate_utf8(password or "", 63)
   ```
3. Define `class FirmwarePatchError(Exception): pass`.
4. Replace placeholder missing warnings with `raise FirmwarePatchError("Required placeholders not found in firmware binary")`.
5. In `ota_stager.py` and `config_flow.py`, catch `FirmwarePatchError` and present a descriptive error message to the user.

**Acceptance Criteria**
- [ ] 32+ character SSIDs are truncated to 31 bytes plus `\0`.
- [ ] International SSIDs (e.g. `CaféNet⚡`) are never split mid-character.
- [ ] Missing placeholder buffers immediately abort staging with user notification.
- [ ] Patched image boot checksum and SHA-256 recalculate correctly.

**Risk / Notes**  
Failing closed prevents bricking or orphaned feeder states.

---

### S1-4. Guaranteed cleanup of `pawsync_ota_customized.bin` across all exit paths

**Current State**  
When credentials are injected, `prepare_customized_firmware_file()` writes `pawsync_ota_customized.bin` to the integration storage directory. If an OTA fails, times out, HA restarts, or the config entry is unloaded, the customized binary (with plaintext Wi-Fi credentials) remains indefinitely on disk.

**Desired End State**  
The customized binary is strictly temporary and is deleted under all exit paths: success, failure, timeout, and config-entry unload.

**Implementation Steps**
1. In `PawsyncOtaStager`, track `self._customized_path: str | None = None`.
2. In `async_stop()`:
   ```python
   if self._customized_path and os.path.exists(self._customized_path):
       try:
           os.remove(self._customized_path)
           _LOGGER.debug("Removed temporary customized firmware: %s", self._customized_path)
       except OSError as err:
           _LOGGER.warning("Could not delete customized firmware %s: %s", self._customized_path, err)
       finally:
           self._customized_path = None
   ```
3. Wrap download execution in a `try...finally:` block that ensures `async_stop()` runs.
4. In `config_flow.py` `_async_convert_feeder_task()`, add a `finally:` block ensuring `stager.async_stop()` is called if conversion terminates unexpectedly.
5. In `__init__.py` `async_unload_entry()`, clean up any orphaned customized files matching `pawsync_ota_customized_*.bin`.

**Acceptance Criteria**
- [ ] After successful OTA transfer, `pawsync_ota_customized.bin` is deleted.
- [ ] After an aborted/timed-out transfer, `pawsync_ota_customized.bin` is deleted.
- [ ] The base precompiled template `pawsync_ota_update.bin` is never deleted.

**Risk / Notes**  
Ensures sensitive Wi-Fi credentials do not linger on the host filesystem.

---

### S1-5. Move backup trigger out of `sensor.async_update`

**Current State**  
In `custom_components/pawsync/sensor.py` (lines 160–163):
```python
if not self._backup_in_progress and self._mac and host:
    self._backup_in_progress = True
    self.hass.async_create_task(self._async_trigger_backup(host, self._mac))
```
Factory backup harvesting is triggered from a state-polling method (`async_update`). In Home Assistant architecture, state polling must be purely read-only and idempotent; triggering background I/O tasks from sensors creates race conditions and repeated execution.

**Desired End State**  
Sensor polling is strictly read-only. Backup harvesting is triggered solely from `async_setup_entry` during post-adoption setup or via a dedicated service call.

**Implementation Steps**
1. Remove `_async_trigger_backup` call from `sensor.py`.
2. Ensure `async_setup_entry` in `__init__.py` schedules `async_ensure_factory_backup()` once on integration startup.
3. Expose a Home Assistant service `pawsync.trigger_backup` allowing manual on-demand triggers.
4. Keep `PawSyncBackupStatusSensor` reporting status based solely on filesystem state.

**Acceptance Criteria**
- [ ] Regular sensor updates perform zero network or disk write operations.
- [ ] Automated backup still executes reliably once after initial conversion.
- [ ] `pawsync.trigger_backup` service triggers an on-demand backup.

**Risk / Notes**  
Low-risk architectural clean-up.

---

## 3. Sprint 2 – Device-Specific Secrets & Pre-Flash Cloud Backup (target: v1.5.0-beta)

Establishes the cryptographic framework: eliminates shared transition secrets, enables multi-device coexistence with MAC-scoped secrets, standardizes fallback AP behavior, and captures full cloud settings before flashing.

---

### S2-1. Unique per-device Noise PSK (eliminate `TRANSITION_NOISE_PSK`)

**Current State**  
`const.py` hardcodes:
```python
TRANSITION_NOISE_PSK = "OjRSzAh3ADVkNjmBs5+K6GnOY0tGoSqlniJvsmolVeE="
DEFAULT_NOISE_PSK = TRANSITION_NOISE_PSK
```
All converted feeders share this static key during transition. If two feeders are adopted or reset, an adoption collision and authentication mismatch occurs (as experienced in v1.4.4 with Feeder 2).

**Desired End State**  
- Every feeder receives a unique, cryptographically random 32-byte Noise PSK (`base64.b64encode(secrets.token_bytes(32)).decode("ascii")`) generated at onboarding time.
- The precompiled transition image contains a 44-byte base64 placeholder:
  `PLACEHOLDER_NOISE_PSK_KEY_44B________________`
- The stager dynamically byte-patches the unique key into the binary before flashing.
- `TRANSITION_NOISE_PSK` is completely removed from the codebase.

**Implementation Steps**
1. In `pawsync_ota` repository, define the 44-byte placeholder in `pawsync.yaml`:
   ```yaml
   api:
     encryption:
       key: "PLACEHOLDER_NOISE_PSK_KEY_44B________________"
   ```
2. In `firmware_patcher.py`, implement `patch_noise_psk(raw_bin, noise_psk_b64)`.
3. In `config_flow.py`, generate a unique key per feeder during onboarding.
4. Write the key into `/config/esphome/secrets.yaml` (see S2-4).
5. Remove all fallback loops referencing `TRANSITION_NOISE_PSK` in `esphome_provisioner.py`.

**Acceptance Criteria**
- [ ] No two feeders ever receive the same Noise PSK.
- [ ] `TRANSITION_NOISE_PSK` is removed from `const.py`.
- [ ] Feeder adopts cleanly using its unique key.
- [ ] API connections presenting any other key are rejected.

**Risk / Notes**  
Critical path for multi-device support. Eliminates cross-device authentication collisions.

---

### S2-2. Unique per-device OTA password

**Current State**  
In `pawsync.yaml` (lines 154–156):
```yaml
ota:
  - platform: esphome
```
Port 3232 is unauthenticated. Any device on the LAN can push arbitrary firmware.

**Desired End State**  
Every device is flashed with a unique, cryptographically random 16-character alphanumeric OTA password stored in `secrets.yaml` and referenced via `!secret`.

**Implementation Steps**
1. In `pawsync_ota`, add a 32-byte placeholder in `pawsync.yaml`:
   ```yaml
   ota:
     - platform: esphome
       password: "PLACEHOLDER_OTA_PASSWORD_32B_____"
   ```
2. In `firmware_patcher.py`, implement `patch_ota_password(raw_bin, ota_password)`.
3. Generate a 16-char random alphanumeric password in `config_flow.py`.
4. Record `feeder_<sanitized_mac>_ota_password` in `secrets.yaml`.
5. Update `generate_esphome_yaml()` to specify `password: !secret feeder_<sanitized_mac>_ota_password`.

**Acceptance Criteria**
- [ ] ESPHome OTA port 3232 requires authentication.
- [ ] Password is unique per feeder.
- [ ] Compiling through ESPHome dashboard or Home Assistant update entity succeeds using `!secret`.

**Risk / Notes**  
Secures the network firmware update channel against unauthorized flashing.

---

### S2-3. Fallback SoftAP standardization (Option C: `pawsync1234`)

**Current State**  
`pawsync.yaml` defines a fallback AP with no password. If primary Wi-Fi is unavailable, an open access point is broadcast. Deriving a password dynamically from the SSID violates IEEE 802.11 standards if the SSID is under 8 characters, causing ESP-IDF boot crashes.

**Desired End State**  
Implement **Option C**:
- Fallback SSID: `Pawsync-Feeder-Fallback`
- Fallback Password: `pawsync1234`
- Port 6053 ESPHome Native API remains fully secured by the unique 32-byte per-device Noise PSK.

**Implementation Steps**
1. In `pawsync.yaml`:
   ```yaml
   wifi:
     ap:
       ssid: "Pawsync-Feeder-Fallback"
       password: "pawsync1234"
   ```
2. Document the standard recovery passphrase in the user manual and README.
3. Validate that connecting to the fallback AP only exposes the captive portal for Wi-Fi reconfiguration and cannot actuate the feeder without the Noise PSK.

**Acceptance Criteria**
- [ ] Fallback AP is secured with WPA2 passphrase `pawsync1234` (8+ chars, compliant with 802.11i).
- [ ] Feeder never crashes on boot regardless of primary SSID length.
- [ ] Captive portal functions for network reconfiguration.

**Risk / Notes**  
Eliminates dynamic derivation crashes while maintaining a documented, deterministic recovery path.

---

### S2-4. Write all secrets to `/config/esphome/secrets.yaml` with mode 0600 & MAC prefixing

**Current State**  
Wi-Fi credentials and configuration parameters are written directly in plaintext into `/config/esphome/pawsync-feeder.yaml`. In multi-feeder setups, generic key names collide.

**Desired End State**  
All sensitive credentials reside exclusively in `/config/esphome/secrets.yaml` using MAC-scoped keys. The file is created/updated with POSIX permissions `0600` (`rw-------`). The device YAML contains only `!secret` references.

**Implementation Steps**
1. In `esphome_provisioner.py`, implement `async_write_feeder_secrets(hass, mac, secrets_dict)`:
   ```yaml
   feeder_<mac>_wifi_ssid: "..."
   feeder_<mac>_wifi_password: "..."
   feeder_<mac>_noise_psk: "..."
   feeder_<mac>_ota_password: "..."
   ```
2. Use YAML safe loading and atomic file writing (write to temp file, `os.chmod(0o600)`, atomic rename) to prevent race conditions.
3. Non-destructive merge: retain all existing user secrets in `secrets.yaml`.
4. Update `generate_esphome_yaml()` to emit only `!secret` references.

**Acceptance Criteria**
- [ ] `/config/esphome/secrets.yaml` is written with mode `0600`.
- [ ] Zero plaintext credentials in `/config/esphome/pawsync-feeder-*.yaml`.
- [ ] Multiple feeders coexist without key collisions.
- [ ] Pre-existing secrets from other ESPHome devices are preserved intact.

**Risk / Notes**  
Ensures secrets isolation across multiple feeder instances.

---

### S2-5. Pre-flash cloud settings harvesting & backup (`cloud_backup_<mac>.json`)

**Current State**  
During onboarding, `config_flow.py` only fetches basic device summaries for selection. All rich cloud configuration—meal schedules, portion calibration (`singleWeight_g`), smart feeding modes, and hopper surplus—is discarded upon conversion, forcing users to re-enter all settings manually.

**Desired End State**  
Before staging the transition binary, the integration queries the PawSync cloud API for the complete device configuration and feeding plans. It serializes this data into a structured JSON backup (`/config/.storage/pawsync/cloud_backup_<mac>.json`) and caches it in config-entry data, paving the way for zero-loss migration.

**Implementation Steps**
1. In `custom_components/pawsync/pawsync_api.py`, add `async_harvest_feeder_profile(device_id)`:
   - Query `/pet/api/deviceManaged/v1/deviceList4Pet` or `getDeviceDetail` to obtain:
     - `deviceProp.singleWeight_g` (kibble grams per portion calibration)
     - `deviceProp.intelligentFeedingSwitch` (leftover deduction toggle)
     - `deviceProp.slowFeedSwitch` (slow dispensing toggle)
     - `deviceProp.sleepMode` (night mode quiet hours)
     - `deviceProp.petFood.bucketSurplus` (hopper remaining food weight)
   - Query `/pet/api/deviceManaged/v1/getFeedingPlanList` and `/pet/api/deviceManaged/v1/getFeedingPlanDetail` for the full meal schedule:
     - `timeSec` (seconds past midnight, e.g. 28800 for 08:00)
     - `weight` (target meal grams)
     - `repeat` (7-day bitmask of active weekdays)
2. In `config_flow.py` `_async_convert_feeder_task()`, execute harvesting before calling `stager.async_start()`.
3. In `backup_manager.py`, implement `save_cloud_backup(mac, profile_dict)` writing to:
   `/config/.storage/pawsync/cloud_backup_<sanitized_mac>.json`.
4. Store `cloud_settings` in `entry.data` for post-adoption restoration.
5. If the cloud call fails or times out, log a warning and proceed gracefully with standard defaults (fail-safe, non-blocking).

**Acceptance Criteria**
- [ ] Cloud profile and full meal plans are fetched and validated before OTA transfer begins.
- [ ] Persistent backup file `cloud_backup_<mac>.json` is saved on disk.
- [ ] If cloud harvesting fails, the conversion still completes safely using default schedules.

**Risk / Notes**  
Provides a complete, reproducible snapshot of pet care settings prior to severing cloud connectivity.

---

### S2-6. Binary digest pinning (`firmware_downloader.py`)

**Current State**  
`firmware_downloader.py` downloads release binaries from GitHub and only verifies file size and container magic bytes. If a release binary is tampered with or corrupted during CDN delivery, it could be staged.

**Desired End State**  
Only binaries matching a hardcoded SHA-256 allow-list for the current integration release are accepted.

**Implementation Steps**
1. In `firmware_downloader.py`, define:
   ```python
   EXPECTED_FIRMWARE_DIGESTS = {
       "1.5.0": "sha256:4a8b7e2c91d0f5...",
   }
   ```
2. Compute SHA-256 after download and compare against the dictionary.
3. Reject mismatches with `HomeAssistantError("Firmware SHA-256 digest verification failed")`.
4. Automate hash updating in release CI workflows.

**Acceptance Criteria**
- [ ] Binaries matching the expected SHA-256 hash are accepted.
- [ ] Corrupted or mismatched binaries are rejected before saving.
- [ ] CI validates release assets against the hash map.

**Risk / Notes**  
Guarantees firmware integrity and supply chain security.

---

## 4. Sprint 3 – Reliability, UX & Architecture (target: v1.5.0 final)

Focuses on post-adoption automated settings restoration, recovery workflows, modular C++ refactoring, and integration testing.

---

### S3-1. Failed-conversion recovery step (`async_step_recovery`)

**Current State**  
If the feeder downloads the transition image but fails to connect to Wi-Fi or cannot be discovered over mDNS, the config flow times out without actionable guidance, leaving the user in an ambiguous state.

**Desired End State**  
A dedicated interactive recovery step (`async_step_recovery`) provides clear options:
1. Retry auto-adoption.
2. Enter manual IP address (for split-VLAN / mDNS reflection environments).
3. Connect to fallback SoftAP (`Pawsync-Feeder-Fallback` / `pawsync1234`).
The flow preserves generated credentials so retries do not regenerate mismatched keys.

**Implementation Steps**
1. In `config_flow.py`, if `async_auto_adopt_esphome()` returns `False` or times out, redirect to `async_step_recovery`.
2. Present a recovery form offering:
   - Option A: "Retry discovery"
   - Option B: "Specify device IP address manually"
   - Option C: "Troubleshooting instructions" (points to fallback SoftAP details).
3. If manual IP is provided, immediately attempt ESPHome Native API connection with the previously generated `feeder_noise_psk`.

**Acceptance Criteria**
- [ ] Flow never terminates in a silent failure or unhandled exception.
- [ ] Manual IP adoption works seamlessly if mDNS discovery fails.
- [ ] User can retry without restarting the entire onboarding flow.

**Risk / Notes**  
Significantly reduces support overhead and handles complex network topologies.

---

### S3-2. Automated post-adoption cloud settings restoration & replay engine

**Current State**  
After conversion, the feeder boots with default NVS settings: generic meal schedule (`08:00 (2p), 18:00 (3p)`), default portion weight (`8.0g`), and all safety toggles disabled. Users must manually re-configure everything.

**Desired End State**  
Upon successful ESPHome adoption, the integration automatically replays the harvested cloud settings (from S2-5) into ESPHome entities and services:
- Programs the exact feeding schedule via `esphome.<feeder>_set_meal_schedule`.
- Sets kibble density via `number.<feeder>_grams_per_portion_kibble_calibration`.
- Sets feature toggles: Intelligent Feeding, Slow Feed, and Sleep Mode.
- Sets hopper surplus weight via `number.<feeder>_tank_refill_weight`.
- Exposes service `pawsync.restore_cloud_backup` to re-apply settings at any time.

**Implementation Steps**
1. Create `custom_components/pawsync/restore_manager.py`:
   ```python
   async def async_restore_cloud_settings(hass: HomeAssistant, entry: ConfigEntry) -> bool:
       """Replay harvested cloud configuration into adopted ESPHome feeder."""
   ```
2. Meal plan translation logic:
   - Convert `timeSec` to `HH:MM` time.
   - Calculate portion count: $\text{portions} = \text{round}(\text{meal\_weight\_g} / \text{singleWeight\_g})$.
   - Convert `repeat` integer to active day bitmask.
   - Call service `esphome.<feeder>_set_meal_schedule` for each meal index (1–14).
3. Entity state alignment:
   - Set `number.<feeder>_grams_per_portion_kibble_calibration` to `singleWeight_g`.
   - Set `switch.<feeder>_intelligent_feeding_leftover_deduction` to match `intelligentFeedingSwitch`.
   - Set `switch.<feeder>_slow_feed_mode` to match `slowFeedSwitch`.
   - Set `number.<feeder>_tank_refill_volume` based on `bucketSurplus`.
4. In `__init__.py` `async_setup_entry()`, run restoration automatically once after initial adoption.
5. Register service `pawsync.restore_cloud_backup` in `services.py`.

**Acceptance Criteria**
- [ ] Within 30 seconds of adoption, the pet's original meal schedule is live on the feeder.
- [ ] Kibble density and feature switches match previous cloud settings.
- [ ] `pawsync.restore_cloud_backup` successfully restores settings on demand from backup JSON.

**Risk / Notes**  
Achieves a true **100% "Zero-Loss Migration"** experience for the end user.

---

### S3-3. Extract backup HTTP server from monolithic C++ (`ppf_r361s_backup_server.cpp`)

**Current State**  
`components/ppf_r361s/ppf_r361s.cpp` is a 2,130-line monolithic file. Lines 1893–1940 embed the ESP-IDF `httpd` streaming server for partition backups (`/export_stock_bin`, `/export_calibration`) directly inside the main component class.

**Desired End State**  
Extract the backup HTTP server into a dedicated translation unit (`ppf_r361s_backup_server.h` / `.cpp`). The main component interacts via a clean lifecycle interface (`start_backup_server()`, `stop_backup_server()`).

**Implementation Steps**
1. Create `components/ppf_r361s/ppf_r361s_backup_server.h` and `.cpp`.
2. Move `http_export_status_handler`, `http_export_stock_bin_handler`, and `http_export_calibration_handler` into the new unit.
3. Encapsulate socket configuration, URI registration, and buffer streaming.
4. Provide clean start/stop methods on the backup server object.
5. Verify C++ compilation under ESP-IDF within ESPHome build pipeline.

**Acceptance Criteria**
- [ ] `ppf_r361s.cpp` is reduced by ~250 lines.
- [ ] Factory stock partition (`ota_1`) and calibration downloads continue working reliably.
- [ ] Unit compiles cleanly without warnings.

**Risk / Notes**  
Prerequisite for adding any further transport security or automated shutdown to port 8088.

---

### S3-4. Post-patch structural validation (ESP32 image header `0xE9` & segment offsets)

**Current State**  
`firmware_patcher.py` recalculates checksums and SHA-256 digests but does not parse the internal ESP-IDF image structure. If placeholder replacement accidentally corrupts segment offsets, the binary is still wrapped and flashed, causing a bootloader crash.

**Desired End State**  
Before wrapping the binary in the VeSync container, the patcher parses the ESP32 image header:
- Validates magic byte `0xE9` at offset 0.
- Reads segment count and validates that segment headers point to valid memory ranges.
- Confirms that zero unpatched placeholder buffers remain in the binary.

**Implementation Steps**
1. In `firmware_patcher.py`, implement `validate_esp32_image_structure(image_bytes: bytes) -> bool`.
2. Check `image_bytes[0] == 0xE9`.
3. Parse segment table header (offsets, lengths).
4. Assert `image_bytes.find(PLACEHOLDER_NOISE_PSK) == -1` and `image_bytes.find(SSID_PLACEHOLDER) == -1`.
5. If invalid, raise `FirmwarePatchError` and abort staging.

**Acceptance Criteria**
- [ ] Valid patched images pass structural validation.
- [ ] An image with corrupted segment tables or leftover placeholders is rejected.
- [ ] No unbootable binary is ever served to the feeder.

**Risk / Notes**  
Hardens anti-bricking guarantees.

---

### S3-5. Integration test suite for the secrets framework (synthetic binaries)

**Current State**  
`tests/test_firmware_patcher.py` contains hardcoded paths to local development binaries (`/root/pawsync_ota/pawsync_ota_update.bin`), causing tests to fail in CI environments or clean checkouts.

**Desired End State**  
All tests generate synthetic ESP32 test containers in-memory with valid `0xE9` headers, placeholders, and checksums. Comprehensive test suite runs in GitHub Actions CI without external dependencies.

**Implementation Steps**
1. Create `tests/fixtures/synthetic_firmware.py` to generate minimal mock ESP32 binaries containing placeholders.
2. Add test cases:
   - Unique Noise PSK patching and verification.
   - Null-terminated UTF-8 safe SSID/password truncation.
   - `secrets.yaml` creation, non-destructive merging, and `0600` permissions.
   - VeSync container encryption/decryption round-trip.
   - Guaranteed deletion of temporary customized files.
3. Integrate into GitHub Actions `.github/workflows/test.yml`.

**Acceptance Criteria**
- [ ] 100% of integration and patcher tests pass in GitHub Actions CI.
- [ ] Zero reliance on local hardcoded filesystem paths.

**Risk / Notes**  
Establishes reliable regression prevention for all future pull requests.

---

### S3-6. Modular split of monolithic `ppf_r361s.cpp`

**Current State**  
`components/ppf_r361s/ppf_r361s.cpp` is 2,130 lines long and handles UART protocol framing, food scheduling, weight calibration, eating detection, hardware sensors, and component lifecycle in a single translation unit.

**Desired End State**  
Split the component into cohesive domain modules:
- `ppf_r361s_uart.cpp`: Byte framing, checksums, command transmission/receipt.
- `ppf_r361s_schedule.cpp`: Meal plan evaluation, RTC sync, NVS schedule persistence.
- `ppf_r361s_sensors.cpp`: Load cell calibration, bowl tare, hopper level, desiccant timers.
- `ppf_r361s_backup_server.cpp`: Factory partition streaming (from S3-3).
- `ppf_r361s.cpp`: Core ESPHome component orchestration and lifecycle.

**Implementation Steps**
1. Create separate header and source files for each domain.
2. Move state variables and methods into domain classes or namespaces.
3. Update `components/ppf_r361s/__init__.py` to compile all translation units.
4. Verify complete build in ESPHome docker build container.

**Acceptance Criteria**
- [ ] All modules compile independently without circular dependencies.
- [ ] Component functionality, UART timing, and entity behaviors remain identical.
- [ ] Main `ppf_r361s.cpp` is under 400 lines of orchestration logic.

**Risk / Notes**  
Major architectural maintenance improvement; makes code review manageable.

---

### S3-7. Diagnostic sensors for free heap space & lwIP sockets

**Current State**  
The ESP32-C3 runs with limited RAM. Heavy operations (e.g. concurrent HTTP backup streaming, mDNS lookups, and Native API traffic) can stress heap and lwIP socket allocations without visible telemetry.

**Desired End State**  
Expose diagnostic sensors in `pawsync.yaml` for real-time memory and socket visibility:
- `sensor.pawsync_feeder_free_heap` (bytes)
- `sensor.pawsync_feeder_free_lwip_sockets` (count)

**Implementation Steps**
1. In `pawsync.yaml`, add ESPHome debug/internal sensors:
   ```yaml
   sensor:
     - platform: debug
       free:
         name: "Free Heap"
         entity_category: diagnostic
       block:
         name: "Max Free Block"
         entity_category: diagnostic
   ```
2. In C++ component, report active lwIP socket count via diagnostic entity.

**Acceptance Criteria**
- [ ] Home Assistant displays diagnostic entities for free heap and memory blocks.
- [ ] Memory leaks or buffer exhaustion can be diagnosed directly from Home Assistant.

**Risk / Notes**  
Zero overhead; standard ESPHome diagnostic functionality.

---

### S3-8. Publish updated `SECURITY.md`

**Current State**  
No formal `SECURITY.md` exists detailing the threat model, network boundaries, or reporting procedures.

**Desired End State**  
A comprehensive `SECURITY.md` is published in both repositories documenting:
- The threat model (LAN-only attack surface, physical access, supply chain).
- Explanation of the transient transition window and why Phase 1 requires dynamic in-memory patching.
- SoftAP Option C policy (`pawsync1234`) and why Native API Noise PSK protects control surfaces.
- Clarification that the `"Levoit"` AES container key provides integrity validation for the stock bootloader rather than cryptographic privacy against a local network observer.
- Vulnerability disclosure and reporting guidelines.

**Implementation Steps**
1. Draft `SECURITY.md` covering the above topics.
2. Commit to root of `pawsync_esphome` and `pawsync_ota`.

**Acceptance Criteria**
- [ ] `SECURITY.md` published and referenced in project documentation.

**Risk / Notes**  
Pure documentation; ensures open-source security transparency.

---

## 5. Summary Matrix & Sprint Allocation

| Item ID | Proposal Name | Sprint | Domain | Priority | Implementation Complexity |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **S1-1** | Add missing `import tempfile` | Sprint 1 | Bugfix | **P0** | Trivial |
| **S1-2** | Remove untokenized stager routes | Sprint 1 | Security | **P1** | Low |
| **S1-3** | Fail-closed + safe UTF-8 truncation | Sprint 1 | Reliability | **P0** | Medium |
| **S1-4** | Guaranteed cleanup of `pawsync_ota_customized.bin` | Sprint 1 | Privacy | **P1** | Low |
| **S1-5** | Move backup trigger out of `sensor.async_update` | Sprint 1 | Architecture | **P2** | Low |
| **S2-1** | Unique per-device Noise PSK | Sprint 2 | Security | **P0** | High |
| **S2-2** | Unique per-device OTA password | Sprint 2 | Security | **P1** | Medium |
| **S2-3** | Fallback SoftAP standardization (Option C) | Sprint 2 | Usability | **P1** | Low |
| **S2-4** | Write secrets to `secrets.yaml` (Mode 0600) | Sprint 2 | Security | **P0** | Medium |
| **S2-5** | Pre-flash cloud settings harvesting & backup | Sprint 2 | Feature (UX) | **P0** | Medium |
| **S2-6** | Binary digest pinning (SHA-256) | Sprint 2 | Integrity | **P1** | Low-Med |
| **S3-1** | Failed-conversion recovery step | Sprint 3 | UX | **P1** | Medium |
| **S3-2** | Automated post-adoption settings restoration | Sprint 3 | Feature (UX) | **P0** | High |
| **S3-3** | Extract backup HTTP server (C++) | Sprint 3 | Architecture | **P0** | Medium |
| **S3-4** | Post-patch structural image validation | Sprint 3 | Safety | **P1** | Medium |
| **S3-5** | Synthetic CI integration test suite | Sprint 3 | Quality | **P1** | High |
| **S3-6** | Modular split of `ppf_r361s.cpp` | Sprint 3 | Maintainability | **P1** | High |
| **S3-7** | Diagnostic sensors for free heap & sockets | Sprint 3 | Diagnostics | **P2** | Low |
| **S3-8** | Publish updated `SECURITY.md` | Sprint 3 | Compliance | **P2** | Low |

---

## 6. Suggested Release Cadence

| Release | Sprint Scope | Key Deliverables | Target |
| :--- | :--- | :--- | :--- |
| **v1.4.5** | Sprint 1 only | Python hotfixes: `tempfile` fix, fail-closed patcher, route protection, file cleanup. | Immediate |
| **v1.5.0-beta** | Sprint 2 | Device-specific secrets framework, `secrets.yaml` integration, pre-flash cloud backup. | Next |
| **v1.5.0** | Sprint 3 | Automated settings restoration (zero-loss migration), C++ modularization, recovery UI. | Final |

---

*End of implementation backlog v1.1*
