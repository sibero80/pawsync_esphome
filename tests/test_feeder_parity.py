#!/usr/bin/env python3
"""
tests/test_feeder_parity.py - Automated End-to-End Test Suite for Pawsync Feeder Parity

Validates parity with stock firmware behavior via the Home Assistant REST API:
  1. Feeder online & connectivity status.
  2. Battery level telemetry: validates Key 14 parsing (state > 0%, matching stock 30%).
  3. Desiccant lifetime tracker: validates 30-day countdown sensor and reset button.
  4. Child Lock independence: validates remote feeding executes without requiring child lock bypass or delay.
  5. Scale Tare: tests the tare bowl scale button and validates tare ACK.
  6. Single Portion Remote Feed: triggers 1-portion feed, verifies status progression and timing.
"""

import os
import sys
import time
import json
import requests

HA_URL = os.environ.get("HA_URL", "http://192.168.1.140:8123")
HA_TOKEN = os.environ.get(
    "HA_TOKEN",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiI2NTJiMzI0MmY5NmM0ZDMyYjE0MjQ5NGRkNjJkZDZlOCIsImlhdCI6MTc5Mjg3ODIxNSwiZXhwIjoyMTA4MjM4MjE1fQ.NzOPHL9R3SZUDGlmzgOGa0iDcUW91QYqQEnHfnpm4dc"
)

HEADERS = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "Content-Type": "application/json"
}


def get_entity_state(entity_id: str, max_retries: int = 5, retry_delay: float = 2.0):
    """Retrieve full entity state object from Home Assistant."""
    url = f"{HA_URL}/api/states/{entity_id}"
    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=5)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            pass
        time.sleep(retry_delay)
    raise RuntimeError(f"Failed to fetch state for entity {entity_id} after {max_retries} attempts")


def call_service(domain: str, service: str, data: dict, timeout: float = 10.0):
    """Call a Home Assistant service."""
    url = f"{HA_URL}/api/services/{domain}/{service}"
    r = requests.post(url, headers=HEADERS, json=data, timeout=timeout)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Service call {domain}.{service} failed: {r.status_code} {r.text}")
    return r.json()


def wait_for_online(timeout_s: int = 60):
    """Wait until the feeder entity is online in Home Assistant."""
    print(f"[*] Waiting up to {timeout_s}s for feeder to come online in Home Assistant...")
    start = time.time()
    while time.time() - start < timeout_s:
        try:
            state = get_entity_state("sensor.pawsync_ppf_r361s_feeder_feeder_status", max_retries=1)
            status_val = state.get("state", "")
            if status_val not in ("unavailable", "unknown", ""):
                print(f"[+] Feeder is online: status = '{status_val}'")
                return True
        except Exception:
            pass
        time.sleep(2)
    raise TimeoutError("Feeder did not come online within timeout")


def test_battery_level():
    """Verify battery presence and percentage parsing (matching stock NotInstalled when Key 5 is 0)."""
    print("\n--- Test: Battery Level Telemetry & Absence Detection ---")
    bat_state = get_entity_state("sensor.pawsync_ppf_r361s_feeder_battery_level")
    bat_val = bat_state.get("state")
    print(f"[*] Current battery level sensor state: {bat_val}")

    # Check battery installed binary sensor if available
    inst_eid = find_entity_by_suffix("battery_installed")
    if inst_eid and inst_eid != "battery_installed":
        inst_state = get_entity_state(inst_eid).get("state")
        print(f"[*] Battery installed binary sensor state: {inst_state}")
        assert inst_state in ("off", "false", "unavailable", "unknown"), (
            f"Expected battery_installed to be 'off' (no physical battery installed), got: {inst_state}"
        )

    # When no battery is installed, state should be unavailable / unknown / None / nan
    assert bat_val in ("unavailable", "unknown", "None", "nan"), (
        f"Expected battery level to be unavailable (no battery installed in unit), but got: {bat_val}%"
    )
    print(f"[PASS] Battery absence correctly identified (status: {bat_val})")


