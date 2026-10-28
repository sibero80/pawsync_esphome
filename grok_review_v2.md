# PawSync ESPHome (sibero80/pawsync_esphome) – Updated Review & Remediation Plan
**Version reviewed:** v1.1.2 (commit e8544d9 and preceding remediation commits, 2026-10-28)

## 1. Executive Summary

v1.1.2 represents a meaningful security and quality hardening pass in direct response to the earlier review. Most high-priority items have been addressed or substantially improved. The project is now in a stronger position for cautious production use, provided users follow the documented physical flash-backup guidance.

**Key improvements in v1.1.2:**
- Unique Noise PSK generation (`generate_noise_psk()`)
- OTA password support + secret
- Fallback AP password moved to secrets
- Logger level changed from DEBUG → INFO
- Dynamic firmware version via `ESPHOME_PROJECT_VERSION`
- Timezone made configurable (substitution)
- UART documentation clarified (UART0 vs UART1)
- SHA-256 verification of firmware binary before staging
- Better stager bind logic (prefer local IP)
- Full CI pipeline (pytest, hassfest, HACS validation, ESPHome compile)
- CONTRIBUTING.md, SECURITY.md, issue templates added

**Remaining high-value gaps:**
- Shared legacy `DEFAULT_NOISE_PSK` still present as fallback
- Long-lived cloud tokens stored in config entry with no rotation/options flow
- OTA stager still serves firmware without authentication
- No signed releases or published checksums for the bundled binary
- Options flow missing for credential/unit management

---

## 2. Validation of Original Findings

### Security

| Finding | Status | Notes |
|---------|--------|-------|
| Hardcoded / shared `DEFAULT_NOISE_PSK` | Partially Fixed | Generation function added; legacy shared key retained for upgrades |
| Cloud credential handling / long-lived tokens | Open | Tokens still persisted; no rotation or short-lived design |
| Wi-Fi credentials in generated YAML | Improved | Proper secrets usage |
| OTA stager binds to 0.0.0.0, no auth | Improved | Prefers local IP; SHA-256 computed; still unauthenticated |
| Bundled firmware integrity | Improved | SHA-256 now calculated and logged |
| Weak fallback AP password | Fixed | Now `!secret wifi_ap_password` |
| Logger level DEBUG | Fixed | Now INFO |
| Missing OTA password | Fixed | `!secret ota_password` required |

### Quality & Architecture

| Finding | Status | Notes |
|---------|--------|-------|
| Hardcoded timezone (America/Bogota) | Fixed | Substitution + dual time sources (HA + SNTP) |
| Static firmware version string | Fixed | Uses `ESPHOME_PROJECT_VERSION` |
| UART pin/baud docs vs code mismatch | Fixed | Clear UART0 (flash) vs UART1 (coprocessor @ 115200) distinction |
| Complex state machines / edge cases | Open | Input validation added on services; core complexity remains |
| Config-flow error recovery & Linux-only ARP | Mostly Open | Some hardening; ARP still Linux-specific |
| Manifest / HACS metadata | Slightly Improved | Version bump only |
| Testing & CI | Significantly Improved | Full GitHub Actions pipeline + issue templates |
| Documentation | Improved | Stronger disclaimers, CONTRIBUTING, SECURITY.md |

### Best Practices (ESPHome / HA / HACS)

| Finding | Status | Notes |
|---------|--------|-------|
| External component packaging | Open | Still local path |
| Secrets hygiene | Improved | AP + OTA + encryption keys |
| API encryption + reboot_timeout | Improved | `reboot_timeout: 0s`; unique key generation available |
| Options flow | Open | Not present |
| Lovelace card practices | Good | Auto-registration intact |
| Binary supply-chain (signed releases) | Partially Improved | Runtime SHA-256 only |
| Community signals / templates | Improved | Issue templates + CONTRIBUTING added |

---

## 3. Remaining Gaps (Priority Ordered)

### High Priority
1. **Shared legacy Noise PSK** – Remove or strongly deprecate the hardcoded fallback so every new device gets a unique key.
2. **Unauthenticated OTA stager** – Add a short-lived token or basic auth, or bind exclusively to a private interface and enforce a hard timeout.
3. **Long-lived cloud tokens** – Implement an options flow for credential refresh and document that tokens are bootstrap-only.
4. **Firmware supply chain** – Publish SHA-256 (and ideally signatures) for release binaries; prefer build-from-source or reproducible builds.

### Medium Priority
5. Options flow for units, credentials, and polling/refresh settings.
6. Replace Linux-only ARP resolution with a more portable discovery method (or make it optional).
7. Move the ESPHome component to a proper external/GitHub package source for easier updates.
8. Richer HACS metadata and quality-score signals.

### Lower Priority
9. Further input validation and fuzzing of the UART protocol handler.
10. Explicit threat-model document covering local-network trust assumptions and physical-access risks.

---

## 4. Proposed Remediation Steps

### Immediate (Security Hardening)

1. **Noise PSK**
   - Make `generate_noise_psk()` the only path for new devices.
   - On upgrade, detect the legacy shared key and force regeneration + user notification.
   - Remove or comment out `DEFAULT_NOISE_PSK` after a deprecation window.

2. **OTA Stager**
   - Generate a one-time random path or token when starting the stager.
   - Reject requests that do not present the token.
   - Auto-stop the server after a fixed window (e.g. 5–10 minutes) or after successful transfer.
   - Prefer binding only to the LAN interface; never fall back to 0.0.0.0 if a specific IP is known.

3. **Cloud Credentials**
   - Add an options flow that allows re-authentication without deleting the config entry.
   - Store tokens with an explicit “bootstrap-only” comment and clear them (or mark them non-reusable) after successful local adoption.
   - Log a warning if a stored token is older than a configurable age.

4. **Firmware Integrity**
   - Publish SHA-256 checksums in the release notes and/or a `checksums.txt` file.
   - Optionally embed an expected hash in the integration and refuse to stage a binary that does not match.
   - Document how users can rebuild the binary from source.

### Short-Term (Quality & Maintainability)

5. Implement a full options flow (credentials, unit system, timezone override, stager port).
6. Replace or supplement `/proc/net/arp` with mDNS / zeroconf or a user-supplied IP.
7. Publish the `ppf_r361s` component as an external component (GitHub source) so users can pin versions cleanly.
8. Expand CI to include a basic lint/type-check step and a smoke test of the config flow.

### Medium-Term

9. Add a brief threat-model section to SECURITY.md covering:
   - Local network is trusted after conversion
   - Physical UART access can always reflash
   - Cloud bootstrap is a one-time risk window
10. Consider signing release binaries (even a simple GPG signature) and verifying them in the update platform.

---

## 5. Recommended Next Actions for Maintainers

1. Cut a v1.1.3 (or v1.2.0) that fully retires the shared Noise PSK and adds stager authentication + options flow.
2. Publish checksums for the current OTA binary.
3. Update the README “Security” / “Threat Model” section to reflect the remaining residual risks honestly.
4. Keep the strong physical-backup recommendation prominent — it remains the single most important user safety measure.

---

## 6. Closing Assessment

The project has responded rapidly and effectively to the original review. Core security hygiene (unique keys, secrets, logging, documentation accuracy, CI) is now at a solid community-project level. Closing the remaining items above — especially the shared PSK fallback, unauthenticated stager, and long-lived tokens — would bring it to a high standard for a reverse-engineered, dual-MCU, cloud-bootstrap IoT integration.

Users should still treat the wireless conversion as experimental, always take a full 4 MB UART backup first, and understand that the feeder’s safety ultimately depends on the on-device scheduler continuing to function offline.
