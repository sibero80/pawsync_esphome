"""Serve and auto-register the dashboard cards that ship with the integration."""

from __future__ import annotations

import logging
import os
import shutil

from aiohttp import web

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import HomeAssistantView
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant

from .const import CARD_FILENAME, CARD_URL_PATH, CARD_VERSION, DOMAIN

_LOGGER = logging.getLogger(__name__)

_REGISTERED = f"{DOMAIN}_cards_registered"


def _card_path() -> str:
    return os.path.join(os.path.dirname(__file__), "frontend", CARD_FILENAME)


def _card_mtime(path: str) -> int:
    try:
        return int(os.path.getmtime(path))
    except OSError:
        return 0


class PawsyncCardView(HomeAssistantView):
    """Serve pawsync-feeder-card.js, resolved fresh on every request.

    No auth: the frontend fetches Lovelace resources as plain script tags,
    which carry no token. The file is public UI code.
    """

    url = CARD_URL_PATH
    name = f"{DOMAIN}:card"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        path = _card_path()

        def _read() -> bytes | None:
            try:
                with open(path, "rb") as fh:
                    return fh.read()
            except OSError:
                return None

        body = await request.app["hass"].async_add_executor_job(_read)
        if body is None:
            return web.Response(
                status=404,
                text="pawsync-feeder-card.js is missing from the integration directory",
            )
        return web.Response(
            body=body,
            content_type="text/javascript",
            charset="utf-8",
            headers={
                "Cache-Control": "no-cache",
                "Access-Control-Allow-Origin": "*",
            },
        )

    async def head(self, request: web.Request) -> web.Response:
        resp = await self.get(request)
        resp.body = None
        return resp


async def async_register_cards(hass: HomeAssistant) -> None:
    """Idempotently register and serve the PawSync feeder card."""
    path = _card_path()
    if not await hass.async_add_executor_job(os.path.isfile, path):
        _LOGGER.error("PawSync card file missing at %s", path)
        return

    # 1. Register the dedicated HTTP View (supports GET and HEAD without 405)
    if not hass.data.get(_REGISTERED):
        hass.data[_REGISTERED] = True
        try:
            hass.http.register_view(PawsyncCardView())
            _LOGGER.info("Registered PawSync CardView at %s", CARD_URL_PATH)
        except Exception as view_err:
            _LOGGER.warning("Could not register CardView: %s", view_err)

    # 2. Also ensure copy exists in www/ for direct /local/ serving
    def _sync_www() -> None:
        try:
            www_dir = hass.config.path("www")
            os.makedirs(www_dir, exist_ok=True)
            dest = os.path.join(www_dir, CARD_FILENAME)
            shutil.copy2(path, dest)
        except Exception as copy_err:
            _LOGGER.debug("Could not copy card to www: %s", copy_err)

    await hass.async_add_executor_job(_sync_www)

    # 3. Generate versioned URL with mtime stamp
    stamp = await hass.async_add_executor_job(_card_mtime, path)
    url = f"/local/{CARD_FILENAME}?v={CARD_VERSION}&m={stamp}"

    # 4. Auto-register as a true Lovelace Resource
    registered = await _async_register_resource(hass, url)
    if not registered:
        add_extra_js_url(hass, url)
        if hass.state is CoreState.starting:
            async def _retry(_event) -> None:
                if await _async_register_resource(hass, url):
                    _LOGGER.info("PawSync card Lovelace resource registered after startup")
                else:
                    _LOGGER.warning(
                        "Could not auto-register PawSync card in Lovelace resources. "
                        "Add url: %s / type: module in Lovelace Resources.", url
                    )
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _retry)
        else:
            _LOGGER.warning(
                "Could not auto-register PawSync card in Lovelace resources. "
                "Add url: %s / type: module in Lovelace Resources.", url
            )
    else:
        _LOGGER.info("PawSync card automatically registered as Lovelace resource: %s", url)


async def _async_register_resource(hass: HomeAssistant, url: str) -> bool:
    """Add or update the card in Lovelace resources collection."""
    data = hass.data.get("lovelace")
    resources = getattr(data, "resources", None)
    if resources is None and isinstance(data, dict):
        resources = data.get("resources")
    if resources is None or not hasattr(resources, "async_create_item"):
        return False

    try:
        if hasattr(resources, "async_get_info"):
            await resources.async_get_info()
        elif getattr(resources, "loaded", True) is False:
            await resources.async_load()

        existing = [
            item for item in (resources.async_items() or [])
            if CARD_FILENAME in str(item.get("url", ""))
        ]

        if not existing:
            await resources.async_create_item({"res_type": "module", "url": url})
            _LOGGER.info("Registered PawSync card as a new Lovelace resource: %s", url)
            return True

        # Keep exactly one, delete any duplicate entries
        keep, *duplicates = existing
        for dupe in duplicates:
            try:
                await resources.async_delete_item(dupe["id"])
            except Exception:
                pass

        if keep.get("url") != url:
            if hasattr(resources, "async_update_item"):
                await resources.async_update_item(keep["id"], {"res_type": "module", "url": url})
            else:
                keep["url"] = url
            _LOGGER.info("Updated existing PawSync card Lovelace resource to %s", url)
        return True
    except Exception as e:
        _LOGGER.debug("Lovelace resource auto-registration failed: %s", e)
        return False
