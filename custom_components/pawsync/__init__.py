"""The PawSync Smart Pet Feeder Integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .cards import async_register_cards
from .const import (
    CONF_HOST,
    CONF_SELECTED_FEEDER,
    DEFAULT_NOISE_PSK,
    DOMAIN,
)
from .esphome_provisioner import async_auto_adopt_esphome
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)


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
    host = entry.data.get(CONF_HOST) or feeder_info.get("ip")

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

    # 2. Trigger automated ESPHome background adoption if host is known
    if host:
        hass.async_create_task(
            async_auto_adopt_esphome(
                hass=hass,
                host=host,
                noise_psk=DEFAULT_NOISE_PSK,
                mac=mac,
                feeder_name=name,
            )
        )

    # 3. Reload entry on options update (e.g. unit system switch)
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    _LOGGER.info("Loaded PawSync config entry for %s", entry.title)
    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a PawSync Feeder config entry."""
    if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
        hass.data[DOMAIN].pop(entry.entry_id)
        _LOGGER.info("Unloaded PawSync config entry for %s", entry.title)
    return True
