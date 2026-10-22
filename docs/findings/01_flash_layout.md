# 01 Flash Layout & Forensics Report: Pawsync PPF-R361S-WUS

## 1. Flash Integrity & Encryption Status
- **Dump File**: `esp32c3_dump.bin`
- **File Size**: 4,194,304 bytes (4.0 MiB exact)
- **SHA-256**: `8d1970e78007f18975c255c625c37bccf2a5cfa7d76eff04f3af731fea3bb77a`
- **Image Magic at `0x0000`**: `0xE9` (Valid ESP image header)
- **Extended Header Chip ID**: `0x0005` (ESP32-C3 SoC)
- **Partition Table Magic at `0x8000`**: `0x50AA` (Standard ESP-IDF partition table)
- **Flash Encryption**: **Disabled** (Flags: `0x00000000`, entropy consistent with unencrypted code/data, standard bootloader/app magic visible across all segments)
- **Rollback Guarantee**: Unencrypted full SPI flash image archived at `work/orig/esp32c3_dump.bin.sha256`. Bit-accurate restoration via ESP32-C3 bootloader is 100% supported.

---

## 2. Partition Table Map
Extracted from partition table at offset `0x008000` (`work/parts/partition_table.bin`):

| Partition | Type | Subtype | Flash Offset | Size (Hex) | Size (Bytes) | SHA-256 (first 16 hex) | Content / Format Summary |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `bootloader` | - | - | `0x000000` | `0x008000` | 32,768 | `3f990710609337ff...` | 2nd-stage bootloader (ESP-IDF) |
| `ptable` | - | - | `0x008000` | `0x001000` | 4,096 | `36526eb57bc6bcda...` | Partition table & MD5 checksum |
| `nvs` | `0x01` (data) | `0x02` (nvs) | `0x009000` | `0x004000` | 16,384 | `8e448b87695ed431...` | System NVS: `nvs.net80211`, `phy` cal |
| `otadata` | `0x01` (data) | `0x00` (ota) | `0x00D000` | `0x002000` | 8,192 | `a1ed149677f974e7...` | OTA selection records (seq=2 active) |
| `phy_init` | `0x01` (data) | `0x01` (phy) | `0x00F000` | `0x001000` | 4,096 | `f47a8ec3e9aff231...` | RF PHY initialization calibration |
| `ota_0` | `0x00` (app) | `0x10` (ota0) | `0x010000` | `0x140000` | 1,310,720 | `5c2802292a05b926...` | Inactive app slot (built Nov 21 2024) |
| `ota_1` | `0x00` (app) | `0x11` (ota1) | `0x150000` | `0x140000` | 1,310,720 | `0a9b13c2dc770826...` | **Active app slot (built Mar 5 2025)** |
| `usercfg` | `0x01` (data) | `0x02` (nvs) | `0x290000` | `0x004000` | 16,384 | `17bf1e5801e868ed...` | User NVS: schedules, plans, timezone |
| `fac_data` | `0x01` (data) | `0x02` (nvs) | `0x294000` | `0x002000` | 8,192 | `cf80a558fa2b7b22...` | Factory configuration data |
| `storage` | `0x01` (data) | `0x02` (nvs) | `0x296000` | `0x010000` | 65,536 | `d199961a0565a36b...` | SPIFFS filesystem |
| `historydata` | `0x01` (data) | `0x02` (nvs) | `0x2A6000` | `0x058000` | 360,448 | `f6e51a32628d7754...` | Feeding and device event history log |
| `log` | `0x01` (data) | `0x02` (nvs) | `0x2FE000` | `0x000400` | 1,024 | `5f4ecdb7b71c3e40...` | Crash / panic log storage (clean/empty) |
| `custom_data` | `0x01` (data) | `0x02` (nvs) | `0x2FF000` | `0x100000` | 1,048,576 | `b2812366709fc3d7...` | Custom audio: RIFF WAVE recorded voice |

### Unallocated Gaps
- `gap_2FE400_2FF000`: 3,072 bytes (All `0xFF`)
- `gap_3FF000_400000`: 4,096 bytes (All `0xFF`)

---

## 3. Active Application Image Selection & Metadata
From `otadata` analysis:
- **Sector 1 (`0x00D000`)**: `seq = 1`, `state = 2`, `crc = 0x4743989A`
- **Sector 2 (`0x00E000`)**: `seq = 2`, `state = 0xFFFFFFFF`, `crc = 0x55F63774`
- **Active Slot**: **`ota_1`** (`(seq 2 - 1) % 2 = 1`)

### Application Descriptors (`esp_app_desc_t`)
| Field | `ota_0` (Inactive / Previous) | `ota_1` (Active / Latest) |
| :--- | :--- | :--- |
| **Magic** | `0xABCD5432` | `0xABCD5432` |
| **Build Date & Time** | `Nov 21 2024 10:25:37` | `Mar 5 2025 15:05:20` |
| **ESP-IDF Version Commit** | `264e1242` | `264e1242` |
| **ELF SHA-256** | `3aed9577946bb88d83434c72688467eac78d7dc2a3bfd4cdf2e749e679ef9882` | `fdee744fad9dbcc1775669bb45289ef73cd8b012af71cf78362768d3e5c90093` |
| **Firmware Version (Strings)**| `v1.2.x` | **`v1.2.5`** |
| **Hardware Model Identity** | `PPF-R361S` / `PPF-R361S-WUS_US` | **`PPF-R361S-WUS_US`** |
| **VeSync Cloud Model ID** | `VS_WB_PFM_PPF-R361S-WUS_US` | **`VS_WB_PFM_PPF-R361S-WUS_US`** |

---

## 4. NVS Namespace & Configuration Inventory

### System NVS (`nvs.bin`)
- `phy`: RF calibration parameters (`cal_data`, `cal_mac`, `cal_version`). MAC recorded: `94:A9:90:4C:18:D8`.
- `nvs.net80211`: Wi-Fi parameters (`country`, `ap.chan`, `ap.sndchan`).

### User NVS (`usercfg.bin`)
- `sche_cfg_0`, `sche_cfg_1`: Feeding plan schedule definitions (meal times, portion quantities, repetition weekday masks).
- `sch_param`: Stored feeding plan metadata (contains active plan names: `"Feeding Plan"`, `"Prueba"`).
- `sche_tb_mod`: Timezone string (configured as `"America/Bogota"`).
- `feed_param`: Feeding execution state & portion-to-gram conversion weights.
- `otaSubDev`: Coprocessor / sub-device OTA status records.
- `prd_cfg_data`: Product hardware profile and configuration flags.
- `todo_list`: Pending asynchronous synchronization tasks.

---

## 5. Carved Assets & Subsystem Artifacts
1. **Recorded Meal Call Audio**:
   - Location: Flash offset `0x2FF000` (`custom_data.bin`).
   - Format: Standard **RIFF WAVE**, Mono 16-bit PCM, **32,000 Hz** sample rate.
   - Size: 256,228 bytes (~4.00 seconds of audio).
   - Extracted to: [`work/parts/meal_call.wav`](file:///root/pawsync_oma/work/parts/meal_call.wav).
2. **Sub-MCU Firmware Image**:
   - No separate binary MCU image found in unallocated gaps. The SC95F8766P coprocessor firmware is either factory pre-programmed or managed via structured chunks in `otaSubDev`. No risk of accidental MCU overwrites from ESP32.
