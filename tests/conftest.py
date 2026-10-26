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

        def async_create_entry(self, title, data, description=None):
            return {
                "type": "create_entry",
                "title": title,
                "data": data,
            }

    config_entries.ConfigFlow = ConfigFlow
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

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.config_validation"] = cv
    sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client
    sys.modules["homeassistant.components"] = MagicMock()
    sys.modules["homeassistant.components.frontend"] = MagicMock()
