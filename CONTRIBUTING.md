# Contributing to PawSync ESPHome

Thank you for your interest in contributing to **PawSync ESPHome**! This project liberates the Pawsync PPF-R361S Smart Pet Feeder from proprietary cloud lock-in, providing local, cloud-free Home Assistant integration with precision load-cell telemetry and reliable feeding automation.

---

## Repository Architecture

- **`pawsync.yaml`**: The primary ESPHome device configuration targeting the ESP32-C3.
- **`components/ppf_r361s/`**: Custom C++ ESPHome component implementing the bidirectional UART protocol with the Sinowealth SC95F8766P motor/scale coprocessor.
- **`custom_components/pawsync/`**: Home Assistant custom integration providing guided cloud onboarding, automated wireless OTA conversion, firmware update entities, and zero-touch ESPHome adoption.
- **`tools/ota/`**: Offline utility scripts for building 129-byte VeSync container binaries and staging local HTTP firmware updates.
- **`partitions.csv`**: ESP-IDF partition table preserving the stock 4MB SPI Flash layout.
- **`tests/`**: Unit and integration test suite covering API clients, config flows, provisioners, and OTA crypto.

---

## Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/sibero80/pawsync_esphome.git
   cd pawsync_esphome
   ```

2. **Set up a Python virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r <(pip list --format=freeze)  # or install pytest, pytest-asyncio, esphome, aiohttp, cryptography
   ```

3. **Configure local secrets for testing:**
   ```bash
   cp secrets.yaml.example secrets.yaml
   # Customize passwords or keys for your test environment
   ```

---

## Running Tests & Verification

Before submitting changes, ensure all unit tests pass and the ESPHome firmware compiles cleanly:

```bash
# Run the Python test suite
PYTHONPATH=. pytest tests/ -v

# Verify ESPHome YAML compilation
esphome compile pawsync.yaml
```

---

## Contribution Guidelines & Principles

1. **Pet Safety First**:
   - Never disable or bypass portion clamping (1–20 portions) or offline scheduling safeguards. The feeder must always remain capable of dispensing scheduled meals even if Wi-Fi or Home Assistant is offline.
2. **Dual-MCU Protocol Invariants**:
   - Communication between the ESP32-C3 and the Sinowealth coprocessor runs on **UART1 (GPIO19 TX, GPIO18 RX) at 115200 Baud (8N1)**.
   - Do not alter frame opcodes, checksums, or timing pauses without empirical validation against physical hardware.
3. **Partition Table Integrity**:
   - The partition table in `partitions.csv` must remain 100% byte-aligned with stock 4MB flash layout (`ota_0` at `0x10000`, `ota_1` at `0x150000`). Firmware images must strictly fit within 1,310,720 bytes.
4. **Code Quality**:
   - Python code must conform to PEP 8 standards with type hints.
   - C++ code should follow ESPHome style guidelines with clear logging levels (`ESP_LOGD`, `ESP_LOGI`, `ESP_LOGW`).

---

## Submitting Pull Requests

1. Fork the repository and create a feature branch (`git checkout -b feature/my-new-feature`).
2. Commit your changes with clear, descriptive commit messages.
3. Push to your branch and submit a Pull Request targeting `main`.
4. Ensure all CI checks (Hassfest, HACS validation, Pytest, ESPHome compile) pass.