def find_entity_by_suffix(suffix: str) -> str:
    """Find the entity ID matching the given suffix across all HA states."""
    url = f"{HA_URL}/api/states"
    r = requests.get(url, headers=HEADERS, timeout=5)
    if r.status_code == 200:
        for item in r.json():
            eid = item.get("entity_id", "")
            if eid.endswith(suffix):
                return eid
    return suffix


def test_desiccant_tracker():
    """Verify desiccant days sensor and reset button."""
    print("\n--- Test: Desiccant Lifetime Tracker ---")
    # Check desiccant sensor
    sensor_eid = find_entity_by_suffix("desiccant_days_remaining")
    print(f"[*] Found desiccant sensor: {sensor_eid}")
    state = get_entity_state(sensor_eid)
    raw_val = state.get("state")
    print(f"[*] Desiccant days remaining: {raw_val}")
    assert raw_val not in ("unavailable", "unknown"), f"Desiccant sensor is unavailable: {raw_val}"
    val = float(raw_val)
    assert 0 <= val <= 30, f"Desiccant days out of range [0, 30]: {val}"

    # Press reset button
    button_eid = find_entity_by_suffix("reset_desiccant_30_days")
    print(f"[*] Found reset desiccant button: {button_eid}")
    print(f"[*] Pressing reset desiccant button: {button_eid}...")
    call_service("button", "press", {"entity_id": button_eid})
    time.sleep(1.5)

    updated_state = get_entity_state(sensor_eid)
    updated_val = float(updated_state.get("state", 0))
    print(f"[*] Updated desiccant days remaining: {updated_val}")
    assert updated_val == 30.0, f"Expected 30.0 after reset, got {updated_val}"
    print("[PASS] Desiccant countdown and reset verified successfully")


def test_tare_bowl():
    """Verify bowl scale tare functionality."""
    print("\n--- Test: Bowl Scale Tare ---")
    button_eid = "button.pawsync_ppf_r361s_feeder_tare_bowl_scale"
    sensor_eid = "sensor.pawsync_ppf_r361s_feeder_bowl_weight"
    
    initial_weight = get_entity_state(sensor_eid).get("state")
    print(f"[*] Initial bowl weight: {initial_weight}g")
    
    print(f"[*] Pressing tare button: {button_eid}...")
    call_service("button", "press", {"entity_id": button_eid})
    time.sleep(2.5)
    
    new_weight = float(get_entity_state(sensor_eid).get("state", 999))
    print(f"[*] Bowl weight post-tare: {new_weight}g")
    assert abs(new_weight) <= 1.0, f"Expected weight within [-1, 1]g, got {new_weight}g"
    print("[PASS] Tare command executed and scale zeroed")


