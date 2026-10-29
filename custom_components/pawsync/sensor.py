"""Diagnostic sensors for PawSync Feeder factory backup and partition state."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .backup_manager import (
    async_check_device_backup_status,
    has_valid_local_backup,
)
from .const import (
    BACKUP_STATUS_BACKED_UP,
    BACKUP_STATUS_PENDING,
    BACKUP_STATUS_SLOT_OVERWRITTEN,
    BACKUP_STATUS_UNAVAILABLE,
    CONF_HOST,
    CONF_SELECTED_FEEDER,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

SLOT_STATE_STOCK_PRESERVED = "Stock Preserved"
SLOT_STATE_ESPHOME_OVERWRITTEN = "ESPHome Overwritten"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PawSync diagnostic sensors from a config entry."""
    async_add_entities(
        [
            PawSyncStockBackupStatusSensor(hass, entry),
            PawSyncAlternateSlotSensor(hass, entry),
        ],
        update_before_add=True,
    )


class PawSyncStockBackupStatusSensor(SensorEntity):
    """Sensor tracking whether genuine factory firmware has been backed up to local HA storage."""

    _attr_has_entity_name = True
    _attr_name = "Stock Backup Status"
    _attr_icon = "mdi:folder-sync"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the stock backup status sensor."""
        self.hass = hass
        self._entry = entry

        feeder_info = entry.data.get("feeder_info", {})
        self._mac = feeder_info.get("mac") or entry.data.get("mac_address")
        self._cid = entry.data.get(CONF_SELECTED_FEEDER) or entry.title
        self._name = feeder_info.get("name") or entry.title
        self._model = feeder_info.get("model") or "PPF-R361S"
        self._host = entry.options.get(CONF_HOST) or entry.data.get(CONF_HOST) or feeder_info.get("ip")

        self._attr_unique_id = f"{self._mac or self._cid}_stock_backup_status"

        identifiers = {(DOMAIN, str(self._cid))}
        if self._mac:
            identifiers.add((DOMAIN, str(self._mac)))

        connections = set()
        if self._mac:
            connections.add((dr.CONNECTION_NETWORK_MAC, str(self._mac)))

        self._attr_device_info = DeviceInfo(
            identifiers=identifiers,
            connections=connections,
            name=self._name,
            manufacturer="PawSync",
            model=self._model,
        )
        self._attr_native_value = BACKUP_STATUS_PENDING
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self._backup_verified: bool = False

    async def async_update(self) -> None:
        """Fetch current backup status."""
        if not self._mac:
            self._attr_native_value = BACKUP_STATUS_UNAVAILABLE
            return

        # 1. Fast-path: already verified valid local backup
        if self._backup_verified:
            self._attr_native_value = BACKUP_STATUS_BACKED_UP
            self._attr_extra_state_attributes = {"local_backup_verified": True}
            return

        # Offload 1MB disk read from event loop
        has_backup = await self.hass.async_add_executor_job(
            has_valid_local_backup, self.hass, self._mac
        )
        if has_backup:
            self._backup_verified = True
            self._attr_native_value = BACKUP_STATUS_BACKED_UP
            self._attr_extra_state_attributes = {"local_backup_verified": True}
            return

        # 2. Check device partition status endpoint
        host = self._host or self._entry.options.get(CONF_HOST) or self._entry.data.get(CONF_HOST)
        if not host:
            self._attr_native_value = BACKUP_STATUS_PENDING
            return

        session = async_get_clientsession(self.hass)
        status = await async_check_device_backup_status(host, session)
        if "error" in status:
            self._attr_native_value = BACKUP_STATUS_UNAVAILABLE
            self._attr_extra_state_attributes = {"error": status["error"]}
        elif not status.get("stock_intact"):
            self._attr_native_value = BACKUP_STATUS_SLOT_OVERWRITTEN
            self._attr_extra_state_attributes = {
                "slot": status.get("slot"),
                "version": status.get("version"),
            }
        else:
            self._attr_native_value = BACKUP_STATUS_PENDING
            self._attr_extra_state_attributes = {
                "slot": status.get("slot"),
                "version": status.get("version"),
            }


class PawSyncAlternateSlotSensor(SensorEntity):
    """Sensor tracking whether feeder's alternate flash partition preserves factory stock."""

    _attr_has_entity_name = True
    _attr_name = "Alternate Slot State"
    _attr_icon = "mdi:memory"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the alternate slot state sensor."""
        self.hass = hass
        self._entry = entry

        feeder_info = entry.data.get("feeder_info", {})
        self._mac = feeder_info.get("mac") or entry.data.get("mac_address")
        self._cid = entry.data.get(CONF_SELECTED_FEEDER) or entry.title
        self._name = feeder_info.get("name") or entry.title
        self._model = feeder_info.get("model") or "PPF-R361S"
        self._host = entry.options.get(CONF_HOST) or entry.data.get(CONF_HOST) or feeder_info.get("ip")

        self._attr_unique_id = f"{self._mac or self._cid}_alternate_slot_state"

        identifiers = {(DOMAIN, str(self._cid))}
        if self._mac:
            identifiers.add((DOMAIN, str(self._mac)))

        connections = set()
        if self._mac:
            connections.add((dr.CONNECTION_NETWORK_MAC, str(self._mac)))

        self._attr_device_info = DeviceInfo(
            identifiers=identifiers,
            connections=connections,
            name=self._name,
            manufacturer="PawSync",
            model=self._model,
        )
        self._attr_native_value = "Unknown"
        self._attr_extra_state_attributes: dict[str, Any] = {}

    async def async_update(self) -> None:
        """Fetch alternate slot partition description."""
        host = self._host or self._entry.options.get(CONF_HOST) or self._entry.data.get(CONF_HOST)
        if not host:
            self._attr_native_value = "Unknown"
            return

        session = async_get_clientsession(self.hass)
        status = await async_check_device_backup_status(host, session)
        if "error" in status:
            self._attr_native_value = "Unavailable"
            self._attr_extra_state_attributes = {"error": status["error"]}
        elif status.get("stock_intact"):
            self._attr_native_value = SLOT_STATE_STOCK_PRESERVED
            self._attr_extra_state_attributes = {
                "slot": status.get("slot"),
                "version": status.get("version"),
                "size": status.get("slot_size"),
            }
        else:
            self._attr_native_value = SLOT_STATE_ESPHOME_OVERWRITTEN
            self._attr_extra_state_attributes = {
                "slot": status.get("slot"),
                "version": status.get("version"),
                "size": status.get("slot_size"),
            }
