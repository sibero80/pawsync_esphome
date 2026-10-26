"""ESPHome YAML Provisioner for Pawsync Pet Feeder."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

_LOGGER = logging.getLogger(__name__)

DEFAULT_ESPHOME_DIR = "/config/esphome"


def sanitize_filename(name: str) -> str:
    """Sanitize string for safe filename usage."""
    s = re.sub(r"[^\w\-_]", "_", name.lower())
    return re.sub(r"_+", "_", s).strip("_")


def generate_esphome_yaml(
    device_name: str,
    friendly_name: str,
    wifi_ssid: str = "",
    wifi_password: str = "",
    remote_repo: str = "https://github.com/sibero80/pawsync_esphome",
    branch: str = "main",
    mac_address: str = "",
) -> str:
    """Generate ESPHome YAML configuration referencing the remote package."""
    clean_name = sanitize_filename(device_name)
    mac_comment = f"# Device MAC: {mac_address}\n" if mac_address else ""

    yaml_content = f"""# Auto-provisioned by PawSync Home Assistant Integration
{mac_comment}substitutions:
  name: "{clean_name}"
  friendly_name: "{friendly_name}"

packages:
  pawsync_base:
    url: {remote_repo}
    ref: {branch}
    files:
      - pawsync.yaml
    refresh: 1d

wifi:
  ssid: "{wifi_ssid or '!secret wifi_ssid'}"
  password: "{wifi_password or '!secret wifi_password'}"
  fast_connect: true
  power_save_mode: none

api:
  encryption:
    key: "!secret api_encryption_key"

ota:
  - platform: esphome
"""
    return yaml_content


async def async_provision_esphome_yaml(
    hass_config_dir: str,
    device_name: str,
    friendly_name: str,
    wifi_ssid: str = "",
    wifi_password: str = "",
    mac_address: str = "",
) -> str | None:
    """Write the generated YAML file to Home Assistant's /config/esphome/ directory."""
    target_dir = os.path.join(hass_config_dir, "esphome")
    if not os.path.exists(target_dir):
        # If /config/esphome doesn't exist, try local config dir
        target_dir = hass_config_dir

    filename = f"{sanitize_filename(device_name)}.yaml"
    file_path = os.path.join(target_dir, filename)

    content = generate_esphome_yaml(
        device_name=device_name,
        friendly_name=friendly_name,
        wifi_ssid=wifi_ssid,
        wifi_password=wifi_password,
        mac_address=mac_address,
    )

    try:
        def _write():
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

        import asyncio
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _write)
        _LOGGER.info("Provisioned ESPHome YAML at %s", file_path)
        return file_path
    except Exception as err:
        _LOGGER.error("Failed to write ESPHome YAML to %s: %s", file_path, err)
        return None
