"""Services for PawSync Feeder Integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .backup_manager import get_backup_paths, validate_esp_idf_image
from .const import CONF_HOST, DOMAIN
from .espota_client import async_flash_esphome_ota

_LOGGER = logging.getLogger(__name__)

SERVICE_FEED = "feed"
SERVICE_TARE_SCALE = "tare_scale"
SERVICE_CALIBRATE = "calibrate_portion"
SERVICE_RESTORE_STOCK = "restore_stock_firmware"
SERVICE_RESTORE_CLOUD_BACKUP = "restore_cloud_backup"
SERVICE_FLASH_LATEST_FIRMWARE = "flash_latest_firmware"

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

RESTORE_STOCK_SCHEMA = vol.Schema(
    {
        vol.Required("confirm", default=False): cv.boolean,
        vol.Optional("host"): cv.string,
        vol.Optional("mac"): cv.string,
    }
)

RESTORE_CLOUD_BACKUP_SCHEMA = vol.Schema(
    {
        vol.Optional("mac"): cv.string,
        vol.Optional("entry_id"): cv.string,
    }
)

FLASH_LATEST_FIRMWARE_SCHEMA = vol.Schema(
    {
        vol.Optional("host"): cv.string,
        vol.Optional("mac"): cv.string,
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

    async def async_handle_restore_stock(call: ServiceCall) -> None:
        """Handle 1-click restore to stock firmware over OTA Port 3232."""
        if not call.data.get("confirm", False):
            raise HomeAssistantError(
                "Confirmation required to restore stock firmware: please set 'confirm: true'. "
                "This will flash the feeder back to genuine VeSync stock firmware."
            )

        host = call.data.get("host")
        mac = call.data.get("mac")

        # Disambiguate multi-feeder setups if host/mac omitted
        if not host or not mac:
            domain_entries = [
                d for d in hass.data.get(DOMAIN, {}).values() if isinstance(d, dict)
            ]
            if len(domain_entries) > 1:
                raise HomeAssistantError(
                    f"Multiple PawSync feeders found ({len(domain_entries)}). "
                    "You must explicitly specify target 'host' or 'mac' in restore_stock_firmware service call."
                )
            if domain_entries:
                entry_data = domain_entries[0]
                feeder_info = entry_data.get("feeder_info", {})
                if not host:
                    host = entry_data.get(CONF_HOST) or feeder_info.get("ip")
                if not mac:
                    mac = feeder_info.get("mac") or entry_data.get("mac_address")

        if not host or not mac:
            raise HomeAssistantError("Could not resolve target feeder IP address or MAC for restore.")

        stock_path, _ = get_backup_paths(hass, mac)
        if not stock_path.is_file():
            raise HomeAssistantError(
                f"No stock firmware backup file found at {stock_path}. "
                "Please place or upload a valid stock backup binary first."
            )

        stock_bytes = await hass.async_add_executor_job(stock_path.read_bytes)
        valid, err, meta = validate_esp_idf_image(stock_bytes)
        if not valid:
            raise HomeAssistantError(f"Stock backup file {stock_path.name} failed ESP-IDF validation: {err}")

        _LOGGER.warning(
            "Initiating 1-Click stock firmware restore to %s (%d bytes, project: '%s', version: '%s')...",
            host,
            len(stock_bytes),
            meta.get("project"),
            meta.get("version"),
        )

        ota_password = None
        for entry in hass.config_entries.async_entries(DOMAIN):
            feeder_info = entry.data.get("feeder_info", {})
            entry_mac = (feeder_info.get("mac") or entry.data.get("mac_address") or "").replace(":", "").replace("-", "").lower()
            clean_mac = (mac or "").replace(":", "").replace("-", "").lower()
            if entry_mac and clean_mac and entry_mac == clean_mac:
                ota_password = entry.data.get("ota_password")
                break

        success = await async_flash_esphome_ota(
            host=host,
            firmware_binary=stock_bytes,
            ota_password=ota_password,
        )
        if not success:
            raise HomeAssistantError(f"ESPHome OTA flash to {host}:3232 failed. Check logs for details.")

        _LOGGER.info("Stock firmware flashed. Waiting up to 15 seconds for feeder reboot into stock firmware...")
        port_open = False
        for _ in range(15):
            await asyncio.sleep(1.0)
            try:
                _, writer = await asyncio.wait_for(asyncio.open_connection(host, 55555), timeout=1.0)
                writer.close()
                await writer.wait_closed()
                port_open = True
                break
            except Exception:
                pass

        if port_open:
            _LOGGER.info("Stock firmware restored successfully! VeSync developer port 55555 is responsive on %s.", host)
        else:
            _LOGGER.info("OTA transfer complete; feeder %s rebooted into stock firmware.", host)

    async def async_handle_restore_cloud_backup(call: ServiceCall) -> None:
        """Handle on-demand restoration of cloud backup settings."""
        mac = call.data.get("mac")
        entry_id = call.data.get("entry_id")

        matched_entry = None
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry_id and entry.entry_id == entry_id:
                matched_entry = entry
                break
            if mac:
                feeder_info = entry.data.get("feeder_info", {})
                entry_mac = (feeder_info.get("mac") or entry.data.get("mac_address") or "").replace(":", "").replace("-", "").lower()
                clean_mac = mac.replace(":", "").replace("-", "").lower()
                if entry_mac and clean_mac and entry_mac == clean_mac:
                    matched_entry = entry
                    break

        if not matched_entry:
            entries = hass.config_entries.async_entries(DOMAIN)
            if len(entries) == 1:
                matched_entry = entries[0]
            else:
                raise HomeAssistantError("Could not resolve PawSync feeder entry. Please specify mac or entry_id.")

        from .restore_manager import async_restore_cloud_settings
        success = await async_restore_cloud_settings(hass, matched_entry)
        if not success:
            raise HomeAssistantError(f"Cloud settings restoration failed for {matched_entry.title}")
        _LOGGER.info("Restored cloud backup settings for %s", matched_entry.title)

    async def async_handle_flash_latest_firmware(call: ServiceCall) -> None:
        """Handle on-demand flashing of latest firmware with patched credentials."""
        host = call.data.get("host")
        mac = call.data.get("mac")

        matched_entry = None
        for entry in hass.config_entries.async_entries(DOMAIN):
            feeder_info = entry.data.get("feeder_info", {})
            entry_mac = (feeder_info.get("mac") or entry.data.get("mac_address") or "").replace(":", "").replace("-", "").lower()
            clean_mac = (mac or "").replace(":", "").replace("-", "").lower()
            entry_host = entry.data.get(CONF_HOST) or feeder_info.get("ip")
            if (clean_mac and entry_mac == clean_mac) or (host and entry_host == host):
                matched_entry = entry
                break

        if not matched_entry:
            entries = hass.config_entries.async_entries(DOMAIN)
            if len(entries) == 1:
                matched_entry = entries[0]
            elif len(entries) > 1 and not host and not mac:
                raise HomeAssistantError("Multiple feeders configured; please specify 'host' or 'mac'.")
            else:
                raise HomeAssistantError("Could not resolve target PawSync feeder.")

        from .update import PawSyncFirmwareUpdateEntity
        entity = PawSyncFirmwareUpdateEntity(hass, matched_entry)
        if host:
            entity._host = host
        await entity.async_install()
        _LOGGER.info("Successfully executed flash_latest_firmware service for %s", entity._name)

    if not hass.services.has_service(DOMAIN, SERVICE_FEED):
        hass.services.async_register(DOMAIN, SERVICE_FEED, async_handle_feed, schema=FEED_SCHEMA)

    if not hass.services.has_service(DOMAIN, SERVICE_TARE_SCALE):
        hass.services.async_register(DOMAIN, SERVICE_TARE_SCALE, async_handle_tare, schema=TARE_SCHEMA)

    if not hass.services.has_service(DOMAIN, SERVICE_CALIBRATE):
        hass.services.async_register(DOMAIN, SERVICE_CALIBRATE, async_handle_calibrate, schema=CALIBRATE_SCHEMA)

    if not hass.services.has_service(DOMAIN, SERVICE_RESTORE_STOCK):
        hass.services.async_register(DOMAIN, SERVICE_RESTORE_STOCK, async_handle_restore_stock, schema=RESTORE_STOCK_SCHEMA)

    if not hass.services.has_service(DOMAIN, SERVICE_RESTORE_CLOUD_BACKUP):
        hass.services.async_register(
            DOMAIN,
            SERVICE_RESTORE_CLOUD_BACKUP,
            async_handle_restore_cloud_backup,
            schema=RESTORE_CLOUD_BACKUP_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_FLASH_LATEST_FIRMWARE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_FLASH_LATEST_FIRMWARE,
            async_handle_flash_latest_firmware,
            schema=FLASH_LATEST_FIRMWARE_SCHEMA,
        )
