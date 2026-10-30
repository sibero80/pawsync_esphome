"""PawSync Feeder Firmware Update Platform for Home Assistant."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from aiohttp import ClientSession

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .backup_manager import (
    async_check_device_backup_status,
    has_valid_local_backup,
)
from .const import (
    CONF_HOST,
    CONF_SELECTED_FEEDER,
    CONF_SSID,
    CONF_WIFI_PASSWORD,
    DOMAIN,
    VERSION,
    generate_noise_psk,
)
from .espota_client import async_flash_esphome_ota, sanitize_firmware_binary
from .esphome_provisioner import read_feeder_secrets_sync, resolve_arp_ip
from .firmware_downloader import async_ensure_firmware_binary
from .firmware_patcher import patch_raw_esp32_credentials

_LOGGER = logging.getLogger(__name__)

GITHUB_RELEASES_URL = "https://api.github.com/repos/sibero80/pawsync_esphome/releases/latest"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PawSync firmware update entity from a config entry."""
    async_add_entities([PawSyncFirmwareUpdateEntity(hass, entry)])


class PawSyncFirmwareUpdateEntity(UpdateEntity):
    """Update entity for PawSync Smart Pet Feeder firmware."""

    _attr_has_entity_name = True
    _attr_name = "Firmware"
    _attr_title = "PawSync Smart Pet Feeder Firmware"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.PROGRESS
        | UpdateEntityFeature.RELEASE_NOTES
    )

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the update entity."""
        self.hass = hass
        self._entry = entry

        feeder_info = entry.data.get("feeder_info", {})
        self._mac = feeder_info.get("mac") or entry.data.get("mac_address")
        self._cid = entry.data.get(CONF_SELECTED_FEEDER) or entry.title
        self._name = feeder_info.get("name") or entry.title
        self._model = feeder_info.get("model") or "PPF-R361S"
        self._host = entry.data.get(CONF_HOST) or feeder_info.get("ip")

        self._attr_unique_id = f"{self._mac or self._cid}_firmware_update"

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

        self._latest_version: str | None = VERSION
        self._release_notes: str | None = None
        self._installed_version: str | None = None

    @property
    def installed_version(self) -> str | None:
        """Return the currently installed firmware version on the feeder."""
        if self._installed_version:
            return self._installed_version

        # 1. Check live ESPHome config entries for the matched device
        clean_mac = (self._mac or "").replace(":", "").replace("-", "").strip().lower()
        for esphome_entry in self.hass.config_entries.async_entries("esphome"):
            entry_mac = (esphome_entry.unique_id or "").replace(":", "").replace("-", "").strip().lower()
            entry_host = esphome_entry.data.get("host")
            if (clean_mac and clean_mac == entry_mac) or (self._host and self._host == entry_host):
                if hasattr(esphome_entry, "runtime_data") and esphome_entry.runtime_data:
                    dev_info = getattr(esphome_entry.runtime_data, "device_info", None)
                    if dev_info:
                        proj_ver = getattr(dev_info, "project_version", None)
                        if proj_ver:
                            self._installed_version = str(proj_ver).lstrip("v")
                            return self._installed_version

        # 2. Check if an explicit installed version was saved in entry data/options
        saved_ver = self._entry.data.get("installed_firmware_version")
        if saved_ver:
            self._installed_version = str(saved_ver).lstrip("v")
            return self._installed_version

        # 3. Check Device Registry
        dev_reg = dr.async_get(self.hass)
        device = dev_reg.async_get_device(identifiers={(DOMAIN, str(self._cid))})
        if device and isinstance(device.sw_version, str) and device.sw_version.startswith("v"):
            self._installed_version = device.sw_version.lstrip("v")
            return self._installed_version

        # 4. Default: If not yet confirmed updated to v1.1.0, report v1.0.8
        return "1.0.8"

    @property
    def latest_version(self) -> str | None:
        """Return the latest firmware version available."""
        return self._latest_version or VERSION

    @property
    def release_url(self) -> str | None:
        """Return the release URL."""
        return f"https://github.com/sibero80/pawsync_esphome/releases/tag/v{self.latest_version}"

    async def async_release_notes(self) -> str | None:
        """Return release notes for the latest version."""
        if self._release_notes:
            return self._release_notes

        # Fetch release notes from GitHub
        try:
            async with ClientSession() as session:
                async with session.get(
                    GITHUB_RELEASES_URL,
                    headers={"User-Agent": "HomeAssistant-PawSync"},
                    timeout=5.0,
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self._release_notes = data.get("body")
                        if tag := data.get("tag_name"):
                            self._latest_version = tag.lstrip("v")
                            self.async_write_ha_state()
                        return self._release_notes
        except Exception as err:
            _LOGGER.debug("Could not fetch release notes from GitHub: %s", err)

        return (
            "### v1.1.0 - 100% Native APK Parity\n"
            "- **Precision Feeding Mode**: Closed-loop load-cell compensation & density refinement.\n"
            "- **Scale Tray vs Bowl Detection**: Distinguishes pogo-pin dock status from bowl placement.\n"
            "- **Safety Inhibit & Overload**: Active bowl overflow (>150g) and scale overload (>1000g) protections.\n"
            "- **Eating Speed Telemetry**: Real-time g/min ingestion rate and abnormal eating notifications.\n"
            "- **Chute Maintenance**: 30-day chute cleaning reminder and reset switch.\n"
            "- **Full Parity Blueprint**: 14 notification alert channels.\n"
            "- **Lovelace Card v1.3.0**: Unit conversions, warning banners, and eating telemetry."
        )

    async def async_install(
        self, version: str | None = None, backup: bool = False, **kwargs: Any
    ) -> None:
        """Install the firmware update OTA."""
        _LOGGER.info("Starting firmware update install for %s...", self._name)
        self._attr_in_progress = True
        self._attr_update_percentage = 0
        self.async_write_ha_state()

        # 1. Resolve target host IP
        host = self._host or self._entry.options.get(CONF_HOST) or self._entry.data.get(CONF_HOST)
        if not host and self._mac:
            host = resolve_arp_ip(self._mac, hass=self.hass)

        if not host:
            clean_mac = (self._mac or "").replace(":", "").replace("-", "").strip().lower()
            for esphome_entry in self.hass.config_entries.async_entries("esphome"):
                entry_mac = (esphome_entry.unique_id or "").replace(":", "").replace("-", "").strip().lower()
                if clean_mac and clean_mac == entry_mac:
                    host = esphome_entry.data.get("host")
                    break

        if not host:
            self._attr_in_progress = False
            self.async_write_ha_state()
            raise HomeAssistantError("Could not resolve IP address of the Pawsync feeder.")

        # 2. Check Overwrite Protection Interlock
        try:
            session = async_get_clientsession(self.hass)
            status = await async_check_device_backup_status(host, session)
            if status.get("stock_intact") and not status.get("allow_overwrite"):
                has_backup = False
                if self._mac:
                    has_backup = await self.hass.async_add_executor_job(
                        has_valid_local_backup, self.hass, self._mac
                    )
                if not has_backup:
                    self._attr_in_progress = False
                    self.async_write_ha_state()
                    raise HomeAssistantError(
                        "Firmware update blocked: Alternate partition contains pristine factory stock firmware, "
                        "no local backup exists, and 'Allow Overwriting Stock Slot' switch is OFF. "
                        "Wait for automated factory backup to complete, or toggle ON 'Allow Overwriting Stock Slot'."
                    )
        except HomeAssistantError:
            raise
        except Exception as err:
            _LOGGER.debug("Could not verify overwrite protection status on %s: %s", host, err)

        # 3. Locate or dynamically download the firmware binary
        try:
            firmware_path = await async_ensure_firmware_binary(
                self.hass, version=self.latest_version
            )
        except Exception as err:
            self._attr_in_progress = False
            self.async_write_ha_state()
            raise HomeAssistantError(f"Could not obtain firmware binary: {err}") from err

        try:
            def _read_bin():
                with open(firmware_path, "rb") as f:
                    return f.read()

            data = await self.hass.async_add_executor_job(_read_bin)

            # Strip 129-byte VeSync container header if present
            firmware_binary = sanitize_firmware_binary(data)

            def _on_progress(pct: float) -> None:
                self._attr_update_percentage = int(pct * 100)
                self.async_write_ha_state()

            # 4. Resolve credentials to preserve across OTA
            hass_config_dir = (
                self.hass.config.config_dir
                if hasattr(self.hass, "config") and hasattr(self.hass.config, "config_dir")
                else "/config"
            )
            secrets = await self.hass.async_add_executor_job(
                read_feeder_secrets_sync, hass_config_dir, self._mac
            )

            device_noise_psk = (
                self._entry.data.get("noise_psk")
                or self._entry.options.get("noise_psk")
                or secrets.get("noise_psk")
                or generate_noise_psk()
            )
            device_ota_password = (
                self._entry.data.get("ota_password")
                or self._entry.options.get("ota_password")
                or secrets.get("ota_password")
            )
            wifi_ssid = (
                self._entry.data.get(CONF_SSID)
                or self._entry.options.get(CONF_SSID)
                or self._entry.data.get("wifi_ssid")
                or secrets.get("wifi_ssid")
                or ""
            )
            wifi_password = (
                self._entry.data.get(CONF_WIFI_PASSWORD)
                or self._entry.options.get(CONF_WIFI_PASSWORD)
                or self._entry.data.get("wifi_password")
                or secrets.get("wifi_password")
                or ""
            )

            # 5. Dynamically inject credentials into firmware binary
            if wifi_ssid or device_noise_psk or device_ota_password:
                def _patch(bin_bytes: bytes) -> bytes:
                    return patch_raw_esp32_credentials(
                        bin_bytes,
                        ssid=wifi_ssid,
                        password=wifi_password,
                        noise_psk=device_noise_psk,
                        ota_password=device_ota_password,
                    )

                firmware_binary = await self.hass.async_add_executor_job(_patch, firmware_binary)
                _LOGGER.info(
                    "Injected credentials into update binary for %s: SSID '%s', Noise PSK (%s), OTA pass (%s)",
                    self._name,
                    wifi_ssid,
                    "present" if device_noise_psk else "none",
                    "present" if device_ota_password else "none",
                )

            success = await async_flash_esphome_ota(
                host=host,
                firmware_binary=firmware_binary,
                ota_password=device_ota_password,
                noise_psk=device_noise_psk,
                on_progress=_on_progress,
            )

            if not success:
                raise HomeAssistantError(
                    f"ESPHome OTA upload to {host} failed. Ensure feeder is online and check Home Assistant logs for details."
                )

            # Mark version as updated and persist resolved credentials in entry data
            self._installed_version = self.latest_version
            new_data = dict(self._entry.data)
            new_data["installed_firmware_version"] = self.latest_version
            if device_noise_psk and new_data.get("noise_psk") != device_noise_psk:
                new_data["noise_psk"] = device_noise_psk
            if device_ota_password and new_data.get("ota_password") != device_ota_password:
                new_data["ota_password"] = device_ota_password
            if wifi_ssid and new_data.get(CONF_SSID) != wifi_ssid:
                new_data[CONF_SSID] = wifi_ssid
            if wifi_password and new_data.get(CONF_WIFI_PASSWORD) != wifi_password:
                new_data[CONF_WIFI_PASSWORD] = wifi_password
            self.hass.config_entries.async_update_entry(self._entry, data=new_data)

            # Update Device Registry
            dev_reg = dr.async_get(self.hass)
            device = dev_reg.async_get_device(identifiers={(DOMAIN, str(self._cid))})
            if device:
                dev_reg.async_update_device(device.id, sw_version=f"v{self.latest_version}")

            _LOGGER.info("Firmware update to v%s installed successfully!", self.latest_version)

        except Exception as err:
            _LOGGER.error("Firmware update failed: %s", err)
            raise HomeAssistantError(f"Firmware update failed: {err}") from err
        finally:
            self._attr_in_progress = False
            self._attr_update_percentage = None
            self.async_write_ha_state()
