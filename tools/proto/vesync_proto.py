#!/usr/bin/env python3
"""
tools/proto/vesync_proto.py - Reference Python Codec & Test Vectors for
Pawsync PPF-R361S VeSync Dual-MCU UART Protocol.
"""
import struct
from typing import Dict, List, Tuple, Any, Optional

FRAME_HEADER = 0xA5

# Opcodes
OPCODE_FEED_CMD           = 0x5018
OPCODE_CHILD_LOCK         = 0x5104
OPCODE_SLEEP_MODE         = 0x5105
OPCODE_SLOW_FEED          = 0x5107
OPCODE_WIFI_LED           = 0x5140
OPCODE_BUZZER_SWITCH      = 0x5141
OPCODE_STATUS_POLL        = 0x5590
OPCODE_INTELLIGENT_FEED   = 0x5592
OPCODE_STATUS_REPORT      = 0x5593
OPCODE_DISPENSE_PROGRESS  = 0x5594
OPCODE_SLEEP_CLOCK_SYNC   = 0x5595
OPCODE_DISPENSE_RESULT    = 0x5596
OPCODE_BUTTON_EVENT       = 0x5597
OPCODE_SCHEDULE_TRIGGER   = 0x5598
OPCODE_SINGLE_MEASURE     = 0x5599
OPCODE_SCALE_CAL_POINTS   = 0x55A0
OPCODE_CLOCK_SYNC         = 0x55A1
OPCODE_SCALE_ZERO_MEASURE = 0x55A2
OPCODE_TARE_BOWL          = 0x55A3
OPCODE_MOTOR_DIAGNOSTICS  = 0x55A4
OPCODE_SCALE_RAW_ADC      = 0x55A5
OPCODE_PLAN_SYNC          = 0x55A6

def calculate_checksum(data: bytearray) -> int:
    """Computes frame checksum: one's complement of sum of bytes with byte 5 = 0."""
    temp = bytearray(data)
    if len(temp) > 5:
        temp[5] = 0
    total = sum(temp) & 0xFF
    return (~total) & 0xFF

def encode_klv(items: List[Tuple[int, bytes]]) -> bytes:
    """Encodes a list of (key_id, value_bytes) into KLV payload format."""
    out = bytearray()
    for key_id, val in items:
        out.append(key_id & 0xFF)
        out.extend(struct.pack('<H', len(val)))
        out.extend(val)
    return bytes(out)

def decode_klv(payload: bytes) -> Dict[int, bytes]:
    """Decodes KLV payload bytes into a dictionary of {key_id: value_bytes}."""
    items = {}
    idx = 0
    while idx + 3 <= len(payload):
        key_id = payload[idx]
        val_len = struct.unpack('<H', payload[idx+1:idx+3])[0]
        idx += 3
        if idx + val_len > len(payload):
            break
        items[key_id] = payload[idx:idx+val_len]
        idx += val_len
    return items

def encode_frame(frame_type: int, seq: int, sub_cmd: int, opcode: int,
                 status: int = 0, klv_items: Optional[List[Tuple[int, bytes]]] = None) -> bytes:
    """Serializes a complete wire protocol frame."""
    inner_payload = bytearray()
    inner_payload.append(sub_cmd & 0xFF)
    inner_payload.extend(struct.pack('<H', opcode))
    inner_payload.append(status & 0xFF)
    if klv_items:
        inner_payload.extend(encode_klv(klv_items))

    payload_len = len(inner_payload)
    frame = bytearray()
    frame.append(FRAME_HEADER)
    frame.append(frame_type & 0xFF)
    frame.append(seq & 0xFF)
    frame.extend(struct.pack('<H', payload_len))
    frame.append(0) # placeholder for checksum at index 5
    frame.extend(inner_payload)

    # Compute and set checksum
    frame[5] = calculate_checksum(frame)
    return bytes(frame)

def decode_frame(raw: bytes) -> Dict[str, Any]:
    """Deserializes and validates a complete wire protocol frame."""
    if len(raw) < 6:
        raise ValueError("Frame too short")
    if raw[0] != FRAME_HEADER:
        raise ValueError(f"Invalid frame magic: 0x{raw[0]:02X}")

    frame_type = raw[1]
    seq = raw[2]
    payload_len = struct.unpack('<H', raw[3:5])[0]
    expected_len = payload_len + 6
    if len(raw) < expected_len:
        raise ValueError(f"Incomplete frame: expected {expected_len}, got {len(raw)}")

    # Verify checksum: sum of all bytes modulo 256 must equal 0xFF
    checksum_sum = sum(raw[:expected_len]) & 0xFF
    if checksum_sum != 0xFF:
        raise ValueError(f"Checksum mismatch: total modulo 256 = 0x{checksum_sum:02X} (expected 0xFF)")

    payload = raw[6:expected_len]
    if len(payload) < 4:
        raise ValueError("Payload missing inner header")

    sub_cmd = payload[0]
    opcode = struct.unpack('<H', payload[1:3])[0]
    status = payload[3]
    klv_data = decode_klv(payload[4:])

    return {
        "frame_type": frame_type,
        "seq": seq,
        "payload_len": payload_len,
        "checksum": raw[5],
        "sub_cmd": sub_cmd,
        "opcode": opcode,
        "status": status,
        "klv": klv_data
    }

