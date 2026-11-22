"""Admin-only websocket commands."""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.loader import async_get_integration

from .client import MatterClientUnavailable, get_matter_client
from .commands import IDENTIFY_DEFAULT, IDENTIFY_MAX, IDENTIFY_MIN, CommandRefused, async_identify
from .const import DOMAIN, STORE_KEY
from .errors import CLIENT_ERRORS, error_text
from .export import build_export
from .exposure import ExposeError, annotate_nodes, async_set_exposed, missing_exposed
from .nodes import build_nodes
from .writable import MAX_BATCH, WriteRefused, async_write, async_write_many

_LOGGER = logging.getLogger(__name__)

# "endpoint/cluster/attribute", decimal ints (HA's schema error is the answer to anything else)
PATH_RE = re.compile(r"^[0-9]{1,5}/[0-9]{1,10}/[0-9]{1,10}$")
_path = vol.All(str, vol.Match(PATH_RE))


def _int(lo: int, hi: int) -> Callable[[Any], int]:
    """An int in lo..hi; a bool is not an int here."""

    def check(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise vol.Invalid("expected an integer")
        if not lo <= value <= hi:
            raise vol.Invalid(f"expected {lo}..{hi}")
        return value

    return check


_node_id = _int(0, 2**64 - 1)
_endpoint_id = _int(0, 65534)
_value = vol.Any(bool, _int(-(2**63), 2**64 - 1), vol.All(str, vol.Length(max=256)))

WsHandler = Callable[
    [HomeAssistant, websocket_api.ActiveConnection, dict[str, Any]], Awaitable[None]
]


def _guarded(handler: WsHandler) -> WsHandler:
    """Turn client errors into error replies and log anything unexpected with its traceback.

    The error reply is never a traceback: ``matter_unavailable`` when matter / the Matter Server
    is not there, ``matter_error`` for an error of the client, ``unknown_error`` for a bug.
    """

    async def wrapper(
        hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
    ) -> None:
        try:
            await handler(hass, connection, msg)
        except MatterClientUnavailable as err:
            connection.send_error(msg["id"], "matter_unavailable", str(err))
        except CLIENT_ERRORS as err:
            _LOGGER.warning("%s failed: %s", msg.get("type"), error_text(err))
            connection.send_error(msg["id"], "matter_error", error_text(err))
        except Exception:  # outer edge of a websocket command
            _LOGGER.exception("Unexpected error in %s", msg.get("type"))
            connection.send_error(msg["id"], "unknown_error", "Unexpected error, see the log")

    wrapper.__name__ = handler.__name__
    return wrapper


@callback
def async_register_commands(hass: HomeAssistant) -> None:
    """Register the websocket commands."""
    websocket_api.async_register_command(hass, ws_nodes)
    websocket_api.async_register_command(hass, ws_export)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_write)
    websocket_api.async_register_command(hass, ws_write_many)
    websocket_api.async_register_command(hass, ws_set_exposed)
    websocket_api.async_register_command(hass, ws_identify)


