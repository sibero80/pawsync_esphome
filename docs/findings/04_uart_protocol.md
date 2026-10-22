# 04 Dual-MCU UART Protocol Specification: Pawsync PPF-R361S

## 1. Physical Serial Configuration
- **UART Peripheral**: `UART_NUM_0` (or `UART_NUM_1`)
- **Baud Rate**: **`115200`** bps
- **Data Bits**: `8`
- **Parity**: `None`
- **Stop Bits**: `1` (`8N1`)
- **Flow Control**: `None`
- **ESP32-C3 Pins**:
  - **`TXD`**: **`GPIO 19`** (Transmits to `SC95F8766P` RX)
  - **`RXD`**: **`GPIO 18`** (Receives from `SC95F8766P` TX)

---

## 2. Wire Frame Encapsulation
Every frame exchanged between ESP32-C3 and SC95F8766P conforms to the VeSync MCU binary framing:

```text
+------+------+------+---------+---------+----------+-----------------------+
| 0xA5 | Type | Seq  | Len LSB | Len MSB | Checksum | Payload (Len bytes)  |
+------+------+------+---------+---------+----------+-----------------------+
  0      1      2        3         4         5              6..(5+Len)
```

### Field Definitions
- **Byte 0 (`Header Magic`)**: Fixed `0xA5` sync byte.
- **Byte 1 (`Frame Type`)**:
  - `0x02`: Standard Command / Response / Telemetry frame.
  - Bit 4: Async event flag (`0x10`).
  - Bit 5: ACK request flag (`0x20`).
- **Byte 2 (`Sequence Number`)**: 8-bit incrementing packet counter ($0\text{–}255$).
- **Bytes 3–4 (`Payload Length`)**: 16-bit little-endian integer ($N$) representing the length of the trailing payload bytes. Total wire frame size is $N + 6$ bytes.
- **Byte 5 (`Checksum`)**: Checksum byte computed over all bytes of the frame with byte 5 zeroed.

---

## 3. Checksum Algorithm & Verification
The checksum is the **one's complement of the modulo-256 sum** of all frame bytes:
$$\text{Checksum} = \left(\sim \sum_{i \neq 5} \text{Frame}[i]\right) \& \text{ 0xFF}$$

### Python Implementation
```python
def calculate_checksum(frame_bytes: bytearray) -> int:
    """Computes the 1-byte frame checksum (byte 5 is treated as 0)."""
    frame_copy = bytearray(frame_bytes)
    frame_copy[5] = 0
    total = sum(frame_copy) & 0xFF
    return (~total) & 0xFF

def verify_frame(frame_bytes: bytes) -> bool:
    """A valid frame sums to 0xFF modulo 256 across all N+6 bytes."""
    if len(frame_bytes) < 6 or frame_bytes[0] != 0xA5:
        return False
    return (sum(frame_bytes) & 0xFF) == 0xFF
```

---

## 4. Internal Payload & KLV Architecture
The payload ($N$ bytes starting at frame byte 6) contains an inner command header followed by Key-Length-Value (KLV) fields:

```text
+---------+-------------+-------------+--------+-----------------------+
| Sub-Cmd | Opcode LSB  | Opcode MSB  | Status | KLV Data Elements ... |
+---------+-------------+-------------+--------+-----------------------+
    0            1             2          3           4..(N-1)
```

- **Byte 0 (`Sub-Cmd`)**: Sub-command / transaction category (`0x04` = normal command, `0x05` = ack/query, `0x14` = status/telemetry).
- **Bytes 1–2 (`Opcode`)**: 16-bit little-endian command ID (e.g., `0x5018`, `0x5593`, `0x55A3`).
- **Byte 3 (`Status`)**: Result code (`0x00` = Success, non-zero = Error / Busy).
- **Bytes 4+ (`KLV Elements`)**: Packed TLV entries.

### KLV Data Element Encoding
Each KLV element inside the payload is structured as:
```text
+--------+---------+---------+--------------------+
| Key ID | Len LSB | Len MSB | Value (Len bytes)  |
+--------+---------+---------+--------------------+
    0         1         2          3..(2+Len)
```
- **Byte 0 (`Key ID`)**: 8-bit unsigned key identifier.
- **Bytes 1–2 (`Length`)**: 16-bit little-endian length of the value.
- **Bytes 3+ (`Value`)**: Payload bytes.