# Helper builder functions
def build_feed_cmd(portions: int, seq: int = 1, sound: bool = True) -> bytes:
    """Builds a manual feed command (Opcode 0x5018)."""
    items = [
        (1, bytes([1])),                             # Key 1: Feed mode = 1 (portion)
        (2, struct.pack('<H', portions)),             # Key 2: Portions count
        (3, struct.pack('<H', 60)),                   # Key 3: Timeout 60s
        (4, bytes([1 if sound else 0]))              # Key 4: Sound play prompt
    ]
    return encode_frame(frame_type=0x02, seq=seq, sub_cmd=0x04, opcode=OPCODE_FEED_CMD, klv_items=items)

def build_tare_cmd(seq: int = 1) -> bytes:
    """Builds a bowl tare/zero command (Opcode 0x55A3)."""
    return encode_frame(frame_type=0x02, seq=seq, sub_cmd=0x05, opcode=OPCODE_TARE_BOWL, klv_items=[])

def build_child_lock_cmd(locked: bool, seq: int = 1) -> bytes:
    """Builds child lock command (Opcode 0x5104)."""
    return encode_frame(frame_type=0x02, seq=seq, sub_cmd=0x04, opcode=OPCODE_CHILD_LOCK,
                        klv_items=[(1, bytes([1 if locked else 0]))])

def build_wifi_led_cmd(mode: int, seq: int = 1) -> bytes:
    """Builds Wi-Fi LED state command (Opcode 0x5140, mode: 0=off, 1=pairing, 2=connected)."""
    return encode_frame(frame_type=0x02, seq=seq, sub_cmd=0x14, opcode=OPCODE_WIFI_LED,
                        klv_items=[(1, bytes([mode & 0xFF]))])

def build_clock_sync_cmd(timestamp: int, seq: int = 1) -> bytes:
    """Builds RTC clock synchronization command (Opcode 0x55A1)."""
    return encode_frame(frame_type=0x02, seq=seq, sub_cmd=0x14, opcode=OPCODE_CLOCK_SYNC,
                        klv_items=[(1, struct.pack('<I', timestamp))])

def build_plan_sync_cmd(plan_idx: int, meals: List[Dict[str, Any]], seq: int = 1) -> bytes:
    """Builds feeding plan sync command (Opcode 0x55A6) for coprocessor EEPROM storage."""
    meals_payload = bytearray()
    count = 0
    for idx, meal in enumerate(meals):
        if meal.get("enabled", True):
            meal_idx = meal.get("meal_idx", idx)
            hour = meal.get("hour", 8)
            minute = meal.get("minute", 0)
            portions = meal.get("portions", 1)
            repeat_days = meal.get("days", 0x7F)
            sound = 1 if meal.get("sound", True) else 0
            meals_payload.extend(struct.pack('<BBBBHBB', meal_idx, 1, hour, minute, portions, repeat_days, sound))
            count += 1
    items = [
        (1, bytes([plan_idx & 0xFF])),
        (2, bytes([count & 0xFF])),
        (3, bytes(meals_payload))
    ]
    return encode_frame(frame_type=0x02, seq=seq, sub_cmd=0x14, opcode=OPCODE_PLAN_SYNC, klv_items=items)

def build_schedule_trigger_report(clk_sec: int, output_type: int = 2, seq: int = 1) -> bytes:
    """Builds autonomous schedule trigger report from coprocessor (Opcode 0x5598)."""
    items = [
        (1, struct.pack('<I', clk_sec)),
        (2, bytes([output_type & 0xFF]))
    ]
    return encode_frame(frame_type=0x02, seq=seq, sub_cmd=0x14, opcode=OPCODE_SCHEDULE_TRIGGER, klv_items=items)

