"""ESPHome YAML Provisioner for Pawsync Pet Feeder."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

from .const import generate_noise_psk, generate_ota_password
from .pawsync_api import resolve_ip_from_mac

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
    noise_psk: str | None = None,
    ota_password: str | None = None,
) -> str:
    """Generate ESPHome YAML configuration referencing the remote package."""
    clean_name = sanitize_filename(device_name)
    mac_comment = f"# Device MAC: {mac_address}\n" if mac_address else ""
    key = noise_psk or generate_noise_psk()
    ota_pass = ota_password or generate_ota_password()

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
    key: "{key}"

ota:
  - platform: esphome
    password: "{ota_pass}"
"""
    return yaml_content


async def async_provision_esphome_yaml(
    hass_config_dir: str,
    device_name: str,
    friendly_name: str,
    wifi_ssid: str = "",
    wifi_password: str = "",
    mac_address: str = "",
    noise_psk: str | None = None,
    ota_password: str | None = None,
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
        noise_psk=noise_psk,
        ota_password=ota_password,
    )

    try:
        def _write():
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _write)
        _LOGGER.info("Provisioned ESPHome YAML at %s", file_path)
        return file_path
    except Exception as err:
        _LOGGER.error("Failed to write ESPHome YAML to %s: %s", file_path, err)
        return None


def resolve_arp_ip(mac: str, hass: Any = None) -> str:
    """Resolve IP address from MAC using portable multi-tiered resolution."""
    return resolve_ip_from_mac(mac, hass=hass)


def _is_flow_type(res: dict[str, Any] | None, *types: str) -> bool:
    """Check if flow result matches any expected type (handles string or Enum)."""
    if not isinstance(res, dict):
        return False
    t = res.get("type")
    if t is None:
        return False
    t_str = t.value if hasattr(t, "value") else str(t)
    t_clean = t_str.lower().strip()
    return t_clean in types or any(t_clean.endswith(f".{tp}") for tp in types)


async def _advance_esphome_flow(hass: Any, flow_id: str, step_id: str | None, noise_psk: str) -> bool:
    """Advance an in-progress ESPHome config flow through discovery confirm and noise auth."""
    try:
        # If step_id is unknown or None, query the flow state without submitting
        if not step_id:
            cur_res = await hass.config_entries.flow.async_configure(flow_id)
            step_id = cur_res.get("step_id")
            _LOGGER.debug("Queried ESPHome flow %s current step: %s", flow_id, step_id)

        # Loop through steps until entry is created or abort/failure
        for _ in range(5):
            if not step_id:
                break

            if step_id == "discovery_confirm":
                _LOGGER.info("Accepting ESPHome discovery confirmation for flow %s...", flow_id)
                res = await hass.config_entries.flow.async_configure(flow_id, user_input={})
                _LOGGER.debug("Discovery confirm result: %s", res)
                if _is_flow_type(res, "create_entry"):
                    _LOGGER.info("ESPHome entry created directly from discovery confirm: %s", flow_id)
                    return True
                step_id = res.get("step_id")

            elif step_id == "encryption_key":
                _LOGGER.info("Supplying Noise PSK encryption key to ESPHome flow %s...", flow_id)
                res = await hass.config_entries.flow.async_configure(
                    flow_id,
                    user_input={"noise_psk": noise_psk},
                )
                _LOGGER.info("ESPHome flow %s encryption result: %s", flow_id, res.get("type"))
                if _is_flow_type(res, "create_entry", "abort"):
                    return True
                step_id = res.get("step_id")

            elif step_id == "authenticate":
                _LOGGER.info("Supplying authentication to ESPHome flow %s...", flow_id)
                res = await hass.config_entries.flow.async_configure(
                    flow_id,
                    user_input={"password": "", "noise_psk": noise_psk},
                )
                _LOGGER.info("ESPHome flow %s auth result: %s", flow_id, res.get("type"))
                if _is_flow_type(res, "create_entry", "abort"):
                    return True
                step_id = res.get("step_id")

            elif _is_flow_type(step_id, "create_entry"):
                return True
            else:
                _LOGGER.debug("Unhandled ESPHome step %s for flow %s", step_id, flow_id)
                break

    except Exception as err:
        _LOGGER.warning("Could not advance ESPHome flow %s: %s", flow_id, err)

    return False


