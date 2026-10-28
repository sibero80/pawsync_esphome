# PawSync ESPHome Project: Quality, Security and Best-Practices Review

Repository: github.com/sibero80/pawsync\_esphome | Reviewed 28 Oct 2026 | Project version in YAML: 1.1.1 | Target device: Pawsync PPF-R361S (ESP32-C3 + SC95F8766P)

## 1. Scope and confidence

**Reviewed:** README.md, FLASHING\_WIZARD.md, hacs.json, pawsync.yaml, partitions.csv, secrets.yaml.example and the repository landing page.

**Not reviewed:** GitHub blocked automated access to directory listings, so the Python integration (custom\_components/pawsync: config flow, manifest, ota\_stager.py, vesync\_relay.py), the C++ component (components/ppf\_r361s), the Lovelace card JavaScript, the blueprint, the GitHub Actions workflows, tests/, tools/ and docs/ were not read. For those areas I list checks to run, not defects. The rendered GitHub view also flattened the YAML indentation, so I only flagged issues that do not depend on it.

Items marked **(verify)** are inferences from the visible config plus general ESP-IDF, ESPHome and Home Assistant behavior. They have not been confirmed on hardware.

## 2. Executive summary

The project is unusually thorough for a reverse-engineering effort: encrypted native API, a documented UART backup and restore path, a rollback runbook, a notification blueprint, and clear liability warnings. The main weaknesses are (a) a headline safety claim, the preserved stock firmware, that may not survive normal use, (b) unauthenticated OTA, (c) documentation that contradicts the partition table and the YAML in ways that could brick a unit during recovery, and (d) release and CI hygiene that stops users from pinning, rolling back or trusting updates.

**Top five actions**

1. Prove, or fix, that the stock image in ota\_1 survives repeated ESPHome OTA updates.
2. Add an OTA password and a unique fallback-AP password.
3. Reconcile flash offsets, UART pins and baud rate across README, FLASHING\_WIZARD, partitions.csv and pawsync.yaml.
4. Cut tagged releases, pin the dashboard import and external components to a tag, and remove version drift.
5. Add CI (hassfest, HACS validation, ESPHome compile matrix) and review the OTA stager for network exposure.

## 3. Strengths

- API encryption key comes from secrets; secrets.yaml.example and .gitignore exist.
- Full 4 MB flash backup and restore at offset 0x0 is the correct, safest recovery path and is consistent with the partition table.
- partitions.csv marks fac\_data and log as readonly and keeps 64 KB alignment for app slots.
- Factory rollback is gated by an unlock switch and an entity\_category: config button.
- Services have descriptions, typed variables and examples.
- The esphome: project block, dashboard\_import and a notification blueprint with 14 alert channels show good HA-user focus.
- Explicit no-warranty and not-affiliated disclaimers; MIT license.

## 4. Findings

### High severity

**H1. The factory rollback image may be overwritten by routine OTA (verify)**

The README says the stock firmware is preserved in ota\_1 and can be restored in two clicks. partitions.csv defines two equal app slots (ota\_0 at 0x10000, ota\_1 at 0x150000, 1.25 MB each). ESP-IDF OTA writes to the slot that is not currently running, and ESPHome's ESP-IDF OTA follows that default. If ESPHome runs from ota\_0, the first ESPHome-to-ESPHome OTA targets ota\_1 and destroys the stock image. After that the rollback button has nothing to roll back to. Unless components/ppf\_r361s overrides slot selection (I could not see it), this undermines the headline safety feature.

- Test: flash, OTA twice, dump 0x150000 with esptool and compare its hash with the stock dump.
- Options: keep the stock image in a partition ESPHome never targets (for example an app/factory partition, if the ESPHome build fits in smaller slots); force OTA to a single slot and accept losing A/B safety; or have the integration refuse to OTA over the stock slot and document that rollback only exists until the first self-update.
- Whatever is chosen, make the README say exactly what is preserved and until when.

**H2. Unauthenticated OTA and a hard-coded fallback AP password**

pawsync.yaml has `ota: - platform: esphome` with no password, and the fallback AP password is the literal string `fallbackpassword` with captive\_portal enabled. The API key does not protect OTA. Anyone on the LAN (guest Wi-Fi, a compromised IoT device) can push firmware to a device that controls food dispensing, and anyone in radio range can join the fallback AP after a Wi-Fi outage.

- Add `password: !secret ota_password` under the OTA platform.
- Read the AP password from secrets (unique per device) and add both keys to secrets.yaml.example.
- Document placing the feeder on an IoT VLAN.

**H3. Flash-layout documentation contradicts partitions.csv, and recovery steps can brick a unit**

- Stock ota\_1: the README partial-backup command reads 0x160000 to 0x2A0000. partitions.csv puts ota\_1 at 0x150000 and ends it at 0x290000.
- Bootloader and table: the README lists the partition table at 0x10000 and the bootloader at 0x0 to 0x10000. In the CSV, 0x10000 is the start of ota\_0, and nvs at 0x9000 implies the standard table at 0x8000, which sits inside the README's bootloader range.
- Direct flashing: FLASHING\_WIZARD writes firmware.bin at 0x20000. In the CSV, ota\_0 starts at 0x10000, so an image at 0x20000 will not boot.