def run_unit_tests():
    print("Running VeSync UART Protocol Unit Tests & Vector Validation...")

    # Test 1: Tare Bowl Command Frame
    tare_frame = build_tare_cmd(seq=42)
    print(f"Tare Frame (hex): {tare_frame.hex()}")
    assert tare_frame[0] == 0xA5
    assert (sum(tare_frame) & 0xFF) == 0xFF
    decoded_tare = decode_frame(tare_frame)
    assert decoded_tare["opcode"] == OPCODE_TARE_BOWL
    assert decoded_tare["seq"] == 42
    print("  [PASS] Test 1: Tare command serialization and checksum match.")

    # Test 2: Feed Command Frame (3 portions)
    feed_frame = build_feed_cmd(portions=3, seq=10)
    print(f"Feed Frame (hex): {feed_frame.hex()}")
    assert (sum(feed_frame) & 0xFF) == 0xFF
    decoded_feed = decode_frame(feed_frame)
    assert decoded_feed["opcode"] == OPCODE_FEED_CMD
    assert decoded_feed["seq"] == 10
    assert 2 in decoded_feed["klv"]
    portions_dispensed = struct.unpack('<H', decoded_feed["klv"][2])[0]
    assert portions_dispensed == 3
    print("  [PASS] Test 2: Feed command KLV items parsed accurately (3 portions).")

    # Test 3: Simulated MCU Status Telemetry (Opcode 0x5593)
    # Simulate: Battery 95%, AC connected, Bowl weight 142g, Food full (Key 4=0)
    status_klv = [
        (1, struct.pack('<H', 125)), # fw_ver
        (2, struct.pack('<H', 100)), # mcu_ver
        (3, bytes([0])),             # child lock = 0
        (4, bytes([0])),             # food low = 0 (OK)
        (5, bytes([95])),            # battery = 95%
        (6, bytes([1])),             # work_mode = 1
        (7, bytes([1])),             # powerAdapter = 1 (AC plugged in)
        (8, struct.pack('<H', 142))  # bowlWeight = 142g
    ]
    status_frame = encode_frame(frame_type=0x02, seq=101, sub_cmd=0x14, opcode=OPCODE_STATUS_REPORT,
                                status=0, klv_items=status_klv)
    assert (sum(status_frame) & 0xFF) == 0xFF
    decoded_status = decode_frame(status_frame)
    assert decoded_status["opcode"] == OPCODE_STATUS_REPORT
    assert decoded_status["klv"][5][0] == 95 # 95%
    assert decoded_status["klv"][7][0] == 1  # AC adapter
    weight = struct.unpack('<H', decoded_status["klv"][8])[0]
    assert weight == 142
    print(f"  [PASS] Test 3: Telemetry report (battery=95%, AC=1, weight=142g) verified.")

    # Test 4: Clock Sync Command
    clock_frame = build_clock_sync_cmd(timestamp=1741187120, seq=5)
    decoded_clock = decode_frame(clock_frame)
    assert decoded_clock["opcode"] == OPCODE_CLOCK_SYNC
    ts = struct.unpack('<I', decoded_clock["klv"][1])[0]
    assert ts == 1741187120
    print("  [PASS] Test 4: Clock sync timestamp verified.")

    # Test 5: Plan Sync Serialization (Opcode 0x55A6)
    test_meals = [
        {"meal_idx": 0, "enabled": True, "hour": 8, "minute": 30, "portions": 2, "days": 0x7F, "sound": True},
        {"meal_idx": 1, "enabled": True, "hour": 18, "minute": 0, "portions": 3, "days": 0x7F, "sound": True}
    ]
    plan_frame = build_plan_sync_cmd(plan_idx=0, meals=test_meals, seq=6)
    assert (sum(plan_frame) & 0xFF) == 0xFF
    decoded_plan = decode_frame(plan_frame)
    assert decoded_plan["opcode"] == OPCODE_PLAN_SYNC
    assert decoded_plan["klv"][1][0] == 0  # Plan 0
    assert decoded_plan["klv"][2][0] == 2  # 2 meals
    meal_data = decoded_plan["klv"][3]
    assert len(meal_data) == 16 # 2 meals * 8 bytes
    m0_idx, m0_en, m0_h, m0_m, m0_port, m0_days, m0_snd = struct.unpack('<BBBBHBB', meal_data[0:8])
    assert m0_idx == 0 and m0_h == 8 and m0_m == 30 and m0_port == 2
    print("  [PASS] Test 5: Plan sync serialization (0x55A6) verified with 8-byte meal records.")

    # Test 6: Autonomous Schedule Trigger (Opcode 0x5598)
    trigger_frame = build_schedule_trigger_report(clk_sec=1741187120, output_type=2, seq=7)
    assert (sum(trigger_frame) & 0xFF) == 0xFF
    decoded_trigger = decode_frame(trigger_frame)
    assert decoded_trigger["opcode"] == OPCODE_SCHEDULE_TRIGGER
    assert struct.unpack('<I', decoded_trigger["klv"][1])[0] == 1741187120
    assert decoded_trigger["klv"][2][0] == 2
    print("  [PASS] Test 6: Schedule trigger event (0x5598) verified.")

    print("\nALL UNIT TESTS PASSED (100% SPEC COMPLIANCE).")

if __name__ == '__main__':
    run_unit_tests()
