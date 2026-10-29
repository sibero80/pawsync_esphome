"""Pytest configuration and Home Assistant stubs for unit testing."""

import sys
from unittest.mock import MagicMock

# If homeassistant is not installed in the local environment, stub out minimal objects
if "homeassistant" not in sys.modules:
    ha = MagicMock()
    config_entries = MagicMock()

    class ConfigFlow:
        def __init_subclass__(cls, domain=None, **kwargs):
            super().__init_subclass__(**kwargs)
            cls.domain = domain

        def async_show_form(self, step_id, data_schema=None, errors=None, description_placeholders=None):
            return {
                "type": "form",
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors or {},
            }

        def async_create_entry(self, title, data, description=None, description_placeholders=None):
            return {
                "type": "create_entry",
                "title": title,
                "data": data,
                "description_placeholders": description_placeholders or {},
            }

    config_entries.ConfigFlow = ConfigFlow

    class OptionsFlow:
        def __init__(self, config_entry=None):
            self.config_entry = config_entry

        def async_show_form(self, step_id, data_schema=None, errors=None, description_placeholders=None):
            return {
                "type": "form",
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors or {},
            }

        def async_create_entry(self, title, data):
            return {
                "type": "create_entry",
                "title": title,
                "data": data,
            }

    config_entries.OptionsFlow = OptionsFlow
    ha.config_entries = config_entries

    core = MagicMock()
    core.callback = lambda f: f
    ha.core = core

    helpers = MagicMock()
    cv = MagicMock()
    cv.entity_ids = MagicMock()
    helpers.config_validation = cv
    aiohttp_client = MagicMock()
    helpers.aiohttp_client = aiohttp_client
    ha.helpers = helpers

    ha_const = MagicMock()
    class Platform:
        UPDATE = "update"
        SENSOR = "sensor"
    ha_const.Platform = Platform
    sys.modules["homeassistant.const"] = ha_const

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.config_validation"] = cv
    sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client
    sys.modules["homeassistant.components"] = MagicMock()
    sys.modules["homeassistant.components.frontend"] = MagicMock()
    sys.modules["homeassistant.components.http"] = MagicMock()

    class IssueSeverity:
        CRITICAL = "critical"
        ERROR = "error"
        WARNING = "warning"

    issue_registry = MagicMock()
    issue_registry.IssueSeverity = IssueSeverity
    helpers.issue_registry = issue_registry
    sys.modules["homeassistant.helpers.issue_registry"] = issue_registry

    class HomeAssistantError(Exception):
        pass

    ha_exc = MagicMock()
    ha_exc.HomeAssistantError = HomeAssistantError
    sys.modules["homeassistant.exceptions"] = ha_exc

    class UpdateDeviceClass:
        FIRMWARE = "firmware"

    class UpdateEntityFeature:
        INSTALL = 1
        PROGRESS = 2
        RELEASE_NOTES = 4

    class UpdateEntity:
        _attr_has_entity_name = True
        _attr_name = None
        _attr_title = None
        _attr_device_class = None
        _attr_supported_features = 0
        _attr_unique_id = None
        _attr_device_info = None
        _attr_in_progress = False
        _attr_update_percentage = None

        def async_write_ha_state(self):
            pass

    update_module = MagicMock()
    update_module.UpdateDeviceClass = UpdateDeviceClass
    update_module.UpdateEntityFeature = UpdateEntityFeature
    update_module.UpdateEntity = UpdateEntity
    sys.modules["homeassistant.components.update"] = update_module

    class SensorEntity:
        _attr_has_entity_name = True
        _attr_name = None
        _attr_unique_id = None
        _attr_device_info = None
        _attr_native_value = None
        _attr_icon = None
        _attr_extra_state_attributes = None
        _attr_entity_category = None

        @property
        def unique_id(self):
            return self._attr_unique_id

        @property
        def native_value(self):
            return self._attr_native_value

        @property
        def extra_state_attributes(self):
            return self._attr_extra_state_attributes

        def async_write_ha_state(self):
            pass

    sensor_module = MagicMock()
    sensor_module.SensorEntity = SensorEntity
    sys.modules["homeassistant.components.sensor"] = sensor_module

    class EntityCategory:
        DIAGNOSTIC = "diagnostic"
        CONFIG = "config"
    ha_const.EntityCategory = EntityCategory

    class DeviceInfo(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.__dict__.update(kwargs)

    dev_reg = MagicMock()
    dev_reg.DeviceInfo = DeviceInfo
    sys.modules["homeassistant.helpers.device_registry"] = dev_reg
    sys.modules["homeassistant.helpers.entity_platform"] = MagicMock()
