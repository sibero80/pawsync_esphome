"""Config Flow for PawSync Smart Pet Feeder Integration."""

from __future__ import annotations

import logging
import os
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .backup_manager import (
    get_backup_paths,
    strip_trailing_padding,
    validate_esp_idf_image,
)
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
    CONF_UNIT_SYSTEM,
    CONF_WIFI_PASSWORD,
    DEFAULT_COUNTRY_CODE,
    DEFAULT_TIME_ZONE,
    DOMAIN,
    FLASH_METHOD_OTA,
    FLASH_METHOD_SKIP,
    FLASH_METHOD_WEBSERIAL,
    MODE_CLOUD_ONBOARDING,
    MODE_DIRECT_ESPHOME,
    generate_noise_psk,
    generate_ota_password,
    UNIT_SYSTEM_IMPERIAL,
    UNIT_SYSTEM_METRIC,
    VERSION,
)
from .backup_manager import save_cloud_backup
from .esphome_provisioner import (
    async_auto_adopt_esphome,
    async_provision_esphome_yaml,
)
from .firmware_downloader import async_ensure_firmware_binary
from .ota_stager import PawsyncOtaStager
from .pawsync_api import (
    PawsyncApiClient,
    PawsyncAuthError,
    PawsyncConnectionError,
    resolve_ip_from_mac,
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
        self._unit_system: str = UNIT_SYSTEM_METRIC
        self._ota_stager: PawsyncOtaStager | None = None
        self._ota_task: asyncio.Task | None = None

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
            # Refresh local IP via multi-tiered discovery if not populated from cloud
            mac_str = dev.get("mac", "").strip()
            ip_str = dev.get("ip", "").strip() or resolve_ip_from_mac(mac_str, hass=self.hass)
            if ip_str:
                dev["ip"] = ip_str

            model_display = dev.get("model") or "PPF-R361S"

            details = []
            if ip_str:
                details.append(f"IP: {ip_str}")
            if mac_str:
                details.append(f"MAC: {mac_str}")
            detail_str = " | ".join(details) if details else "Wi-Fi Device"

            label = f"{dev['name']} ({model_display}) - {detail_str}"
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

        is_metric = getattr(self.hass.config.units, "is_metric", True) if hasattr(self.hass.config, "units") else True
        default_unit = UNIT_SYSTEM_METRIC if is_metric else UNIT_SYSTEM_IMPERIAL

        # Attempt dynamic IP resolution if not yet discovered
        current_ip = self._selected_feeder_info.get("ip") or ""
        if not current_ip and self._selected_feeder_info.get("mac"):
            current_ip = resolve_ip_from_mac(self._selected_feeder_info["mac"], hass=self.hass)
            if current_ip:
                self._selected_feeder_info["ip"] = current_ip

        if user_input is not None:
            self._wifi_ssid = user_input.get(CONF_SSID, "")
            self._wifi_password = user_input.get(CONF_WIFI_PASSWORD, "")
            self._unit_system = user_input.get(CONF_UNIT_SYSTEM, default_unit)
            if user_input.get(CONF_HOST):
                self._selected_feeder_info["ip"] = user_input[CONF_HOST].strip()
            return await self.async_step_flash_wizard()

        data_schema = vol.Schema(
            {
                vol.Optional(CONF_SSID, default=self._wifi_ssid): str,
                vol.Optional(CONF_WIFI_PASSWORD, default=""): str,
                vol.Optional(
                    CONF_HOST,
                    default=self._selected_feeder_info.get("ip") or "",
                ): str,
                vol.Required(CONF_UNIT_SYSTEM, default=default_unit): vol.In(
                    {
                        UNIT_SYSTEM_METRIC: "Metric (Grams, Liters)",
                        UNIT_SYSTEM_IMPERIAL: "Imperial (Ounces, Cups)",
                    }
                ),
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
            device_noise_psk = self._selected_feeder_info.get("noise_psk") or generate_noise_psk()
            device_ota_password = self._selected_feeder_info.get("ota_password") or generate_ota_password()
            self._selected_feeder_info["noise_psk"] = device_noise_psk
            self._selected_feeder_info["ota_password"] = device_ota_password

            # Automatically provision /config/esphome/ YAML and secrets.yaml
            try:
                await async_provision_esphome_yaml(
                    hass_config_dir=self.hass.config.config_dir,
                    device_name=feeder_name,
                    friendly_name=feeder_name,
                    wifi_ssid=self._wifi_ssid,
                    wifi_password=self._wifi_password,
                    mac_address=mac_address,
                    noise_psk=device_noise_psk,
                    ota_password=device_ota_password,
                )
            except Exception as err:
                _LOGGER.warning("Could not auto-provision ESPHome YAML: %s", err)

            # If wireless OTA was chosen, show progress and wait for device to reconnect
            if self._flash_method == FLASH_METHOD_OTA:
                return await self.async_step_ota_progress()

            # Otherwise complete flow immediately
            return self._create_feeder_entry()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_FLASH_METHOD, default=FLASH_METHOD_OTA
                ): vol.In(
                    {
                        FLASH_METHOD_OTA: "Wireless OTA: Zero-Touch Repackaging & Flash (Recommended)",
                        FLASH_METHOD_WEBSERIAL: "WebSerial: Flash via USB-C cable in browser",
                        FLASH_METHOD_SKIP: "Skip: Feeder is already running ESPHome",
                    }
                )
            }
        )

        return self.async_show_form(
            step_id="flash_wizard",
            data_schema=data_schema,
            errors=errors,
        )

    async def _async_convert_feeder_task(self) -> None:
        """Execute dynamic patching, staging, cloud OTA, and wait for feeder to reappear."""
        feeder_name = self._selected_feeder_info.get("name", "Pawsync Feeder")
        mac_address = self._selected_feeder_info.get("mac", "")
        cid = self._selected_feeder_cid
        device_noise_psk = self._selected_feeder_info.get("noise_psk") or generate_noise_psk()
        device_ota_password = self._selected_feeder_info.get("ota_password") or generate_ota_password()
        self._selected_feeder_info["noise_psk"] = device_noise_psk
        self._selected_feeder_info["ota_password"] = device_ota_password

        # 0. Pre-flash cloud settings harvesting
        session = async_get_clientsession(self.hass)
        if self._cloud_auth.get(CONF_TOKEN):
            try:
                client = PawsyncApiClient(
                    session=session,
                    country_code=self._cloud_auth.get(CONF_COUNTRY_CODE, DEFAULT_COUNTRY_CODE),
                    time_zone=self._cloud_auth.get(CONF_TIME_ZONE, DEFAULT_TIME_ZONE),
                )
                harvested = await client.async_harvest_feeder_profile(
                    cid=cid,
                    account_id=self._cloud_auth.get(CONF_ACCOUNT_ID),
                    token=self._cloud_auth.get(CONF_TOKEN),
                )
                if harvested:
                    await self.hass.async_add_executor_job(
                        save_cloud_backup, self.hass, mac_address, harvested
                    )
                    self._selected_feeder_info["cloud_profile"] = harvested
            except Exception as err:
                _LOGGER.warning("Cloud profile harvest failed before conversion for %s: %s", cid, err)

        # 1. Prepare & patch firmware
        fw_path = await async_ensure_firmware_binary(
            self.hass, version=VERSION, require_patchable=True
        )

        stager = PawsyncOtaStager(
            firmware_path=fw_path,
            wifi_ssid=self._wifi_ssid,
            wifi_password=self._wifi_password,
            noise_psk=device_noise_psk,
            ota_password=device_ota_password,
        )
        download_url = await stager.async_start()

        # 2. Trigger cloud relay command
        session = async_get_clientsession(self.hass)
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
        _LOGGER.info("Cloud OTA trigger sent: %s. Waiting for feeder to flash and reconnect...", res)

        # 3. Wait for feeder to reboot and come online on home network (up to 120s)
        local_ip = self._selected_feeder_info.get("ip") or ""
        adopted = await async_auto_adopt_esphome(
            self.hass,
            host=local_ip,
            noise_psk=device_noise_psk,
            mac=mac_address,
            feeder_name=feeder_name,
            max_attempts=40,
            delay=3.0,
        )

        # Update discovered IP if resolved
        if mac_address:
            resolved = resolve_ip_from_mac(mac_address, hass=self.hass)
            if resolved:
                self._selected_feeder_info["ip"] = resolved

        self._adoption_successful = bool(adopted)

    async def async_step_ota_progress(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show progress bar and wait for feeder to flash and reconnect."""
        if not hasattr(self, "_ota_task") or self._ota_task is None:
            self._ota_task = self.hass.async_create_task(self._async_convert_feeder_task())
            return self.async_show_progress(
                step_id="ota_progress",
                progress_action="converting",
                progress_task=self._ota_task,
            )

        if not self._ota_task.done():
            return self.async_show_progress(
                step_id="ota_progress",
                progress_action="converting",
                progress_task=self._ota_task,
            )

        # Task is complete!
        err = self._ota_task.exception()
        if err:
            _LOGGER.error("OTA conversion error: %s", err)
            return self.async_show_progress_done(next_step_id="recovery")

        if not getattr(self, "_adoption_successful", True):
            _LOGGER.warning("Auto-adoption did not succeed; redirecting to recovery step")
            return self.async_show_progress_done(next_step_id="recovery")

        return self.async_show_progress_done(next_step_id="ota_finish")

    async def async_step_ota_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Create config entry after successful conversion and network reappearance."""
        return self._create_feeder_entry()

    async def async_step_recovery(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle conversion recovery: retry discovery, manual IP, or proceed anyway."""
        errors: dict[str, str] = {}
        feeder_name = self._selected_feeder_info.get("name", "Pawsync Feeder")
        mac_address = self._selected_feeder_info.get("mac", "")
        device_noise_psk = self._selected_feeder_info.get("noise_psk") or generate_noise_psk()
        self._selected_feeder_info["noise_psk"] = device_noise_psk

        if user_input is not None:
            action = user_input.get("recovery_action", "retry")
            manual_ip = (user_input.get("host") or "").strip()

            if action == "manual_ip":
                if not manual_ip:
                    errors["host"] = "invalid_ip"
                else:
                    self._selected_feeder_info["ip"] = manual_ip
                    adopted = await async_auto_adopt_esphome(
                        self.hass,
                        host=manual_ip,
                        noise_psk=device_noise_psk,
                        mac=mac_address,
                        feeder_name=feeder_name,
                        max_attempts=4,
                        delay=1.0,
                    )
                    if adopted:
                        return self._create_feeder_entry()
                    errors["base"] = "cannot_connect_manual_ip"

            elif action == "retry":
                if manual_ip:
                    self._selected_feeder_info["ip"] = manual_ip
                target_ip = manual_ip or self._selected_feeder_info.get("ip") or ""
                adopted = await async_auto_adopt_esphome(
                    self.hass,
                    host=target_ip,
                    noise_psk=device_noise_psk,
                    mac=mac_address,
                    feeder_name=feeder_name,
                    max_attempts=15,
                    delay=2.0,
                )
                if adopted:
                    return self._create_feeder_entry()
                errors["base"] = "adoption_failed"

            elif action == "finish_anyway":
                if manual_ip:
                    self._selected_feeder_info["ip"] = manual_ip
                return self._create_feeder_entry()

        recovery_schema = vol.Schema(
            {
                vol.Required("recovery_action", default="retry"): vol.In(
                    {
                        "retry": "Retry ESPHome Auto-Discovery",
                        "manual_ip": "Adopt via Manual IP Address",
                        "finish_anyway": "Proceed without Waiting for Adoption",
                    }
                ),
                vol.Optional(
                    "host",
                    default=self._selected_feeder_info.get("ip") or "",
                ): str,
            }
        )

        return self.async_show_form(
            step_id="recovery",
            data_schema=recovery_schema,
            errors=errors,
            description_placeholders={
                "feeder_name": feeder_name,
                "mac": mac_address,
                "fallback_ssid": "Pawsync-Feeder-Fallback",
                "fallback_password": "pawsync1234",
            },
        )

    async def async_step_ota_error(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle conversion error or timeout with recovery options."""
        return await self.async_step_recovery(user_input)

    def _create_feeder_entry(self) -> config_entries.ConfigFlowResult:
        """Helper to create the config entry."""
        feeder_name = self._selected_feeder_info.get("name", "Pawsync Feeder")
        mac_address = self._selected_feeder_info.get("mac", "")
        cid = self._selected_feeder_cid
        local_ip = self._selected_feeder_info.get("ip") or ""
        device_noise_psk = self._selected_feeder_info.get("noise_psk") or generate_noise_psk()
        device_ota_password = self._selected_feeder_info.get("ota_password") or generate_ota_password()

        title = f"{feeder_name} ({mac_address or cid[:8]})"
        entry_data = {
            CONF_ONBOARDING_MODE: self._onboarding_mode,
            CONF_ACCOUNT_ID: self._cloud_auth.get(CONF_ACCOUNT_ID),
            CONF_TOKEN: None,  # Redacted: cloud token is bootstrap-only and not persisted
            CONF_SELECTED_FEEDER: cid,
            "feeder_info": self._selected_feeder_info,
            "noise_psk": device_noise_psk,
            "ota_password": device_ota_password,
            "cloud_profile": self._selected_feeder_info.get("cloud_profile"),
            CONF_FLASH_METHOD: self._flash_method,
            CONF_SSID: self._wifi_ssid,
            CONF_HOST: local_ip,
            CONF_UNIT_SYSTEM: self._unit_system,
        }

        return self.async_create_entry(
            title=title,
            data=entry_data,
            description_placeholders={
                "feeder_name": feeder_name,
                "ip": local_ip or "Auto-discovering via mDNS...",
                "noise_psk": device_noise_psk,
            },
        )

    async def async_step_direct_esphome(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Direct connection for an existing flashed ESPHome feeder."""
        errors: dict[str, str] = {}

        is_metric = getattr(self.hass.config.units, "is_metric", True) if hasattr(self.hass.config, "units") else True
        default_unit = UNIT_SYSTEM_METRIC if is_metric else UNIT_SYSTEM_IMPERIAL

        if user_input is not None:
            name = user_input.get("name", "Pawsync Feeder").strip()
            host = user_input[CONF_HOST].strip()
            unit_system = user_input.get(CONF_UNIT_SYSTEM, default_unit)
            device_noise_psk = generate_noise_psk()

            self.hass.async_create_task(
                async_auto_adopt_esphome(
                    self.hass,
                    host=host,
                    noise_psk=device_noise_psk,
                    feeder_name=name,
                )
            )

            return self.async_create_entry(
                title=name,
                data={
                    CONF_ONBOARDING_MODE: MODE_DIRECT_ESPHOME,
                    CONF_HOST: host,
                    CONF_UNIT_SYSTEM: unit_system,
                    "noise_psk": device_noise_psk,
                    "name": name,
                },
                description_placeholders={
                    "feeder_name": name,
                    "ip": host,
                    "noise_psk": device_noise_psk,
                },
            )

        data_schema = vol.Schema(
            {
                vol.Required("name", default="Pawsync Feeder"): str,
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_UNIT_SYSTEM, default=default_unit): vol.In(
                    {
                        UNIT_SYSTEM_METRIC: "Metric (Grams, Liters)",
                        UNIT_SYSTEM_IMPERIAL: "Imperial (Ounces, Cups)",
                    }
                ),
            }
        )

        return self.async_show_form(
            step_id="direct_esphome",
            data_schema=data_schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return PawsyncOptionsFlowHandler(config_entry)


class PawsyncOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Pawsync Feeder integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    @property
    def config_entry(self) -> config_entries.ConfigEntry:
        """Return the config entry."""
        return getattr(self, "_config_entry", None) or super().config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Handle manual stock backup file import if supplied
            stock_file = (user_input.get("stock_backup_file_path") or "").strip()
            if stock_file:
                if not os.path.isfile(stock_file):
                    errors["stock_backup_file_path"] = "file_not_found"
                else:
                    try:
                        raw_data = await self.hass.async_add_executor_job(
                            lambda: open(stock_file, "rb").read()
                        )
                        trimmed = strip_trailing_padding(raw_data)
                        valid, err, _ = validate_esp_idf_image(trimmed)
                        if not valid:
                            errors["stock_backup_file_path"] = "invalid_esp_image"
                        else:
                            feeder_info = self.config_entry.data.get("feeder_info", {})
                            mac = feeder_info.get("mac") or self.config_entry.data.get("mac_address") or "manual"
                            stock_path, _ = get_backup_paths(self.hass, mac)

                            def _save():
                                stock_path.write_bytes(trimmed)
                                os.chmod(stock_path, 0o600)

                            await self.hass.async_add_executor_job(_save)
                            _LOGGER.info("Manually imported stock firmware backup for %s (%d bytes)", mac, len(trimmed))
                    except Exception as err:
                        _LOGGER.error("Failed importing stock backup file: %s", err)
                        errors["stock_backup_file_path"] = "import_failed"

            if not errors:
                return self.async_create_entry(title="", data=user_input)

        is_metric = getattr(self.hass.config.units, "is_metric", True) if hasattr(self.hass.config, "units") else True
        default_unit = self.config_entry.options.get(
            CONF_UNIT_SYSTEM,
            self.config_entry.data.get(CONF_UNIT_SYSTEM, UNIT_SYSTEM_METRIC if is_metric else UNIT_SYSTEM_IMPERIAL),
        )
        current_host = self.config_entry.options.get(
            CONF_HOST,
            self.config_entry.data.get(CONF_HOST, ""),
        )
        current_port = self.config_entry.options.get("stager_port", 8099)
        current_backup_path = self.config_entry.options.get("stock_backup_file_path", "")

        data_schema = vol.Schema(
            {
                vol.Required(CONF_UNIT_SYSTEM, default=default_unit): vol.In(
                    {
                        UNIT_SYSTEM_METRIC: "Metric (Grams, Liters)",
                        UNIT_SYSTEM_IMPERIAL: "Imperial (Ounces, Cups)",
                    }
                ),
                vol.Optional(CONF_HOST, default=current_host): str,
                vol.Optional("stager_port", default=current_port): vol.All(
                    vol.Coerce(int), vol.Range(min=1024, max=65535)
                ),
                vol.Optional("stock_backup_file_path", default=current_backup_path): str,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
            errors=errors,
        )
