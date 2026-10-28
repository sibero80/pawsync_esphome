# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.1.x   | :white_check_mark: |
| 1.0.x   | :x:                |

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

## Security Best Practices for Users

1. **Unique Noise Encryption PSK**: Each device should use an individually generated 32-byte base64 Noise PSK for ESPHome Native API encryption. Avoid reusing shared default keys across multiple devices.
2. **Secrets Hygiene**: Store all credentials in `secrets.yaml` (which is git-ignored) and never commit private tokens, passwords, or wireless SSIDs to public source control.
3. **Flash Dumps**: Full 4MB flash backups (`pawsync_factory_4MB_backup.bin`) contain your device's unique MAC address, factory calibration data, and potentially stored Wi-Fi credentials in the NVS partition. Never share raw flash images publicly.
