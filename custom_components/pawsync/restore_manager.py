"""Automated post-adoption cloud settings restoration and replay engine.

Replays harvested PawSync/VeSync cloud configurations into newly adopted ESPHome feeders:
- Exact feeding schedules via esphome.<feeder>_set_meal_schedule
- Kibble portion density via number.<feeder>_grams_per_portion_kibble_calibration
- Intelligent feeding (leftover deduction), slow feed, and sleep mode switches
- Food hopper surplus level via number.<feeder>_tank_refill_weight
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .backup_manager import load_cloud_backup, sanitize_mac
from .const import CONF_HOST, CONF_SELECTED_FEEDER, DOMAIN

_LOGGER = logging.getLogger(__name__)


def convert_repeat_to_days_str(repeat: int | str | None) -> str:
    """Convert cloud repeat integer or mask to ESPHome days string representation."""
    if repeat is None or repeat == 127 or str(repeat).lower() in ("all", "daily", "everyday"):
        return "All"
    if repeat == 0x3E or repeat == 62:
        return "Weekdays"
    if repeat == 0x41 or repeat == 65:
        return "Weekends"

    if isinstance(repeat, int):
        # Bitmask: Sunday=bit 0 (0x01), Monday=bit 1 (0x02), ..., Saturday=bit 6 (0x40)
        days: list[str] = []
        if repeat & 0x02:
            days.append("Mo")
        if repeat & 0x04:
            days.append("Tu")
        if repeat & 0x08:
            days.append("We")
        if repeat & 0x10:
            days.append("Th")
        if repeat & 0x20:
            days.append("Fr")
        if repeat & 0x40:
            days.append("Sa")
        if repeat & 0x01:
            days.append("Su")

        if len(days) == 7:
            return "All"
        if days:
            return ",".join(days)

    return "All"


def format_timesec_to_hhmm(timesec: int | None) -> str:
    """Format seconds past midnight to 24-hour HH:MM string."""
    if timesec is None:
        return "08:00"
    timesec = timesec % 86400
    hours = timesec // 3600
    minutes = (timesec % 3600) // 60
    return f"{hours:02d}:{minutes:02d}"


def find_esphome_service(
    hass: HomeAssistant,
    action_suffix: str,
    device_slug: str = "",
    feeder_slug: str = "",
) -> str | None:
    """Find registered ESPHome service ending in action_suffix (e.g. set_meal_schedule)."""
    target_slug = feeder_slug or device_slug
    esphome_services = hass.services.async_services().get("esphome", {})
    target_suffix = f"_{action_suffix}"

    # 1. Exact match with target_slug
    if target_slug:
        candidate = f"{target_slug}{target_suffix}"
        if candidate in esphome_services:
            return candidate

    # 2. Check if any service contains target_slug or mac suffix and ends with target_suffix
    for s_name in esphome_services:
        if s_name.endswith(action_suffix):
            if not target_slug or target_slug in s_name:
                return s_name

    # 3. Fallback: if only one service ends with action_suffix, return it
    candidates = [s for s in esphome_services if s.endswith(action_suffix)]
    if len(candidates) == 1:
        return candidates[0]

    return None


async def async_restore_cloud_settings(
    hass: HomeAssistant,
    entry: ConfigEntry,
    backup_data: dict[str, Any] | None = None,
) -> bool:
    """Replay harvested cloud configuration into adopted ESPHome feeder."""
    feeder_info = entry.data.get("feeder_info", {})
    mac = feeder_info.get("mac") or entry.data.get("mac_address") or ""
    clean_mac = sanitize_mac(mac)
    name_raw = feeder_info.get("name") or (entry.title if hasattr(entry, "title") and isinstance(entry.title, str) else "") or "pawsync_feeder"
    name = str(name_raw)
    feeder_slug = re.sub(r"[^a-zA-Z0-9_]+", "_", name.lower()).strip("_")

    # 1. Load cloud backup if not directly supplied
    profile = backup_data
    if not profile:
        profile = entry.data.get("cloud_profile")
    if not profile and mac:
        if hasattr(hass, "async_add_executor_job") and callable(hass.async_add_executor_job):
            profile = await hass.async_add_executor_job(load_cloud_backup, hass, mac)
        else:
            profile = load_cloud_backup(hass, mac)

    if not profile:
        _LOGGER.warning("No cloud settings backup found for feeder %s (MAC: %s)", name, mac)
        return False

    single_weight_g = float(profile.get("single_weight_g") or 8.0)
    if single_weight_g < 3.0:
        single_weight_g = 8.0

    intelligent_feeding = bool(profile.get("intelligent_feeding", False))
    slow_feed = bool(profile.get("slow_feed", False))
    sleep_mode = bool(profile.get("sleep_mode", False))
    bucket_surplus = profile.get("bucket_surplus")

    _LOGGER.info(
        "Restoring cloud settings for %s: singleWeight_g=%.1f, smartFeeding=%s, slowFeed=%s, sleepMode=%s",
        name,
        single_weight_g,
        intelligent_feeding,
        slow_feed,
        sleep_mode,
    )

    # 2. Restore Kibble Calibration Density (number entity)
    await _async_set_entity_value(
        hass=hass,
        domain="number",
        keyword="grams_per_portion",
        value=single_weight_g,
        feeder_slug=feeder_slug,
        clean_mac=clean_mac,
    )

    # 3. Restore Feature Switches
    await _async_set_switch_state(
        hass=hass,
        keyword="intelligent_feeding",
        turn_on=intelligent_feeding,
        feeder_slug=feeder_slug,
        clean_mac=clean_mac,
    )
    await _async_set_switch_state(
        hass=hass,
        keyword="slow_feed",
        turn_on=slow_feed,
        feeder_slug=feeder_slug,
        clean_mac=clean_mac,
    )
    await _async_set_switch_state(
        hass=hass,
        keyword="sleep_mode",
        turn_on=sleep_mode,
        feeder_slug=feeder_slug,
        clean_mac=clean_mac,
    )

    # 4. Restore Tank Surplus (if positive number)
    if bucket_surplus is not None and isinstance(bucket_surplus, (int, float)) and bucket_surplus > 0:
        await _async_set_entity_value(
            hass=hass,
            domain="number",
            keyword="tank_refill_weight",
            value=float(bucket_surplus),
            feeder_slug=feeder_slug,
            clean_mac=clean_mac,
        )

    # 5. Restore Feeding Plans and Meal Schedules
    plans = profile.get("plans", [])
    service_name = find_esphome_service(hass, "set_meal_schedule", feeder_slug=feeder_slug)

    # Retry loop if service not yet discovered (early HA startup race)
    if not service_name and plans:
        for attempt in range(1, 6):
            await asyncio.sleep(2.0)
            service_name = find_esphome_service(hass, "set_meal_schedule", feeder_slug=feeder_slug)
            if service_name:
                _LOGGER.debug(
                    "ESPHome set_meal_schedule service discovered on attempt %d for %s: %s",
                    attempt,
                    feeder_slug,
                    service_name,
                )
                break

    restored_meals_count = 0
    if service_name:
        for plan_idx, plan in enumerate(plans, start=1):
            if plan_idx > 7:
                break
            # Find meals in plan or plan detail
            detail = plan.get("detail", {}) if isinstance(plan.get("detail"), dict) else {}
            meals = (
                detail.get("meals")
                or detail.get("mealList")
                or plan.get("meals")
                or plan.get("mealList")
                or []
            )
            if not isinstance(meals, list):
                continue

            for meal_idx, meal in enumerate(meals, start=1):
                if meal_idx > 10:
                    break
                timesec = meal.get("timeSec")
                meal_time = format_timesec_to_hhmm(timesec)
                target_weight_g = float(meal.get("weight") or 16.0)
                portions = max(1, min(20, round(target_weight_g / single_weight_g)))
                days_str = convert_repeat_to_days_str(meal.get("repeat", 127))
                enabled = bool(meal.get("enabled", True))
                sound = bool(meal.get("sound", True))

                try:
                    await hass.services.async_call(
                        "esphome",
                        service_name,
                        {
                            "plan": plan_idx,
                            "meal": meal_idx,
                            "enabled": enabled,
                            "meal_time": meal_time,
                            "days": days_str,
                            "portions": portions,
                            "sound": sound,
                        },
                        blocking=True,
                    )
                    restored_meals_count += 1
                except Exception as err:
                    _LOGGER.warning(
                        "Could not restore meal %d (plan %d) via %s: %s",
                        meal_idx,
                        plan_idx,
                        service_name,
                        err,
                    )
    else:
        _LOGGER.debug(
            "ESPHome set_meal_schedule service not yet discovered for %s; meals will sync when service is ready",
            feeder_slug,
        )

    _LOGGER.info(
        "Successfully restored cloud profile for %s (singleWeight=%.1fg, meals=%d)",
        name,
        single_weight_g,
        restored_meals_count,
    )

    # Mark cloud profile as restored to prevent overwriting user modifications on future reloads
    if entry is not None and hasattr(hass, "config_entries") and hasattr(hass.config_entries, "async_update_entry"):
        entry_data = getattr(entry, "data", {})
        if isinstance(entry_data, dict) and not entry_data.get("cloud_profile_restored"):
            new_data = dict(entry_data)
            new_data["cloud_profile_restored"] = True
            hass.config_entries.async_update_entry(entry, data=new_data)

    return True


async def _async_set_entity_value(
    hass: HomeAssistant,
    domain: str,
    keyword: str,
    value: float,
    feeder_slug: str,
    clean_mac: str,
) -> None:
    """Helper to locate and call number.set_value on matching entity."""
    entity_id = _resolve_entity_id(hass, domain, keyword, feeder_slug, clean_mac)
    if entity_id:
        try:
            await hass.services.async_call(
                domain,
                "set_value",
                {"entity_id": entity_id, "value": value},
                blocking=True,
            )
            _LOGGER.debug("Set %s to %s", entity_id, value)
        except Exception as err:
            _LOGGER.debug("Could not call %s.set_value on %s: %s", domain, entity_id, err)


async def _async_set_switch_state(
    hass: HomeAssistant,
    keyword: str,
    turn_on: bool,
    feeder_slug: str,
    clean_mac: str,
) -> None:
    """Helper to locate and call switch.turn_on/turn_off on matching entity."""
    entity_id = _resolve_entity_id(hass, "switch", keyword, feeder_slug, clean_mac)
    if entity_id:
        service = "turn_on" if turn_on else "turn_off"
        try:
            await hass.services.async_call(
                "switch",
                service,
                {"entity_id": entity_id},
                blocking=True,
            )
            _LOGGER.debug("Called switch.%s on %s", service, entity_id)
        except Exception as err:
            _LOGGER.debug("Could not call switch.%s on %s: %s", service, entity_id, err)


def _resolve_entity_id(
    hass: HomeAssistant,
    domain: str,
    keyword: str,
    feeder_slug: str,
    clean_mac: str,
) -> str | None:
    """Locate matching entity ID in state machine."""
    entity_ids = hass.states.async_entity_ids(domain)
    for eid in entity_ids:
        eid_lower = eid.lower()
        if keyword in eid_lower:
            if not feeder_slug and not clean_mac:
                return eid
            if feeder_slug and feeder_slug in eid_lower:
                return eid
            if clean_mac and clean_mac in eid_lower:
                return eid

    # Fallback to candidate entity ID if single matching keyword exists
    keyword_matches = [e for e in entity_ids if keyword in e.lower()]
    if len(keyword_matches) == 1:
        return keyword_matches[0]

    return None
