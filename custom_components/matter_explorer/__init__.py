"""Matter Explorer: browse every attribute of every Matter node known to HA."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .client import MatterClientUnavailable, get_matter_client
from .const import DOMAIN, ISSUE_MATTER_NOT_LOADED, MATTER_DOMAIN, SIGNAL_MATTER_STATE, STORE_KEY
from .exposure import PLATFORMS, remove_stale_entities
from .live import LiveStore
from .websocket_api import async_register_commands

_LOGGER = logging.getLogger(__name__)

PANEL_URL_PATH = "matter-explorer"
STATIC_URL = "/matter_explorer_static"
FRONTEND_DIR = Path(__file__).parent / "frontend"
_STATIC_KEY = f"{DOMAIN}_static_registered"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the websocket commands once."""
    async_register_commands(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from the config entry; needs a loaded matter entry."""
    try:
        client = get_matter_client(hass)
    except MatterClientUnavailable as err:
        _async_set_matter_issue(hass, True, str(err))
        raise ConfigEntryNotReady(str(err)) from err
    _async_set_matter_issue(hass, False)
    hass.data[STORE_KEY] = LiveStore(client)
    _async_follow_matter_client(hass, entry, client)
    await _async_register_panel(hass)
    remove_stale_entities(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


@callback
def _async_set_matter_issue(hass: HomeAssistant, missing: bool, reason: str = "") -> None:
    """Open a repair issue while HA's matter entry is missing or not loaded; clear it when back."""
    if not missing:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_MATTER_NOT_LOADED)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_MATTER_NOT_LOADED,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_MATTER_NOT_LOADED,
        translation_placeholders={"reason": reason or "not loaded"},
    )


@callback
def _async_follow_matter_client(hass: HomeAssistant, entry: ConfigEntry, client: object) -> None:
    """Reload this entry when the matter entry comes back with a new MatterClient.

    HA's matter integration reloads itself whenever the connection to the Matter Server drops, and
    the reloaded entry has a new client object. The live store and the entities are subscribed to
    the old one, and the new client never writes live updates into its node snapshots, so values
    would stay frozen at the reconnect snapshot until HA restarts.
    """
    matter_entries = hass.config_entries.async_entries(MATTER_DOMAIN)
    if not matter_entries:
        return
    matter_entry = matter_entries[0]

    @callback
    def on_state_change() -> None:
        try:
            current = get_matter_client(hass)
        except MatterClientUnavailable as err:
            # unloaded, in setup-retry or disconnected: entities go unavailable until it is back
            _LOGGER.warning("Matter is not available: %s", err)
            _async_set_matter_issue(hass, True, str(err))
            async_dispatcher_send(hass, SIGNAL_MATTER_STATE)
            return
        _async_set_matter_issue(hass, False)
        if current is not client:
            hass.config_entries.async_schedule_reload(entry.entry_id)
        else:
            async_dispatcher_send(hass, SIGNAL_MATTER_STATE)

    entry.async_on_unload(matter_entry.async_on_state_change(on_state_change))


async def _async_register_panel(hass: HomeAssistant) -> None:
    """Serve frontend/ and add the admin-only sidebar panel."""
    if not hass.data.get(_STATIC_KEY):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(FRONTEND_DIR), cache_headers=False)]
        )
        hass.data[_STATIC_KEY] = True
    # The version in the URL makes the browser load the new entry module after an update; the
    # modules it imports (relative, no build step) are revalidated: no cache headers are sent.
    version = (await async_get_integration(hass, DOMAIN)).version
    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="matter-explorer-panel",
        frontend_url_path=PANEL_URL_PATH,
        module_url=f"{STATIC_URL}/matter-explorer-panel.js?v={version}",
        sidebar_title="Matter Explorer",
        sidebar_icon="mdi:graph-outline",
        require_admin=True,
        config={},
        embed_iframe=False,
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the entry and remove the panel."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    frontend.async_remove_panel(hass, PANEL_URL_PATH)
    if store := hass.data.pop(STORE_KEY, None):
        store.close()
    _async_set_matter_issue(hass, False)
    return unloaded


__all__ = ["DOMAIN", "async_setup", "async_setup_entry", "async_unload_entry"]
