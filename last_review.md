# PawSync ESPHome v1.4.3: Consolidated Review (Claude findings cross-checked against Grok)

Repository: github.com/sibero80/pawsync\_esphome | Version reviewed: v1.4.3 (29 Oct 2026) | Prepared 29 Oct 2026

## 1. Basis and how to read this

**Claude's evidence:** the diffs for v1.2.1, v1.3.1, v1.4.0, v1.4.2 and v1.4.3, the release list, and earlier README, YAML and partition views (those cached views were stale, showing v1.1.1). I could not open the Python and C++ source files directly, and GitHub blocked the commit-list and compare pages.

**Grok's evidence:** its review quotes ota\_stager.py, esphome\_provisioner.py and the C++ component, so it appears to have read more of the v1.4.3 source than I did. I have not been able to verify those quotes.

Every item below carries a tag:

- **\[Confirmed\]** seen in a diff I read.
- **\[Reported\]** claimed by Grok, plausible and consistent with what I saw, not independently seen.
- **\[Unverified\]** claimed by one reviewer only and needs a quick check (section 6 lists the checks).
- **\[Disputed\]** the two reviews disagree.

## 2. Bottom line

Grok concludes that v1.4.3 has closed almost all of the original high-severity findings and that what remains is subtle. The diffs do not support that. Version 1.3.1 removed the OTA password and the fallback-AP password from pawsync.yaml and made a fixed, publicly committed Noise PSK the default again. Together with the points below, a converted feeder currently has effectively no device-level authentication on the LAN, and the onboarding path leaks the user's Wi-Fi password in several ways. The project has improved in real ways (backups, executor jobs, releases, token non-persistence), but the top of the priority list is still security, not polish.

## 3. Consolidated findings

### High

**H1. OTA password and fallback-AP password removed in v1.3.1 \[Confirmed, Claude only\].** The v1.3.1 diff deletes `password: !secret ota_password` and `password: !secret wifi_ap_password`. The fallback AP becomes an open network and OTA accepts any pusher. Grok did not mention this, and it undoes an earlier fix. Restore both, and have the patcher inject per-device values (see H2).

**H2. One public Noise PSK for every converted feeder \[Confirmed; scope Disputed\].** `TRANSITION_NOISE_PSK` is hard-coded in const.py, is the default (`DEFAULT_NOISE_PSK`), is the fallback in `async_setup_entry` and in the adoption retry, and the same value was committed to secrets.yaml.example in v1.2.1. Grok calls it intentional and scoped to a short conversion window. I disagree: nothing I saw rotates the key after adoption, so it persists on the device indefinitely, and the repository publishes it. Anyone on the LAN can speak the native API to such a device (feed, rollback, services). Both reviews agree on the fix: rotate to a unique key right after adoption and never fall back to the transition key. The firmware patcher already substitutes Wi-Fi placeholders in the binary, so per-device PSK and OTA-password placeholders are a natural extension. Runtime key setting through the native API is another route (check it works on the declared minimum ESPHome version).

**H3. Legacy untokenized stager paths \[Reported\].** Grok quotes `/firmware.bin` and `/pawsync_ota_update.bin` still registered on the staging server alongside the tokenized URL. If so, the token adds nothing, because any LAN host can fetch the image during the 10-minute window. Since the served image now contains the user's Wi-Fi credentials (H4), this is a direct credential exposure. Remove the legacy routes or put them behind a debug flag, and invalidate the token after one successful download.

**H4. Wi-Fi credentials exposed at several points \[Confirmed, plus Reported\].**

- The password is patched into the firmware payload and served over plain HTTP on port 8000. Correction to Grok's framing: the patcher encrypts only the 128-byte container header (AES-CBC, key and IV both MD5 of the string Levoit). The firmware body, with the credentials in it, is not encrypted at all, so the outer container gives no confidentiality against a LAN observer.
- The patched image is written to disk as pawsync\_ota\_customized.bin in the cache directory. I saw no cleanup. Delete it after the flash.
- Grok reports that esphome\_provisioner.py writes the SSID and password in cleartext into a generated YAML under /config/esphome. This is consistent with the flow logging an auto-provision step but I did not see the code. Use `!secret` references instead.