Keep the full-image backup and restore as the only recommended path, delete or correct the partial ones, generate every offset in the docs from partitions.csv in CI, and test each documented command on a spare unit.

**H4. UART pins and baud rate differ between YAML and docs**

pawsync.yaml configures the coprocessor UART on tx GPIO19, rx GPIO18 at 115200. The README spec table and FLASHING\_WIZARD say GPIO20/GPIO21 at 9600 8N1. GPIO20/21 are the ESP32-C3 UART0 defaults used for the serial flashing pads, so the spec table appears to conflate the console UART with the coprocessor link. Separately, GPIO18/19 are the ESP32-C3 USB D-/D+ pins, so using them as a UART conflicts with the USB-C CDC flashing method described in FLASHING\_WIZARD. Either the docs or the YAML is wrong, or there are hardware revisions. Add a hardware-revision table and state which one each document applies to.

**H5. Adoption path exposure (code not reviewed, verify)**

Per FLASHING\_WIZARD, Home Assistant opens an HTTP server on port 8000, serves the firmware in plain HTTP with an MD5 check inside a vendor container, and triggers the flash through the vendor cloud API using the user's VeSync credentials. Checks for the unreviewed code:

- Serve only during the flash window, only to the feeder's IP, on an unguessable one-shot path; shut down on success, failure and cancel.
- Verify a SHA-256 of the staged image before serving; MD5 alone is not integrity protection against a LAN attacker.
- Keep credentials, tokens, CID and MAC out of logs and diagnostics (use `async_redact_data`), and discard the account password after token capture if possible.
- Pacing (8 s pause, 20 ms per chunk) must use `await asyncio.sleep`, never blocking calls, so the HA event loop is not stalled.
- Handle power loss or timeout mid-flash with a clear repair issue and a link to the UART recovery guide.
- The one-click path depends on a vendor cloud command that can be patched away. Keep the UART route a first-class, tested alternative and say what data is sent to the vendor.

### Medium severity

**M1. Version drift.** project.version and the header comment say 1.1.1, the Firmware Version text sensor returns the hard-coded string 1.1.0, and the README advertises card v1.3.0. Use a single substitution for the version, expose it with the ESPHome version/project mechanisms, and make the HA manifest.json version equal the git tag (the HACS release flow expects this). The template text sensor also has no `update_interval: never`, so it re-evaluates a constant every minute.

**M2. Unpinned supply chain.** dashboard\_import uses `github://sibero80/pawsync_esphome/pawsync.yaml@main`, which tracks a moving branch. The Releases section of the repo is empty, so HACS users cannot pin or roll back. Also, `external_components` uses `type: local, path: components`; a user who adopts the config through the dashboard import will not have that folder. Use a git source pinned to a tag or commit for external\_components, point dashboard\_import at a tag, and publish GitHub releases.

**M3. Image marked valid before anything is proven.** The on\_boot lambda at priority 2000 calls `esp_ota_mark_app_valid_cancel_rollback()` before Wi-Fi, API or the coprocessor link start. That cancels the bootloader's automatic rollback for a build that crashes later in boot. Mark the app valid only after a meaningful health signal (for example the first valid coprocessor telemetry and an API or Wi-Fi connection).

**M4. Offline autonomy claim vs time source.** The README says the feeder runs autonomously if Wi-Fi or Home Assistant is offline, but the only time source is `time: platform: homeassistant` (and its id is `sntp_time`, which is misleading). After a power cycle with HA unreachable, the clock may be unset and scheduled meals may not fire. Add a `sntp` time platform as a fallback or confirm the coprocessor keeps time, and test a cold boot with HA offline.

**M5. Reboot timeouts.** api and wifi are left at default `reboot_timeout` values (15 minutes). A Home Assistant outage longer than that can make the feeder reboot repeatedly, interrupting dispensing and losing volatile state. Decide deliberately: for an appliance that must keep running, set `reboot_timeout: 0s` on api and consider the trade-off for Wi-Fi recovery.

**M6. Service validation and feeding safety.** In `set_meal_schedule`, an out-of-range `meal` silently becomes slot 1 and an out-of-range `plan` silently becomes the active plan, so a typo overwrites a real meal. `portions` is not range-checked in YAML (check the C++), and `feed` accepts up to 20 portions with no daily cap or minimum interval. Reject invalid input with a logged error, clamp in firmware, and add a configurable daily maximum and cooldown. Pet safety deserves a documented failure-mode table: motor jam, scale fault, clock loss, coprocessor link loss.

**M7. Device state mirrored in template entities.** Active plan (template select) and grams-per-portion (template number) use `restore_value: false` plus an on\_boot lambda at priority -100 to copy the real value back from the bridge. That depends on startup ordering and on the coprocessor having answered by then. Implement these as native entities in the ppf\_r361s component that publish state when telemetry arrives.