async def async_auto_adopt_esphome(
    hass: Any,
    host: str,
    noise_psk: str | None = None,
    mac: str | None = None,
    feeder_name: str = "Pawsync Feeder",
    max_attempts: int = 40,
    delay: float = 3.0,
) -> bool:
    """Automatically adopt the ESPHome feeder device into Home Assistant.

    Monitors network connectivity to port 6053 and auto-completes the ESPHome
    config flow with the pre-configured Noise PSK encryption key.
    """
    effective_psk = noise_psk or generate_noise_psk()
    _LOGGER.info("Starting automated ESPHome adoption monitor for host: %s (MAC: %s)", host, mac)
    clean_mac = mac.replace(":", "").replace("-", "").strip().lower() if mac else ""

    for attempt in range(1, max_attempts + 1):
        # Dynamically resolve IP if missing or stale
        if not host and mac:
            host = resolve_arp_ip(mac, hass=hass)
            if host:
                _LOGGER.info("Dynamically resolved feeder IP from discovery: %s", host)

        # 1. Check if ESPHome config entry already exists
        try:
            for entry in hass.config_entries.async_entries("esphome"):
                entry_host = entry.data.get("host")
                entry_mac = (entry.unique_id or "").replace(":", "").replace("-", "").strip().lower()
                if (host and entry_host == host) or (clean_mac and entry_mac and entry_mac == clean_mac):
                    _LOGGER.info(
                        "ESPHome entry already active in Home Assistant for %s (%s)",
                        entry.title,
                        entry.entry_id,
                    )
                    return True
        except Exception as entry_err:
            _LOGGER.debug("Note inspecting active ESPHome entries: %s", entry_err)

        # 2. Check for in-progress zeroconf discovery flows for esphome
        try:
            progress_flows = hass.config_entries.flow.async_progress_by_handler("esphome")
            for flow in progress_flows:
                flow_id = flow.get("flow_id")
                step_id = flow.get("step_id")
                flow_context = flow.get("context", {})
                flow_uid = (flow_context.get("unique_id") or "").replace(":", "").replace("-", "").strip().lower()
                
                # Match by MAC, host, or if this is the only pending ESPHome flow
                match = (
                    (clean_mac and flow_uid and clean_mac in flow_uid)
                    or (clean_mac and clean_mac in str(flow).lower())
                    or (mac and mac.lower() in str(flow).lower())
                    or (host and host in str(flow))
                    or len(progress_flows) == 1
                )
                if match and flow_id:
                    _LOGGER.info("Found matching in-progress ESPHome flow %s (step: %s)", flow_id, step_id)
                    success = await _advance_esphome_flow(hass, flow_id, step_id, noise_psk)
                    if success:
                        return True
        except Exception as flow_err:
            _LOGGER.debug("Note inspecting in-progress ESPHome flows: %s", flow_err)

        # 3. Check if TCP port 6053 is open on the feeder
        is_port_open = False
        if host:
            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, 6053), timeout=1.5
                )
                writer.close()
                await writer.wait_closed()
                is_port_open = True
            except Exception:
                is_port_open = False

        # 4. If port is reachable, initiate the user config flow
        if is_port_open:
            _LOGGER.info(
                "Feeder ESPHome port 6053 is REACHABLE at %s (attempt %d/%d)! Initiating adoption flow...",
                host,
                attempt,
                max_attempts,
            )
            try:
                result = await hass.config_entries.flow.async_init(
                    "esphome",
                    context={"source": "user"},
                    data={"host": host, "port": 6053},
                )
                _LOGGER.debug("ESPHome async_init result: %s", result)

                flow_id = result.get("flow_id")
                step_id = result.get("step_id")

                if _is_flow_type(result, "form") and flow_id:
                    success = await _advance_esphome_flow(hass, flow_id, step_id, effective_psk)
                    if success:
                        return True
                elif _is_flow_type(result, "create_entry"):
                    _LOGGER.info("ESPHome entry created for %s", host)
                    return True
                elif _is_flow_type(result, "abort") and result.get("reason") == "already_in_progress":
                    # Pending flow is blocking user flow, advance the pending flow
                    for pflow in hass.config_entries.flow.async_progress_by_handler("esphome"):
                        p_id = pflow.get("flow_id")
                        p_step = pflow.get("step_id")
                        if p_id:
                            success = await _advance_esphome_flow(hass, p_id, p_step, effective_psk)
                            if success:
                                return True
            except Exception as init_err:
                _LOGGER.warning("Could not complete ESPHome config flow for %s: %s", host, init_err)

        await asyncio.sleep(delay)

    _LOGGER.warning(
        "ESPHome auto-adoption timed out after %d attempts (%s). Feeder may still be discovered by zeroconf.",
        max_attempts,
        host,
    )
    return False

