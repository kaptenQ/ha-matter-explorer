"""Access to HA's own Matter client.

HA 2026.11 keeps the MatterClient of the `matter` config entry at
``entry.runtime_data.adapter.matter_client`` (``MatterEntryData.adapter``). This
is the only module that knows that, so a change in HA's internals is fixed here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from matter_server.common.errors import NodeNotExists

from .const import MATTER_DOMAIN

if TYPE_CHECKING:
    from matter_server.client import MatterClient


class MatterClientUnavailable(HomeAssistantError):
    """The `matter` integration is not loaded or has no usable client."""


def get_matter_client(hass: HomeAssistant) -> MatterClient:
    """Return the MatterClient of the loaded `matter` config entry."""
    entries = hass.config_entries.async_loaded_entries(MATTER_DOMAIN)
    if not entries:
        raise MatterClientUnavailable("The matter integration is not set up or not loaded")
    try:
        client = entries[0].runtime_data.adapter.matter_client
    except AttributeError as err:
        raise MatterClientUnavailable(
            "Unsupported matter integration internals: no adapter.matter_client "
            "in the matter config entry runtime data"
        ) from err
    # `connection.connected` is False while the Matter Server is down or restarting
    connection = getattr(client, "connection", None)
    if connection is not None and getattr(connection, "connected", True) is False:
        raise MatterClientUnavailable("Not connected to the Matter Server")
    return client


def find_node(client: MatterClient, node_id: int) -> Any | None:
    """The node, or None when the server does not know it (any more)."""
    try:
        return client.get_node(node_id)
    except NodeNotExists:
        return None
