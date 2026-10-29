# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.5.x   | :white_check_mark: |
| 1.4.x   | :white_check_mark: |
| < 1.4.0 | :x:                |

## Reporting a Vulnerability

The PawSync project takes the security of pet feeding hardware and local home automation seriously. If you discover a security vulnerability or vulnerability in the firmware, integration, or OTA pipeline, please report it privately:

1. **GitHub Security Advisory**: Go to the **Security** tab of this repository and click **Report a vulnerability**.
2. **Private Communication**: If GitHub Security Advisories is not available, please contact the maintainer directly via GitHub profile contact information.

**Please do NOT open public issues for security vulnerabilities or credential exposures.**

## Vulnerability Scope & Priorities

We prioritize vulnerabilities that could result in:
- Unauthorized device takeover or remote code execution via local network / OTA channels.
- Hardcoded secret / encryption key exposure.
- Denial of service or feeding disruption (pet safety concern).
- Unintended credential exfiltration (e.g., Wi-Fi PSK or Home Assistant tokens).

## Threat Model

### System Architecture & Trust Boundaries

The PawSync pet feeder operates in a dual-MCU environment:
1. **ESP32-C3 SoC (RISC-V)**: Handles Wi-Fi connectivity, SNTP time synchronization, Home Assistant Native API communications, web services, and schedules.
2. **Sinowealth SC95F8766P Coprocessor**: Controls low-level motor drivers, load cells, optical sensors, IR obstacle beams, battery charging circuits, and hardware audio buzzer.

Communication between the two MCUs takes place over an internal bidirectional UART bus (`GPIO18` RX / `GPIO19` TX) at 115200 baud using structured KLV (Key-Length-Value) binary frames.

```
+-----------------------------------------------------------+
|                     Home Network (LAN)                    |
|                                                           |
|   +--------------------+         +--------------------+   |
|   |   Home Assistant   |         | Rogue LAN Actor    |   |
|   |  (Pawsync Component|         |  (Untrusted)       |   |
|   +---------+----------+         +---------+----------+   |
|             |                              |              |
|             | Noise PSK (Port 6053)        | Blocked      |
|             v                              v              |
|   +---------------------------------------------------+   |
|   | PawSync Feeder (ESP32-C3)                         |   |
|   |  - Native API: ChaCha20-Poly1305 Encrypted        |   |
|   |  - Ephemeral OTA: Randomized path & auto-timeout  |   |
|   |  - Boot Health Check: Auto-rollback protection    |   |
|   +-------------------------+-------------------------+   |
|                             | Internal UART               |
|                             | (Strict KLV Bounds Check)   |
|                             v                             |
|   +---------------------------------------------------+   |
|   | Sinowealth Coprocessor (Motor, Sensors, RTC)      |   |
|   +---------------------------------------------------+   |
+-----------------------------------------------------------+
```

### Threat Scenarios & Mitigations

#### 1. Rogue LAN Adversary (Eavesdropping & Injection)
- **Threat**: An unauthorized device on the local network attempts to sniff feeding telemetry, dispense unwanted food, or hijack the feeder.
- **Mitigation**:
  - All Native API communication on TCP port 6053 is encrypted using modern Noise Protocol with unique per-device pre-shared keys (`generate_noise_psk()`).
  - Shared default keys (`TRANSITION_NOISE_PSK`) have been completely eliminated. Each feeder receives an isolated, cryptographically generated 32-byte key stored under MAC-scoped entries in `/config/esphome/secrets.yaml` (mode `0600`).
  - Home Assistant issues a Repairs warning if a deprecated legacy key is detected on an existing install.
  - The Native API rejects unauthenticated connections and drops unauthorized command frames.
  - Port 3232 ESPHome native OTA flashing requires authentication using unique 16-character alphanumeric passwords with a SHA-256 challenge-response handshake (`RESPONSE_REQUEST_SHA256_AUTH` / `0x02`), rejecting unauthorized LAN flashing attempts.