**M8. DEBUG logging in production.** `logger: level: DEBUG` floods the API log stream and costs CPU on a single-core C3 that also drives audio. Ship at INFO and raise per-component levels only when needed.

**M9. Compatibility claims need CI proof.** The badges and min\_version claim ESPHome 2024.6+ and HA 2024.1+ through 2026.x. The speaker-based `media_player` with `announcement_pipeline` is, as far as I know, newer than ESPHome 2024.6 (verify). On the HA side, the old `hass.http.register_static_path` was removed in 2025, replaced by `async_register_static_paths` (verify the card registration code). Compile and test against the declared minimum and the latest stable and beta.

**M10. Hard-coded timezone.** `timezone: America/Bogota` is wrong for every other user of a public package. Make it a substitution or document overriding it.

**M11. Firmware size and RAM headroom.** Each app slot is 1.25 MB (0x140000), smaller than ESPHome's default, and the build includes API, I2S audio and a media player on a \~400 KB RAM chip. Add a CI size check that fails above about 90% of the slot, and expose heap and uptime diagnostics.

**M12. Rollback interlock.** The unlock switch is an optimistic template switch with no explicit restore mode. Set `restore_mode: ALWAYS_OFF` so an unlocked state cannot persist across reboots, and make the integration (not only the button lambda) enforce the lock.

**M13. Flash backups contain secrets.** The README notes the 4 MB backup holds the unit's cloud credentials; it will also hold Wi-Fi credentials. Add a warning not to attach dumps to issues, and add `*.bin` and backup patterns to .gitignore.

### Low severity and hygiene

- **Entity design:** names embed thresholds (for example Bowl Overflow (>150g)), which go stale when the threshold changes. Check device\_class, state\_class (total\_increasing or a defined reset for the daily totals), units and entity\_category (diagnostic for battery, desiccant and cleaning counters).
- **Missing diagnostics:** no uptime, Wi-Fi signal, restart or safe-mode button, or heap sensors in the YAML.
- **Events:** `homeassistant.event` payloads work, but ESPHome `event` entities are more discoverable and easier to automate. Document the event names and payloads.
- **Frontend card:** it is served from both /pawsync/ and /local/, and users are told to hard-refresh when it is stale. Use a single path with a versioned query string for cache busting. Confirm the card resolves entities through the device registry (multi-feeder support) rather than fixed entity ids.
- **Repo metadata:** no description, topics, releases or tags. Add them, plus SECURITY.md, CONTRIBUTING.md and issue templates (device revision, ESPHome and HA versions, logs with secrets redacted).
- **Docs:** the README promises setup without taking the device apart while also strongly recommending a UART backup. Make the backup an acknowledged step in the wizard. Move the feasibility and implementation plan into docs/.
- **Legal hygiene:** confirm no vendor binaries or keys are committed, and state how the vendor container header was obtained.
- **Build reproducibility:** pin the ESPHome and ESP-IDF versions used in CI, and set `flash_size: 4MB` explicitly.

## 5. Recommended CI and test baseline

- hassfest and the HACS validation action on every push and PR.
- ESPHome `config` and `compile` matrix: declared minimum version, latest stable, beta. Fail on size above the threshold.
- yamllint, ruff and pytest for the integration (config flow, OTA stager with a fake feeder, redaction tests); clang-format and cppcheck for the component; a unit test for the schedule and day-string parsing.
- CodeQL for Python and JavaScript, Dependabot for GitHub Actions, actions pinned by commit SHA, `permissions: contents: read` by default.
- A release workflow that builds firmware, attaches checksums, and tags the manifest version.
- A hardware-in-the-loop checklist run before each release: cold boot with HA offline, two consecutive OTAs, rollback, restore from the 4 MB backup.

## 6. Checklist for the unreviewed Home Assistant integration

- manifest.json: accurate `iot_class` (cloud for adoption, local push afterward), `integration_type`, `dependencies`, `requirements` pinned, version matching the tag.
- Config flow: unique\_id per feeder, reauth and reconfigure flows, no secrets in logs, translations in strings.json.
- Modern patterns: `runtime_data` on the config entry, a coordinator or push-based updates, `has_entity_name`, device registry entries, diagnostics with redaction, repair issues for failed flashes.
- Async correctness: no blocking I/O or `time.sleep` in the event loop; the HTTP stager uses aiohttp and is cleaned up on unload.
- Frontend registration: current static-path API, resource registered once, no duplicate modules on reload.

## 7. Suggested roadmap

**Now (safety):** run the double-OTA test (H1), add OTA and AP passwords (H2), fix flash offsets, pins and baud in the docs (H3, H4), add input validation to the services (M6).

**Next (trust):** tag a release, pin imports, fix the version drift, add CI with the size gate, review the OTA stager (H5), add a SNTP fallback and decide reboot timeouts (M4, M5).

**Later (polish):** native entities for plan and calibration, entity metadata, diagnostics, event entities, repo metadata and contribution docs.