**H5. Patcher fails open and truncates silently \[Confirmed, Claude only\].** If patching raises, or the placeholders are missing, `prepare_customized_firmware_file` logs a warning and returns the unpatched binary, and the OTA still proceeds; the feeder then reboots with no Wi-Fi credentials. Inputs are cut with `[:32]` and `[:64]`, which leaves no NUL terminator for a 32-byte SSID or a 64-character hex key and can split multibyte characters. Validate before triggering the cloud OTA and abort on any failure.

**H6. On-device backup HTTP server on port 8088 \[server Confirmed; lack of auth Unverified\].** The diff shows `start_backup_http_server` with port 8088 and a control-port change. Grok says it is unauthenticated and can export the stock partition and calibration data. Require a one-time token or the PSK, bind narrowly, and shut the server down after a successful backup or a short timeout.

**H7. Possible NameError on tempfile in ota\_stager.py \[Unverified\].** Grok reports that `tempfile.gettempdir()` is used without an import. The v1.4.0 diff adds that call and shows no import hunk at the top of the file, which supports the suspicion but does not prove it. This is a one-line check (section 6).

### Medium

**M1. Config-flow error handling \[Confirmed, Claude only\].** The `ota_error` step creates the feeder entry anyway, so a failed conversion yields a configured feeder. The return value of `async_auto_adopt_esphome` (a bool) is ignored, so a timeout can look like success. `self._cloud_auth[CONF_TOKEN]` replaced a guarded `.get()`, so a missing token raises KeyError.

**M2. Task lifecycle and no rollback path \[Confirmed in part, both\].** Fire-and-forget `hass.async_create_task` calls are not cancelled when the flow is aborted or the entry is removed. The pipeline (stager, cloud relay, adoption polling, backup) has no transactional cleanup and no guided recovery when the device never reappears or reappears with the wrong key beyond try again or UART.

**M3. Adoption polling \[Confirmed numbers; Grok partly right\].** The provisioner default is now 120 attempts at 3 s (6 minutes); the config flow passes 40 (2 minutes). It also drives another integration's flow by flow id and step id, which is fragile across HA versions. Prefer the normal zeroconf discovery path with a bounded wait.

**M4. CI sanitization is a no-op \[Confirmed, Claude only\].** The v1.2.1 workflow replaces the placeholder `Generated_Base64_Key`, but the same commit replaced that placeholder in secrets.yaml.example with a literal key. Release binaries are compiled from the example secrets, so any secret the YAML references is baked into a public binary with its example value.

**M5. Post-patch validation \[Both\].** The patcher recomputes the segment XOR checksum and the SHA-256 but never re-parses the result. Add a post-patch check (parse segments, verify digest, confirm the placeholders are gone) and run it in CI with a real binary.

**M6. External transition-binary repository \[Reported, new to me\].** Grok says the transition binary is now downloaded from a separate pawsync\_ota repository. Pin an expected SHA-256 inside the integration, document the offline fallback, and handle rate limits and deleted releases.

**M7. Sensor side effects \[Confirmed, Claude only\].** The backup status sensor's `async_update` starts a background factory-backup download. Polling methods should not launch long operations; trigger it from setup or a service.

**M8. Test quality \[Confirmed, Claude only\].** The end-to-end patcher test reads `/root/pawsync_ota/pawsync_ota_update.bin` and skips in CI. Config-flow tests use hand-written stubs rather than pytest-homeassistant-custom-component. Commits are authored as root.

**M9. Backup lifecycle \[Both\].** Backups under /config/pawsync\_backups use 0600 permissions (good) but have no documented retention, cleanup or encryption at rest, and they travel inside HA backups.

