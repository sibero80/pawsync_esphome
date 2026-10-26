"""Config Flow for PawSync Smart Pet Feeder Integration."""

from __future__ import annotations

import logging
import os
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_ACCOUNT_ID,
    CONF_COUNTRY_CODE,
    CONF_FEEDERS,
    CONF_FLASH_METHOD,
    CONF_HOST,
    CONF_ONBOARDING_MODE,
    CONF_SELECTED_FEEDER,
    CONF_SSID,
    CONF_TIME_ZONE,
    CONF_TOKEN,
    CONF_WIFI_PASSWORD,
    DEFAULT_COUNTRY_CODE,
    DEFAULT_TIME_ZONE,
    DOMAIN,
    FLASH_METHOD_OTA,
    FLASH_METHOD_SKIP,
    FLASH_METHOD_WEBSERIAL,
    MODE_CLOUD_ONBOARDING,
    MODE_DIRECT_ESPHOME,
)
from .esphome_provisioner import async_provision_esphome_yaml
from .ota_stager import PawsyncOtaStager
from .pawsync_api import (
    PawsyncApiClient,
    PawsyncAuthError,
    PawsyncConnectionError,
)
from .vesync_relay import VeSyncRelay

_LOGGER = logging.getLogger(__name__)

SUPPORTED_COUNTRIES = ["US", "CO", "ES", "CA", "UK", "DE", "FR", "IT", "JP", "MX"]


class PawsyncConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Pawsync Feeder."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow state."""
        self._onboarding_mode: str = MODE_CLOUD_ONBOARDING
        self._cloud_auth: dict[str, Any] = {}
        self._discovered_devices: list[dict[str, Any]] = []
        self._selected_feeder_cid: str = ""
        self._selected_feeder_info: dict[str, Any] = {}
        self._wifi_ssid: str = ""
        self._wifi_password: str = ""
        self._flash_method: str = FLASH_METHOD_OTA
        self._ota_stager: PawsyncOtaStager | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1: Choose onboarding path."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._onboarding_mode = user_input[CONF_ONBOARDING_MODE]
            if self._onboarding_mode == MODE_CLOUD_ONBOARDING:
                return await self.async_step_cloud()
            return await self.async_step_direct_esphome()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_ONBOARDING_MODE, default=MODE_CLOUD_ONBOARDING
                ): vol.In(
                    {
                        MODE_CLOUD_ONBOARDING: "Guided Onboarding for Stock Feeder (Pawsync Cloud)",
                        MODE_DIRECT_ESPHOME: "Direct Adoption of Flashed ESPHome Feeder (Local IP)",
                    }
                )
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2: Authenticate with Pawsync / VeSync Cloud."""
        errors: dict[str, str] = {}

        # Automatically adopt Home Assistant system timezone and country
        ha_tz = getattr(self.hass.config, "time_zone", DEFAULT_TIME_ZONE) or DEFAULT_TIME_ZONE
        ha_country = getattr(self.hass.config, "country", None) or DEFAULT_COUNTRY_CODE
        default_country = ha_country if ha_country in SUPPORTED_COUNTRIES else DEFAULT_COUNTRY_CODE

        if user_input is not None:
            email = user_input["email"].strip()
            password = user_input["password"]
            country = user_input.get(CONF_COUNTRY_CODE, default_country)
            tz = ha_tz  # Adopted automatically from Home Assistant

            session = async_get_clientsession(self.hass)
            client = PawsyncApiClient(session=session, country_code=country, time_zone=tz)

            try:
                auth = await client.async_login(email, password, country, tz)
                self._cloud_auth = {
                    CONF_ACCOUNT_ID: auth["account_id"],
                    CONF_TOKEN: auth["token"],
                    CONF_COUNTRY_CODE: auth.get("country_code", country),
                    CONF_TIME_ZONE: auth.get("time_zone", tz),
                    "email": email,
                }

                devices = await client.async_get_devices()
                self._discovered_devices = devices

                if not devices:
                    errors["base"] = "no_devices_found"
                else:
                    return await self.async_step_select_feeders()

            except PawsyncAuthError:
                errors["base"] = "invalid_auth"
            except PawsyncConnectionError:
                errors["base"] = "cannot_connect"
            except Exception as err:
                _LOGGER.exception("Unexpected error during cloud auth: %s", err)
                errors["base"] = "unknown"

        data_schema = vol.Schema(
            {
                vol.Required("email"): str,
                vol.Required("password"): str,
                vol.Optional(CONF_COUNTRY_CODE, default=default_country): vol.In(
                    SUPPORTED_COUNTRIES
                ),
            }
        )

        return self.async_show_form(
            step_id="cloud",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_select_feeders(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 3: Select feeder from discovered devices."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected_cid = user_input.get(CONF_SELECTED_FEEDER)
            if not selected_cid:
                errors["base"] = "no_feeder_selected"
            else:
                self._selected_feeder_cid = selected_cid
                for dev in self._discovered_devices:
                    if dev["cid"] == selected_cid:
                        self._selected_feeder_info = dev
                        if dev.get("wifi_ssid") and not self._wifi_ssid:
                            self._wifi_ssid = dev["wifi_ssid"]
                        break
                return await self.async_step_prerequisites()

        device_options: dict[str, str] = {}
        for dev in self._discovered_devices:
            mac_str = dev.get("mac", "").strip()
            mac_display = f"MAC: {mac_str}" if mac_str else "Wi-Fi Device"
            model_display = dev.get("model") or "PPF-R361S"
            label = f"{dev['name']} ({model_display}) - {mac_display}"
            device_options[dev["cid"]] = label

        default_feeder = next(iter(device_options.keys())) if device_options else None

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_SELECTED_FEEDER,
                    default=default_feeder,
                ): vol.In(device_options)
            }
        )

        return self.async_show_form(
            step_id="select_feeders",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_prerequisites(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 4: Verify prerequisites and collect Wi-Fi settings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._wifi_ssid = user_input.get(CONF_SSID, "")
            self._wifi_password = user_input.get(CONF_WIFI_PASSWORD, "")
            return await self.async_step_flash_wizard()

        data_schema = vol.Schema(
            {
                vol.Optional(CONF_SSID, default=self._wifi_ssid): str,
                vol.Optional(CONF_WIFI_PASSWORD, default=""): str,
                vol.Optional("confirm_prerequisites", default=True): bool,
            }
        )

        return self.async_show_form(
            step_id="prerequisites",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_flash_wizard(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 5: Select flashing method and execute adoption."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._flash_method = user_input[CONF_FLASH_METHOD]

            feeder_name = self._selected_feeder_info.get("name", "Pawsync Feeder")
            mac_address = self._selected_feeder_info.get("mac", "")
            cid = self._selected_feeder_cid

            # Automatically provision /config/esphome/ YAML
            try:
                await async_provision_esphome_yaml(
                    hass_config_dir=self.hass.config.config_dir,
                    device_name=feeder_name,
                    friendly_name=feeder_name,
                    wifi_ssid=self._wifi_ssid,
                    wifi_password=self._wifi_password,
                    mac_address=mac_address,
                )
            except Exception as err:
                _LOGGER.warning("Could not auto-provision ESPHome YAML: %s", err)

            # If wireless OTA was chosen, trigger stager and cloud relay
            if self._flash_method == FLASH_METHOD_OTA:
                # Find bundled or staged firmware binary
                fw_candidates = [
                    os.path.join(self.hass.config.config_dir, "pawsync_ota_update.bin"),
                    "/root/pawsync_esphome/pawsync_ota_update.bin",
                    os.path.join(os.path.dirname(__file__), "pawsync_ota_update.bin"),
                ]
                fw_path = None
                for path in fw_candidates:
                    if os.path.exists(path):
                        fw_path = path
                        break

                if fw_path and self._cloud_auth.get(CONF_ACCOUNT_ID) and self._cloud_auth.get(CONF_TOKEN):
                    try:
                        session = async_get_clientsession(self.hass)
                        stager = PawsyncOtaStager(firmware_path=fw_path)
                        download_url = await stager.async_start()

                        relay = VeSyncRelay(
                            account_id=self._cloud_auth[CONF_ACCOUNT_ID],
                            token=self._cloud_auth[CONF_TOKEN],
                            session=session,
                        )
                        model = self._selected_feeder_info.get("model", "VS_WB_PFM_PPF-R361S-WUS_US")
                        res = await relay.async_trigger_ota(
                            cid=cid,
                            download_url=download_url,
                            model=model,
                        )
                        _LOGGER.info("Cloud OTA trigger response: %s", res)
                    except Exception as err:
                        _LOGGER.warning("OTA wireless trigger failed: %s", err)

            # Successfully complete flow
            title = f"{feeder_name} ({mac_address or cid[:8]})"
            entry_data = {
                CONF_ONBOARDING_MODE: self._onboarding_mode,
                CONF_ACCOUNT_ID: self._cloud_auth.get(CONF_ACCOUNT_ID),
                CONF_TOKEN: self._cloud_auth.get(CONF_TOKEN),
                CONF_SELECTED_FEEDER: cid,
                "feeder_info": self._selected_feeder_info,
                CONF_FLASH_METHOD: self._flash_method,
                CONF_SSID: self._wifi_ssid,
            }

            return self.async_create_entry(
                title=title,
                data=entry_data,
            )

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_FLASH_METHOD, default=FLASH_METHOD_OTA
                ): vol.In(
                    {
                        FLASH_METHOD_OTA: "Automated Wireless OTA Flashing (Zero-Touch)",
                        FLASH_METHOD_WEBSERIAL: "Browser WebSerial / USB-C Cable",
                        FLASH_METHOD_SKIP: "Skip Flashing (Feeder Already on ESPHome)",
                    }
                )
            }
        )

        return self.async_show_form(
            step_id="flash_wizard",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_direct_esphome(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Direct connection for an existing flashed ESPHome feeder."""
        errors: dict[str, str] = {}

        if user_input is not None:
            name = user_input.get("name", "Pawsync Feeder").strip()
            host = user_input[CONF_HOST].strip()

            return self.async_create_entry(
                title=name,
                data={
                    CONF_ONBOARDING_MODE: MODE_DIRECT_ESPHOME,
                    CONF_HOST: host,
                    "name": name,
                },
            )

        data_schema = vol.Schema(
            {
                vol.Required("name", default="Pawsync Feeder"): str,
                vol.Required(CONF_HOST): str,
            }
        )

        return self.async_show_form(
            step_id="direct_esphome",
            data_schema=data_schema,
            errors=errors,
        )