#### 2. Fallback SoftAP Security Policy (Option C: `pawsync1234`)
- **Threat**: When primary Wi-Fi is unavailable or misconfigured, the feeder broadcasts a fallback access point. An attacker within Wi-Fi range might connect to compromise the device.
- **Mitigation**:
  - The fallback SoftAP SSID is standardized to `Pawsync-Feeder-Fallback` with WPA2 passphrase `pawsync1234` (Option C). This guarantees strict compliance with IEEE 802.11i ($\ge 8$ characters), eliminating ESP-IDF boot crashes caused by short derived passwords.
  - The fallback AP exposes only the ESPHome captive portal for network reconfiguration.
  - Physical actuation and feeding control surfaces remain locked behind the unique 32-byte per-device Noise PSK on port 6053. Connecting to the fallback Wi-Fi AP does not allow unauthorized feeding or secret extraction.

#### 3. Transient Cloud Bootstrap Window & Container Security
- **Threat**: During the initial transition from stock firmware to ESPHome, the feeder downloads firmware from a temporary HTTP server hosted by Home Assistant.
- **Mitigation**:
  - The local OTA stager (`ota_stager.py`) binds to the local LAN IP and uses cryptographically randomized token paths (`/firmware_<16-hex>.bin`). Untokenized HTTP routes return `404 Not Found`.
  - Staging enforces a strict one-shot gate (`HTTP 410 Gone`) once the binary transfer completes, preventing replay.
  - An automated 10-minute timeout terminates the stager server, preventing persistent open HTTP listeners.
  - Third-party cloud bearer tokens are immediately purged from Home Assistant entry storage (`entry.data[CONF_TOKEN] = None`) once local adoption succeeds.
  - Customized binaries containing Wi-Fi credentials (`pawsync_ota_customized.bin`) are strictly temporary and are deleted immediately on completion, failure, timeout, or entry unload.
  - **Container AES Key Note**: The `"Levoit"` AES-128-CBC key is a static key required by the stock vendor bootloader to parse the outer container header. It provides integrity verification for the stock bootloader rather than cryptographic privacy against a local network observer. True end-to-end transport security begins once the transition binary boots into ESPHome with unique Noise PSK encryption.
  - **Fail-Closed Structural Image Validation**: Prior to packaging, `firmware_patcher.py` parses the ESP-IDF `0xE9` header and segment tables, verifying valid load addresses and lengths, and enforcing complete absence of placeholder buffers. Any malformed image immediately aborts staging to prevent bricking.

#### 4. Dual-MCU Protocol Abuse & Malformed UART Injections
- **Threat**: Electrical noise or a compromised ESP32-C3 attempts to over-dispense food or crash the motor controller coprocessor.
- **Mitigation**:
  - The `ppf_r361s.cpp` driver implements defensive bounds validation on all KLV fields:
    - Portion counts are clamped to `1..20`.
    - Plan IDs are clamped to `0..7`.
    - Meal indexes are clamped to `1..10`.
  - Every UART packet is verified using an 8-bit additive checksum.
  - Hardware watchdog and physical safety limits on the Sinowealth coprocessor prevent continuous motor runaway.

#### 5. Physical Device Access & Firmware Recovery
- **Threat**: An attacker with physical access to the device disassembles the housing.
- **Mitigation**:
  - The ESP32-C3 hardware UART0 (`GPIO20`/`GPIO21` or boot pins `GPIO9`/`GPIO8`) is accessible for unbricking and development flashing.
  - Physical flash readout exposes NVS credentials if flash encryption is not enabled. Users in hostile physical environments should enable ESP32-C3 hardware flash encryption (`secure_boot`).
  - Backups (`pawsync_factory_4MB_backup.bin`) contain MAC addresses and factory calibration and must be protected.

#### 6. Availability & Feeding Autonomy
- **Threat**: Home Assistant server goes offline or local Wi-Fi drops, causing pets to miss meals.
- **Mitigation**:
  - Schedules are synchronized directly to the feeder's onboard RTC and Sinowealth coprocessor plans.
  - The feeder dispenses programmed meals completely autonomously without active network connectivity.
  - Time synchronization uses SNTP with monotonic fallback.