@websocket_api.require_admin
@websocket_api.websocket_command({"type": f"{DOMAIN}/nodes"})
@websocket_api.async_response
@_guarded
async def ws_nodes(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return every node with all endpoints, clusters and attributes."""
    client = get_matter_client(hass)
    store = hass.data.get(STORE_KEY)
    overlay = store.overlay if store else None
    nodes = build_nodes(client.get_nodes(), overlay)
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    entry = entries[0] if entries else None
    annotate_nodes(hass, entry, client, nodes)
    connection.send_result(
        msg["id"], {"nodes": nodes, "missing_exposed": missing_exposed(client, entry)}
    )


@websocket_api.require_admin
@websocket_api.websocket_command({"type": f"{DOMAIN}/export", vol.Optional("node_id"): _node_id})
@websocket_api.async_response
@_guarded
async def ws_export(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the diagnostics export of one node or the whole fabric (read-only)."""
    client = get_matter_client(hass)
    store = hass.data.get(STORE_KEY)
    overlay = store.overlay if store else None
    node_id = msg.get("node_id")
    if node_id is not None and all(n.node_id != node_id for n in client.get_nodes()):
        connection.send_error(msg["id"], "node_not_found", f"Node {node_id} does not exist")
        return
    integration = await async_get_integration(hass, DOMAIN)
    connection.send_result(
        msg["id"], build_export(client, str(integration.version), overlay, node_id)
    )


@websocket_api.require_admin
@websocket_api.websocket_command({"type": f"{DOMAIN}/subscribe"})
@websocket_api.async_response
@_guarded
async def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Forward attribute updates and node availability changes from the shared MatterClient."""
    get_matter_client(hass)
    store = hass.data.get(STORE_KEY)
    if store is None:
        connection.send_error(msg["id"], "matter_unavailable", "Matter Explorer is not set up")
        return

    msg_id = msg["id"]

    @callback
    def send(payload: dict[str, Any]) -> None:
        connection.send_message(websocket_api.event_message(msg_id, payload))

    connection.subscriptions[msg_id] = store.add_listener(send)
    connection.send_result(msg_id)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        "type": f"{DOMAIN}/write",
        vol.Required("node_id"): _node_id,
        vol.Required("path"): _path,
        vol.Required("value"): _value,
    }
)
@websocket_api.async_response
@_guarded
async def ws_write(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Write one attribute through the write gate and return the read-back."""
    try:
        result = await async_write(hass, msg["node_id"], msg["path"], msg["value"])
    except WriteRefused as err:
        connection.send_error(msg["id"], err.code, str(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        "type": f"{DOMAIN}/write_many",
        vol.Required("items"): vol.All(
            [{vol.Required("node_id"): _node_id, vol.Required("path"): _path}],
            vol.Length(min=1, max=MAX_BATCH),
        ),
        vol.Required("value"): _value,
    }
)
@websocket_api.async_response
@_guarded
async def ws_write_many(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Write one value to many attributes, sequentially, streaming progress events.

    The result is an acknowledgement; events follow: {event: progress, done, total, item}
    per attribute, then {event: done, results}.
    """
    msg_id = msg["id"]
    get_matter_client(hass)
    connection.send_result(msg_id)

    def progress(done: int, total: int, item: dict[str, Any]) -> None:
        connection.send_message(
            websocket_api.event_message(
                msg_id, {"event": "progress", "done": done, "total": total, "item": item}
            )
        )

    results = await async_write_many(hass, msg["items"], msg["value"], progress)
    connection.send_message(
        websocket_api.event_message(msg_id, {"event": "done", "results": results})
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        "type": f"{DOMAIN}/set_exposed",
        vol.Required("node_id"): _node_id,
        vol.Required("path"): vol.All(str, vol.Length(max=64)),
        vol.Required("exposed"): bool,
    }
)
@websocket_api.async_response
@_guarded
async def ws_set_exposed(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Tick or untick "Add as entity" for one attribute."""
    client = get_matter_client(hass)
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "not_loaded", "Matter Explorer is not set up")
        return
    try:
        result = await async_set_exposed(
            hass, entries[0], client, msg["node_id"], msg["path"], msg["exposed"]
        )
    except ExposeError as err:
        connection.send_error(msg["id"], err.code, str(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        "type": f"{DOMAIN}/identify",
        vol.Required("node_id"): _node_id,
        vol.Required("endpoint_id"): _endpoint_id,
        vol.Optional("identify_time", default=IDENTIFY_DEFAULT): _int(IDENTIFY_MIN, IDENTIFY_MAX),
    }
)
@websocket_api.async_response
@_guarded
async def ws_identify(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Send Identify to one endpoint through the command gate."""
    try:
        result = await async_identify(
            hass, msg["node_id"], msg["endpoint_id"], msg["identify_time"]
        )
    except CommandRefused as err:
        connection.send_error(msg["id"], err.code, str(err))
        return
    connection.send_result(msg["id"], result)
