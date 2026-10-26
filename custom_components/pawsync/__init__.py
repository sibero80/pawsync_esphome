"""The PawSync Smart Pet Feeder Integration."""

from __future__ import annotations

import logging
import os
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CARD_FILENAME,
    CARD_URL_PATH,
    CARD_VERSION,
    DOMAIN,
)
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
    _LOGGER.info("Loaded PawSync config entry for %s", entry.title)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a PawSync Feeder config entry."""
    if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
        hass.data[DOMAIN].pop(entry.entry_id)
        _LOGGER.info("Unloaded PawSync config entry for %s", entry.title)
    return True
