"""The PawSync Smart Pet Feeder Integration."""

from __future__ import annotations

import logging
import os
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import (
    CARD_FILENAME,
    CARD_URL_PATH,
    CARD_VERSION,
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

    # 1. Register bundled Lovelace Feeder Card static HTTP path
    frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
    card_path = os.path.join(frontend_dir, CARD_FILENAME)

    if os.path.exists(card_path):
        try:
            # Register static route on Home Assistant's HTTP server
            hass.http.register_static_path(
                CARD_URL_PATH,
                card_path,
                cache_headers=False,
            )
            _LOGGER.info("Registered PawSync Card static route at %s", CARD_URL_PATH)
        except Exception as err:
            _LOGGER.warning("Could not register static path %s: %s", CARD_URL_PATH, err)

        # Automatically inject into Lovelace frontend extra JS URLs
        try:
            from homeassistant.components.frontend import add_extra_js_url

            add_extra_js_url(hass, f"{CARD_URL_PATH}?v={CARD_VERSION}")
            _LOGGER.info(
                "Injected PawSync Card into Lovelace frontend extra JS URLs (v%s)",
                CARD_VERSION,
            )
        except Exception as err:
            _LOGGER.debug("Could not add extra JS URL via frontend: %s", err)

        # Auto-register resource in modern Lovelace resources collection
        async def _async_register_lovelace_resource() -> None:
            try:
                lovelace_data = hass.data.get("lovelace")
                if lovelace_data and hasattr(lovelace_data, "resources"):
                    resources = lovelace_data.resources
                    if hasattr(resources, "async_items") and hasattr(resources, "async_create_item"):
                        existing = [
                            item.get("url")
                            for item in resources.async_items()
                            if CARD_URL_PATH in item.get("url", "")
                        ]
                        if not existing:
                            await resources.async_create_item(
                                {
                                    "res_type": "module",
                                    "url": f"{CARD_URL_PATH}?v={CARD_VERSION}",
                                }
                            )
                            _LOGGER.info(
                                "Registered PawSync Card in Lovelace resources collection"
                            )
            except Exception as res_err:
                _LOGGER.debug("Lovelace resource auto-registration note: %s", res_err)

        hass.async_create_task(_async_register_lovelace_resource())

    # 2. Register custom services
    await async_setup_services(hass)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up PawSync Feeder from a config entry."""
    hass.data.setdefault(DOMAIN, {})
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

    _LOGGER.info("Loaded PawSync config entry for %s", entry.title)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a PawSync Feeder config entry."""
    if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
        hass.data[DOMAIN].pop(entry.entry_id)
        _LOGGER.info("Unloaded PawSync config entry for %s", entry.title)
    return True
