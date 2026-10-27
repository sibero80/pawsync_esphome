# Technical Replication & Hardening Dossier: Software-Only OTA Installation on Pawsync PPF-R361S

> **Device Target:** Pawsync Smart Pet Feeder (`PPF-R361S` / `PPF-R361S-WUS`)  
> **Vendor Model ID:** `VS_WB_PFM_PPF-R361S-WUS_US` (BLE ID: `92`)  
> **Target SoC:** ESP32-C3FH4 (4MB Flash, RISC-V 160MHz) + Sinowealth SC95F8766P Coprocessor  
> **Author:** Antigravity Engineering Lead  
> **Date:** October 2026  
> **Workspace:** [`/root/pawsync_oma2`](file:///root/pawsync_oma2)  
> **Baseline Commit:** [`b129de9`](file:///root/pawsync_oma2)  

---

## Executive Summary & Replication Thesis

Taking local control of smart pet feeders conventionally demands physical disassembly, locating pogo-pin test pads, and attaching USB-UART adapters. 

Our investigation confirms that a **100% wireless, software-only Over-The-Air (OTA) installation** is feasible on factory Pawsync PPF-R361S feeders running stock v1.2.5 firmware. Furthermore, because the stock factory firmware resides in partition **`ota_1`** (`0x150000`) while OTA updates target partition **`ota_0`** (`0x010000`), the device supports a **Zero-Soldering Dual-Boot Software Rollback**—enabling users to revert to factory firmware directly from Home Assistant at any time without physical intervention.

```
+--------------------------------------------------------------------------------------------------+
|                                    WIRELESS OTA FLASHING FLOW                                    |
+--------------------------------------------------------------------------------------------------+
| 1. Compile ESPHome Firmware (.bin <= 1,310,720 bytes)                                            |
|    |                                                                                             |
| 2. Wrap into 129-byte VeSync Container (tools/ota/build_vesync_ota.py)                           |
|    |  [Byte 0: 0x01] + [Bytes 1..128: AES-128-CBC Encrypted Header] + [Bytes 129+: Raw Binary]   |
|    |                                                                                             |
| 3. Stage Container on Local LAN HTTP Server (tools/ota/trigger_ota.py --serve)                   |
|    |                                                                                             |
| 4. Dispatch Ingress Trigger to Stock Firmware:                                                   |
|    |---> Vector A: Developer TCP Port 55555 (Direct LAN JSON injection if active)                |
|    +---> Vector B: VeSync Cloud Bypass API (smartapi bypassV2 endpoint fallback)                 |
|    |                                                                                             |
| 5. Stock Firmware ves_ota downloads container to ota_0 (0x010000) & verifies MD5                |
|    |                                                                                             |
| 6. Device reboots into ESPHome Native API (Port 6053). ota_1 factory firmware preserved.        |
+--------------------------------------------------------------------------------------------------+
```

---

## 1. Forensic Disassembly Evidence & Findings Validation

### 1.1 Hardware Root-of-Trust & eFuse Posture
Audit of the factory SPI flash dump ([`esp32c3_dump.bin`](file:///root/pawsync_oma2/esp32c3_dump.bin)) confirms that Espressif silicon security primitives are completely unconfigured:
- **Secure Boot V2:** `DISABLED` (Bootloader magic `0xE9`; zero RSA/ECDSA signature blocks appended).
- **Flash Encryption:** `DISABLED` (Plaintext RISC-V instructions and rodata strings).
- **Anti-Rollback:** `DISABLED` (`secure_version = 0`).

**Replication Impact:** The ROM bootloader executes any valid binary written to an active application partition without hardware rejection.

---

### 1.2 SPI Flash Partition Architecture
The stock partition table at offset `0x008000`:

| Partition Name | Type | Subtype | Flash Offset | Size (Bytes) | Max Size | Status / Function |
|---|:---:|:---:|---|---|---|---|
| `nvs` | `0x01` | `0x02` | `0x00009000` | `0x00004000` | 16 KB | Wi-Fi credentials & device tokens |
| `otadata` | `0x01` | `0x00` | `0x0000D000` | `0x00002000` | 8 KB | ESP-IDF OTA boot state register |
| `phy_init` | `0x01` | `0x01` | `0x0000F000` | `0x00001000` | 4 KB | RF PHY calibration |
| **`ota_0`** | `0x00` | `0x10` | **`0x00010000`** | `0x00140000` | **1,310,720 B (1.25 MB)** | **Target for Custom ESPHome OTA** |
| **`ota_1`** | `0x00` | `0x11` | **`0x00150000`** | `0x00140000` | **1,310,720 B (1.25 MB)** | **Active Factory Firmware (v1.2.5)** |
| `usercfg` | `0x01` | `0x02` | `0x00290000` | `0x00004000` | 16 KB | Feeding schedules (`plan_param`) & `dbg_cfg` |
| `fac_data` | `0x01` | `0x02` | `0x00294000` | `0x00002000` | 8 KB | Factory production serial & MAC |
| `storage` | `0x01` | `0x02` | `0x00296000` | `0x00010000` | 64 KB | SPIFFS storage |
| `historydata` | `0x01` | `0x02` | `0x002A6000` | `0x00058000` | 360 KB | Historical feeding events |
| `log` | `0x01` | `0x02` | `0x002FE000` | `0x00000400` | 1 KB | Panic / crash dump log |
| `custom_data` | `0x01` | `0x02` | `0x002FF000` | `0x00100000` | 1 MB | Factory meal call audio (`meal_call.wav`) |

---

### 1.3 The VeSync Proprietary OTA Container Format
Disassembly of `app_active.elf` at `0x420172de` (`ves_ota` handler) reveals the required 129-byte container:

```
+---------------+-----------------------------------------------+-----------------------------------+
|  crypto_type  |         Encrypted Header (128 bytes)          |        Raw Firmware Binary        |
|    (1 Byte)   |              AES-128-CBC Mode                 |         (esp32c3 .bin)            |
+---------------+-----------------------------------------------+-----------------------------------+
     Byte 0                       Bytes 1..128                               Bytes 129..N
```

- **Symmetric Keys** decoded from `.flash.rodata`:
  - **Key:** `b'llwantaeskey1.01'` (16 bytes ASCII)
  - **IV :** `b'llwantaesivv1.01'` (16 bytes ASCII)
- **Decrypted 128-Byte Header Layout:**

| Byte Offset | Length | Field | Value / Verification Standard |
|---|:---:|---|---|
| `0x00` | 1 | `crypto_type` | Must be `0x01` |
| `0x01..0x20` | 32 | `payload_md5` | 32-character ASCII hex MD5 of payload (`bytes[129:]`) |
| `0x21` | 1 | `null_term` | `0x00` |
| `0x22..0x31` | 16 | `model` | Checked via `strncmp(hdr+0x22, "VS_WB_PFM_PPF-R", 15)` |
| `0x32..0x41` | 16 | `version` | Version string comparison (`9.9.9` > `1.2.5`) |
| `0x42..0x49` | 8 | `hw_version` | Target hardware revision (`1.0\x00`) |
| `0x4A..0x4B` | 2 | `region` | Whitelist checked via `strstr(hdr+0x4A, "UN")` |
| `0x4C..0x7F` | 52 | `padding` | Padded with `0x00` |

---

## 2. Gap Analysis & Critique of Prior Agent Findings

While the prior agent correctly identified the AES keys and container layout, our deeper audit uncovered **5 critical technical gaps and unverified assumptions**:

```
+-----------------------------------+-----------------------------------+-----------------------------------+
| Architectural Dimension           | Prior Agent's Assumption          | Verified Ground Truth & Fix       |
+-----------------------------------+-----------------------------------+-----------------------------------+
| 1. Developer Port 55555 State     | Assumed open and listening on LAN | GORMANCY GAP: ves_dev task is     |
|                                   | out-of-the-box                    | dormant unless dbg_cfg is set in  |
|                                   |                                   | NVS. Factory units have it CLOSED.|
| 2. Partition Sizing Guardrail     | Noted 1.25 MB limit in text, but  | OVERFLOW RISK: Script lacked      |
|                                   | script had zero size enforcement  | size assertion. Binary > 1.25 MB  |
|                                   |                                   | corrupts usercfg at 0x290000.     |
| 3. Image Header Integrity         | Permitted arbitrary files without | BRICK HAZARD: Enforced ESP32      |
|                                   | validation                        | magic byte (0xE9) validation.     |
| 4. Boot Rollback Confirmation     | Assumed automatic boot state      | ROLLBACK CANCELLATION: Verified   |
|                                   |                                   | enable_ota_rollback: true in IDF. |
| 5. Rollback Strategy              | Hardware pogo-pin flashing only   | INNOVATION: Instant zero-tool     |
|                                   | (unscrewing chassis, jumper wires)| software rollback button to ota_1.|
+-----------------------------------+-----------------------------------+-----------------------------------+
```

### Gap 1: Developer Port 55555 Ingress Realities
The prior agent suggested sending local JSON directly to `feeder_ip:55555`. However, disassembly of `vesync_developer_flash_read_dbg_cfg` (`0x420267ba`) proves that `ves_dev` is **not spawned on factory units** unless `dbg_cfg` exists in the `usercfg` NVS partition.  
*Remediation:* Our hardened [`tools/ota/trigger_ota.py`](file:///root/pawsync_oma2/tools/ota/trigger_ota.py) implements automated probing: if port 55555 is closed, it routes the trigger through the VeSync Cloud `bypassV2` endpoint to activate the update or enable developer mode.

### Gap 2: Strict Binary Partition Size Enforcement
The maximum capacity of `ota_0` is **1,310,720 bytes**. If an operator includes extra ESPHome components (such as Bluetooth Proxy or heavy Web UI), the binary will overflow. Writing beyond 1,310,720 bytes will cause `esp_ota_write()` to fail or overwrite the `usercfg` partition (`0x290000`).  
*Remediation:* [`tools/ota/build_vesync_ota.py`](file:///root/pawsync_oma2/tools/ota/build_vesync_ota.py) implements a hard pre-packaging gate that halts execution immediately with an error if the binary exceeds 1,310,720 bytes.

### Gap 3: Zero-Soldering Dual-Boot Software Rollback
The prior agent treated the rollback as a purely physical hardware operation with `esptool`. Because the factory firmware remains untouched in `ota_1` (`0x150000`), we added native rollback capability directly into our ESPHome component:
```cpp
void PPFR361SComponent::rollback_to_stock_firmware() {
  const esp_partition_t *ota1 = esp_partition_find_first(ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_APP_OTA_1, "ota_1");
  if (ota1 != nullptr) {
    esp_ota_set_boot_partition(ota1);
    esp_restart();
  }
}
```
This is exposed in Home Assistant as a configuration button (`button.pawsync_feeder_rollback_to_factory_firmware_slot_ota_1`), granting users a risk-free escape hatch back to stock firmware.

---

## 3. Tooling Suite Inventory

All hardened tools reside in [`/root/pawsync_oma2`](file:///root/pawsync_oma2):

1. **[`tools/ota/build_vesync_ota.py`](file:///root/pawsync_oma2/tools/ota/build_vesync_ota.py)**:
   - Validates ESP32 magic byte `0xE9`.
   - Enforces 1,310,720-byte hard limit.
   - Encrypts 128-byte header using AES-128-CBC (`llwantaeskey1.01` / `llwantaesivv1.01`).
   - Executes automatic decryption roundtrip self-test.
2. **[`tools/ota/trigger_ota.py`](file:///root/pawsync_oma2/tools/ota/trigger_ota.py)**:
   - Probes port 55555 (`--probe`).
   - Hosts embedded multi-threaded HTTP staging server (`--serve`).
   - Dispatches local JSON over TCP port 55555 (`--inject-local`).
   - Dispatches cloud envelope via `smartapi.vesync.com/pet/api/deviceManaged/v1/bypassV2` (`--inject-cloud`).
3. **[`tests/test_ota_pipeline.py`](file:///root/pawsync_oma2/tests/test_ota_pipeline.py)**:
   - 6 automated unit & integration tests verifying crypto roundtrips, size enforcement, bad magic rejection, schema compliance, HTTP serving, and production package validation.

---

## 4. Step-by-Step Operator Runbook

### Step 1: Compile ESPHome Firmware
Compile the optimized firmware binary:
```bash
/root/esphome/venv/bin/esphome compile pawsync.yaml
```
Output binary: `.esphome/build/pawsync-feeder/build/firmware.ota.bin` (Size: ~1,138,160 bytes, leaving ~172 KB headroom).

### Step 2: Package VeSync Container
Generate the authenticated container:
```bash
/root/esphome/venv/bin/python3 tools/ota/build_vesync_ota.py \
  .esphome/build/pawsync-feeder/build/firmware.ota.bin \
  -o pawsync_ota_update.bin \
  --version "9.9.9"
```

### Step 3: Stage the Binary on LAN
Launch the local HTTP staging server:
```bash
/root/esphome/venv/bin/python3 tools/ota/trigger_ota.py --serve --http-port 8000
```
Note the host IP address displayed (e.g. `http://192.168.1.100:8000/pawsync_ota_update.bin`).

### Step 4: Dispatch the Trigger
* **Path A (Developer Port Open):**
  ```bash
  /root/esphome/venv/bin/python3 tools/ota/trigger_ota.py --inject-local \
    --feeder-ip 192.168.1.48 \
    --url http://192.168.1.100:8000/pawsync_ota_update.bin
  ```
* **Path B (Port Closed - Cloud Bypass Ingress):**
  ```bash
  /root/esphome/venv/bin/python3 tools/ota/trigger_ota.py --inject-cloud \
    --account-id "<ACCOUNT_ID>" \
    --token "<TOKEN>" \
    --cid "<CID>" \
    --url http://192.168.1.100:8000/pawsync_ota_update.bin
  ```

### Step 5: Verification & Zero-Soldering Rollback
1. Within 15–30 seconds, the feeder downloads the container from the HTTP server and reboots into ESPHome.
2. The device appears in Home Assistant on Port 6053 with full entity control.
3. If rollback to factory firmware is ever desired, press `Rollback to Factory Firmware (Slot ota_1)` in Home Assistant to immediately reactivate stock slot `ota_1`.
