"""Services for PawSync Feeder Integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_FEED = "feed"
SERVICE_TARE_SCALE = "tare_scale"
SERVICE_CALIBRATE = "calibrate_portion"

FEED_SCHEMA = vol.Schema(
    {
        vol.Required("portions", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
        vol.Optional("entity_id"): cv.entity_ids,
    }
)

TARE_SCHEMA = vol.Schema(
    {
        vol.Optional("entity_id"): cv.entity_ids,
    }
)

CALIBRATE_SCHEMA = vol.Schema(
    {
        vol.Required("grams_per_portion"): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=50.0)),
        vol.Optional("entity_id"): cv.entity_ids,
    }
)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register custom services for Pawsync integration."""

    async def async_handle_feed(call: ServiceCall) -> None:
        """Handle immediate feeding service call."""
        portions = call.data["portions"]
        entity_ids = call.data.get("entity_id")
        _LOGGER.info("Executing PawSync feed service: %d portions (targets: %s)", portions, entity_ids)

        # Dispatches to the underlying esphome service if configured
        target_service = "pawsync_ppf_r361s_feeder_feed"
        if hass.services.has_service("esphome", target_service):
            await hass.services.async_call(
                "esphome",
                target_service,
                {"portions": portions},
                blocking=True,
            )
        else:
            _LOGGER.debug("ESPHome native service %s not yet active, logging dispense intent", target_service)

    async def async_handle_tare(call: ServiceCall) -> None:
        """Handle bowl scale tare service call."""
        _LOGGER.info("Executing PawSync tare scale service")
        tare_button = "button.pawsync_ppf_r361s_feeder_tare_bowl_scale"
        if hass.states.get(tare_button):
            await hass.services.async_call(
                "button",
                "press",
                {"entity_id": tare_button},
                blocking=True,
            )

    async def async_handle_calibrate(call: ServiceCall) -> None:
        """Handle setting kibble portion calibration."""
        grams = call.data["grams_per_portion"]
        _LOGGER.info("Executing PawSync calibrate portion service: %.1fg", grams)
        number_entity = "number.pawsync_ppf_r361s_feeder_kibble_grams_per_portion_kibble_calibration"
        if hass.states.get(number_entity):
            await hass.services.async_call(
                "number",
                "set_value",
                {"entity_id": number_entity, "value": grams},
                blocking=True,
            )

    if not hass.services.has_service(DOMAIN, SERVICE_FEED):
        hass.services.async_register(DOMAIN, SERVICE_FEED, async_handle_feed, schema=FEED_SCHEMA)

    if not hass.services.has_service(DOMAIN, SERVICE_TARE_SCALE):
        hass.services.async_register(DOMAIN, SERVICE_TARE_SCALE, async_handle_tare, schema=TARE_SCHEMA)

    if not hass.services.has_service(DOMAIN, SERVICE_CALIBRATE):
        hass.services.async_register(DOMAIN, SERVICE_CALIBRATE, async_handle_calibrate, schema=CALIBRATE_SCHEMA)