**M10. C++ component size \[Reported; plausible\].** The backup server sits near line 1892 of ppf\_r361s.cpp, so the file is at least that long. Protocol, scheduler, tank model, calibration, eating detection, backup server and safety cutoff share one class. Split it into testable units.

**M11. Device resource pressure \[Unverified\].** Native API, OTA, captive portal, the 8088 server and audio compete for sockets and RAM on an ESP32-C3. Grok says the socket limit was raised to 16. Add a heap and free-socket diagnostic, and a CI size check against the 1.25 MB app slot.

**M12. Safety cutoff timing \[Unverified\].** Grok reports fixed timing windows (dispense timeout plus 1.5 s) for the emergency motor stop and delayed MCU reboot. Make them proportional to portion size and test slow dispensing and partial power loss.

### Low and hygiene

- Vendor fingerprints (client type, user agent, trace-id format, version strings) are scattered; centralize them.
- Several INFO logs in adoption and backup belong at DEBUG.
- Four manual version bumps per release (VERSION, CARD\_VERSION, manifest.json, pawsync.yaml); generate them from one source.
- Write a SECURITY.md that states the real threat model: the Levoit container key (header only, shared, vendor-derived), the transition PSK, the staging server and the backup server.
- Make sure no older teardown guide with the wrong UART pins is still linked.

## 4. Where the two reviews differ

- **Overall posture:** Grok says almost all high findings are closed. The v1.3.1 diff shows regressions on OTA, AP and PSK.
- **Transition PSK:** Grok calls it scoped and intentional. It is a permanent shared secret until rotated, and it is published in the repo.
- **Levoit container:** Grok describes it as outer encryption that gives integrity. Only the header is encrypted, so it gives neither confidentiality for the body nor real integrity against a LAN attacker.
- **Items only Claude found:** H1, H5, M1, M4, M7, M8.
- **Items only Grok found:** H3, H6 (auth claim), H7, M6, M10 to M12, YAML-embedded credentials.
- **Accepted provisionally:** Grok's statements that logging is at INFO, UART pins are GPIO18/19 at 115200 and the socket limit is 16. My YAML snapshot was stale, so I could not confirm or refute them.

## 5. Merged priority plan

**Now (security):** restore OTA and AP passwords (H1); per-device PSK and OTA password through the patcher, then rotate and drop the fallback (H2); remove the legacy stager routes and make the token one-shot (H3); stop leaving Wi-Fi credentials on disk and in YAML (H4); make the patcher fail closed and reject over-long inputs (H5); authenticate and time-limit the 8088 server (H6); fix the possible tempfile import (H7).

**Next (reliability):** fix the config-flow failure paths and the ignored adoption result (M1); cancel tasks on abort and removal, add a failed-conversion recovery step (M2); bound polling and prefer zeroconf (M3); make CI compile with generated secrets and a real placeholder check (M4); post-patch validation (M5); pin the transition binary hash (M6).

**Later (maintainability):** move backup triggering out of the sensor, repair the tests, split the C++ component, backup retention, version single-sourcing, SECURITY.md.

## 6. Quick checks to settle the unverified items

- `grep -n add_get custom_components/pawsync/ota_stager.py` to see which routes exist.
- `sed -n 1,30p custom_components/pawsync/ota_stager.py` to confirm tempfile and os imports.
- `grep -n -A3 "^ota:\|ap:" pawsync.yaml` on main to confirm the passwords are still absent.
- `grep -rn TRANSITION_NOISE_PSK custom_components` to list every use and look for a rotation step.
- Read the httpd handlers in ppf\_r361s.cpp for any token, PSK or timeout.
- Convert a spare feeder, then try the native API with the public key from a second host.
- After a test conversion, look for pawsync\_ota\_customized.bin and any generated YAML containing the Wi-Fi password.
