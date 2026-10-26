"""ESPHome YAML Provisioner for Pawsync Pet Feeder."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

from .const import DEFAULT_NOISE_PSK

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
    noise_psk: str = DEFAULT_NOISE_PSK,
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
    key: "{noise_psk}"

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
    noise_psk: str = DEFAULT_NOISE_PSK,
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


def resolve_arp_ip(mac: str) -> str:
    """Resolve IP address from MAC using Linux ARP cache."""
    if not mac:
        return ""
    target_clean = mac.replace(":", "").replace("-", "").strip().lower()
    try:
        with open("/proc/net/arp", "r", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 4:
                    arp_ip = parts[0]
                    arp_mac = parts[3].replace(":", "").replace("-", "").strip().lower()
                    if arp_mac == target_clean and arp_ip != "0.0.0.0":
                        return arp_ip
    except Exception:
        pass
    return ""


async def _advance_esphome_flow(hass: Any, flow_id: str, step_id: str, noise_psk: str) -> bool:
    """Advance an in-progress ESPHome config flow through discovery confirm and noise auth."""
    from homeassistant import config_entries

    try:
        # Step 1: If in discovery_confirm, submit empty dict to accept discovery
        if step_id == "discovery_confirm":
            _LOGGER.info("Accepting ESPHome discovery confirmation for flow %s...", flow_id)
            conf_res = await hass.config_entries.flow.async_configure(flow_id, user_input={})
            _LOGGER.debug("Discovery confirm result: %s", conf_res)
            step_id = conf_res.get("step_id")
            if conf_res.get("type") == config_entries.FlowResultType.CREATE_ENTRY:
                _LOGGER.info("ESPHome entry created directly from discovery confirm: %s", flow_id)
                return True

        # Step 2: If in authenticate step, provide Noise PSK
        if step_id == "authenticate":
            _LOGGER.info("Supplying Noise PSK encryption key to ESPHome flow %s...", flow_id)
            auth_res = await hass.config_entries.flow.async_configure(
                flow_id,
                user_input={"noise_psk": noise_psk},
            )
            _LOGGER.info("ESPHome flow %s authenticated result: %s", flow_id, auth_res.get("type"))
            return auth_res.get("type") in (
                config_entries.FlowResultType.CREATE_ENTRY,
                config_entries.FlowResultType.ABORT,
            )
    except Exception as err:
        _LOGGER.warning("Could not advance ESPHome flow %s: %s", flow_id, err)

    return False


async def async_auto_adopt_esphome(
    hass: Any,
    host: str,
    noise_psk: str = DEFAULT_NOISE_PSK,
    mac: str | None = None,
    feeder_name: str = "Pawsync Feeder",
    max_attempts: int = 40,
    delay: float = 3.0,
) -> bool:
    """Automatically adopt the ESPHome feeder device into Home Assistant.

    Monitors network connectivity to port 6053 and auto-completes the ESPHome
    config flow with the pre-configured Noise PSK encryption key.
    """
    _LOGGER.info("Starting automated ESPHome adoption monitor for host: %s (MAC: %s)", host, mac)
    clean_mac = mac.replace(":", "").replace("-", "").strip().lower() if mac else ""

    for attempt in range(1, max_attempts + 1):
        # Dynamically resolve IP if missing or stale
        if not host and mac:
            host = resolve_arp_ip(mac)
            if host:
                _LOGGER.info("Dynamically resolved feeder IP from ARP: %s", host)

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
                from homeassistant import config_entries

                result = await hass.config_entries.flow.async_init(
                    "esphome",
                    context={"source": config_entries.SOURCE_USER},
                    data={"host": host, "port": 6053},
                )
                _LOGGER.debug("ESPHome async_init result: %s", result)

                res_type = result.get("type")
                flow_id = result.get("flow_id")
                step_id = result.get("step_id")

                if res_type == config_entries.FlowResultType.FORM and flow_id:
                    success = await _advance_esphome_flow(hass, flow_id, step_id, noise_psk)
                    if success:
                        return True
                elif res_type == config_entries.FlowResultType.CREATE_ENTRY:
                    _LOGGER.info("ESPHome entry created for %s", host)
                    return True
                elif res_type == config_entries.FlowResultType.ABORT and result.get("reason") == "already_in_progress":
                    # Pending flow is blocking user flow, advance the pending flow
                    for pflow in hass.config_entries.flow.async_progress_by_handler("esphome"):
                        p_id = pflow.get("flow_id")
                        p_step = pflow.get("step_id")
                        if p_id:
                            success = await _advance_esphome_flow(hass, p_id, p_step, noise_psk)
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