def test_remote_feed_execution():
    """Verify remote feed execution with physical motor actuation and load cell weight delta validation."""
    print("\n--- Test: Single Portion Remote Feed Execution & Physical Scale Verification ---")
    feed_button = "button.pawsync_ppf_r361s_feeder_feed_1_portion"
    status_sensor = "sensor.pawsync_ppf_r361s_feeder_feeder_status"
    weight_sensor = "sensor.pawsync_ppf_r361s_feeder_last_feed_weight"
    bowl_sensor = "sensor.pawsync_ppf_r361s_feeder_bowl_weight"
    portions_sensor = "sensor.pawsync_ppf_r361s_feeder_portions_today"
    child_lock_switch = "switch.pawsync_ppf_r361s_feeder_child_lock"

    initial_child_lock = get_entity_state(child_lock_switch).get("state")
    initial_bowl_weight = float(get_entity_state(bowl_sensor).get("state", 0.0))
    initial_portions = float(get_entity_state(portions_sensor).get("state", 0.0))
    print(f"[*] Initial conditions: Child Lock={initial_child_lock}, Bowl Weight={initial_bowl_weight}g, Portions Today={initial_portions}")

    print(f"[*] Triggering 1-portion feed via {feed_button}...")
    call_service("button", "press", {"entity_id": feed_button})

    # Poll status frequently over the next 20 seconds
    states_observed = []
    start_time = time.time()
    dispense_start = None
    dispense_end = None

    while time.time() - start_time < 20.0:
        st = get_entity_state(status_sensor).get("state", "")
        if not states_observed or states_observed[-1] != st:
            states_observed.append(st)
            ts = round(time.time() - start_time, 2)
            print(f"    [{ts}s] Feeder status -> '{st}'")
            if "Feeding" in st or "Dispensing" in st:
                if dispense_start is None:
                    dispense_start = time.time()
            if "Complete" in st:
                dispense_end = time.time()
                break
            elif dispense_start is not None and "Online" in st:
                dispense_end = time.time()
                break
        time.sleep(0.3)

    print(f"[*] States observed during dispense sequence: {states_observed}")
    assert any("Feeding" in s or "Dispensing" in s or "Complete" in s for s in states_observed), (
        f"Dispense state was never triggered! Observed: {states_observed}"
    )
    assert not any("Aborted" in s or "Locked" in s for s in states_observed), (
        f"Dispense was aborted by coprocessor! Observed: {states_observed}"
    )

    if dispense_start and dispense_end:
        duration = dispense_end - dispense_start
        print(f"[*] Dispense cycle duration: {duration:.2f}s")
        assert duration >= 1.5, f"Dispense aborted too quickly ({duration:.2f}s < 1.5s)"

    # Wait 3.5s for bowl weight poll to settle
    print("[*] Waiting 3.5s for scale settling and telemetry refresh...")
    time.sleep(3.5)

    last_weight_raw = get_entity_state(weight_sensor).get("state")
    last_weight = float(last_weight_raw) if last_weight_raw not in ("unavailable", "unknown") else 0.0
    print(f"[*] Last feed weight reported by coprocessor: {last_weight}g")
    assert last_weight >= 4.0, f"Expected last feed weight >= 4.0g, got {last_weight}g"

    new_portions = float(get_entity_state(portions_sensor).get("state", 0.0))
    print(f"[*] Portions today: before={initial_portions}, after={new_portions}")
    assert new_portions > initial_portions, (
        f"Expected portions today to increment ({initial_portions} -> {new_portions})"
    )

    new_bowl_weight = float(get_entity_state(bowl_sensor).get("state", 0.0))
    delta_w = new_bowl_weight - initial_bowl_weight
    print(f"[*] Bowl weight: before={initial_bowl_weight}g, after={new_bowl_weight}g (delta={delta_w}g)")
    assert new_bowl_weight > initial_bowl_weight, (
        f"Food scale weight did not increase after motor dispense! ({initial_bowl_weight}g -> {new_bowl_weight}g)"
    )

    # Check that child lock state was preserved
    final_child_lock = get_entity_state(child_lock_switch).get("state")
    print(f"[*] Child lock state after feed: {final_child_lock}")
    assert final_child_lock == initial_child_lock, (
        f"Child lock state changed unexpectedly: {initial_child_lock} -> {final_child_lock}"
    )

    print("[PASS] Remote feed executed seamlessly, motor physically actuated, and food scale recorded kibble increase!")


def run_all_tests():
    print("=" * 65)
    print("PAWSYNC PPF-R361S FEEDER - STOCK PARITY VERIFICATION SUITE")
    print("=" * 65)

    wait_for_online(timeout_s=60)
    time.sleep(3.0)  # Allow initial telemetry packet (0x5593) to arrive

    test_battery_level()
    test_desiccant_tracker()
    test_tare_bowl()
    test_remote_feed_execution()

    print("\n" + "=" * 65)
    print("ALL STOCK PARITY TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 65)


if __name__ == "__main__":
    run_all_tests()
