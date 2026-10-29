"""The PawSync Smart Pet Feeder Integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .backup_manager import async_ensure_factory_backup
from .cards import async_register_cards
from .const import (
    CONF_HOST,
    CONF_SELECTED_FEEDER,
    DOMAIN,
    TRANSITION_NOISE_PSK,
    generate_noise_psk,
)
from .esphome_provisioner import async_auto_adopt_esphome
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [Platform.UPDATE, Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the PawSync Feeder component globally."""
    hass.data.setdefault(DOMAIN, {})

    await async_register_cards(hass)
    await async_setup_services(hass)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up PawSync Feeder from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Ensure frontend card and services are registered when loaded via UI config flow
    await async_register_cards(hass)
    await async_setup_services(hass)

    hass.data[DOMAIN][entry.entry_id] = entry.data

    feeder_info = entry.data.get("feeder_info", {})
    mac = feeder_info.get("mac") or entry.data.get("mac_address")
    cid = entry.data.get(CONF_SELECTED_FEEDER) or entry.title
    name = feeder_info.get("name") or entry.title
    model = feeder_info.get("model") or "PPF-R361S"
    host = entry.options.get(CONF_HOST) or entry.data.get(CONF_HOST) or feeder_info.get("ip")

    # 1. Register device in Home Assistant's Device Registry under PawSync
    try:
        identifiers = {(DOMAIN, str(cid))}
        if mac:
            identifiers.add((DOMAIN, str(mac)))

        connections = set()
        if mac:
            connections.add((dr.CONNECTION_NETWORK_MAC, str(mac)))

        device_registry = dr.async_get(hass)
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers=identifiers,
            connections=connections,
            name=name,
            manufacturer="PawSync",
            model=model,
            sw_version="ESPHome 2026.9.1",
            configuration_url=f"http://{host}" if host else None,
        )
        _LOGGER.info("Registered PawSync device in Device Registry: %s (MAC: %s)", name, mac)
    except Exception as dev_err:
        _LOGGER.warning("Could not register device in Device Registry: %s", dev_err)

    # 2. Check for deprecated legacy default PSK and manage Home Assistant Repairs issue
    device_noise_psk = entry.options.get("noise_psk") or entry.data.get("noise_psk")
    LEGACY_DEFAULT_PSK = "2M4yBDYqWbBDSl3PIkccw2IkCUj5WIySqP8JHYVG7Mc="
    if device_noise_psk == LEGACY_DEFAULT_PSK:
        _LOGGER.warning(
            "Feeder %s is configured with the deprecated legacy default Noise PSK",
            name,
        )
        try:
            from homeassistant.helpers import issue_registry as ir
            ir.async_create_issue(
                hass,
                domain=DOMAIN,
                issue_id=f"legacy_noise_psk_{entry.entry_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="legacy_noise_psk",
                translation_placeholders={"feeder_name": name},
                learn_more_url="https://github.com/sibero80/pawsync_esphome/blob/main/SECURITY.md",
            )
        except Exception as issue_err:
            _LOGGER.debug("Could not create repairs issue: %s", issue_err)
    else:
        try:
            from homeassistant.helpers import issue_registry as ir
            ir.async_delete_issue(
                hass,
                domain=DOMAIN,
                issue_id=f"legacy_noise_psk_{entry.entry_id}",
            )
        except Exception:
            pass

    # 3. Trigger automated ESPHome background adoption if host is known
    if host:
        if not device_noise_psk:
            device_noise_psk = TRANSITION_NOISE_PSK
            hass.config_entries.async_update_entry(
                entry,
                data={**entry.data, "noise_psk": device_noise_psk},
            )
        hass.async_create_task(
            async_auto_adopt_esphome(
                hass=hass,
                host=host,
                noise_psk=device_noise_psk,
                mac=mac,
                feeder_name=name,
            )
        )

    # 4. Trigger automated background factory stock backup if host and mac are known
    if host and mac:
        hass.async_create_task(
            async_ensure_factory_backup(
                hass=hass,
                host=host,
                mac=mac,
            )
        )

    # 5. Forward setup to platforms (e.g. Firmware Update and Diagnostic Sensors)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # 5. Reload entry on options update (e.g. unit system switch or IP change)
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    _LOGGER.info("Loaded PawSync config entry for %s", entry.title)
    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a PawSync Feeder config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
        hass.data[DOMAIN].pop(entry.entry_id)
        _LOGGER.info("Unloaded PawSync config entry for %s", entry.title)
    return unload_ok
