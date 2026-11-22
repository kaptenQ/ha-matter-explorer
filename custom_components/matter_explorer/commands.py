"""The one command gate: the only place that calls ``send_device_command``.

Commands are allowed only through this allow-list; anything else is refused without touching the
client. Today the list holds Identify (cluster 3, command 0, ``identifyTime`` 1-60 s), a harmless
command that makes a device blink or beep so you can tell which physical device is which.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .client import find_node, get_matter_client
from .errors import DEVICE_TIMEOUT, record_activity, run_device_call

_LOGGER = logging.getLogger(__name__)

IDENTIFY_CLUSTER = 3
IDENTIFY_COMMAND = 0
IDENTIFY_MIN = 1
IDENTIFY_MAX = 60
IDENTIFY_DEFAULT = 15

# (cluster id, command id) -> command name; the allow-list
ALLOWED_COMMANDS: dict[tuple[int, int], str] = {(IDENTIFY_CLUSTER, IDENTIFY_COMMAND): "Identify"}


class CommandRefused(HomeAssistantError):
    """The gate refused the command (nothing was sent to the device)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


async def async_identify(
    hass: HomeAssistant, node_id: int, endpoint_id: int, identify_time: int = IDENTIFY_DEFAULT
) -> dict[str, Any]:
    """Send Identify (cluster 3, command 0) to one endpoint. Raises CommandRefused."""
    return await async_command(
        hass, node_id, endpoint_id, IDENTIFY_CLUSTER, IDENTIFY_COMMAND,
        {"identifyTime": identify_time},
    )  # fmt: skip


async def async_command(
    hass: HomeAssistant,
    node_id: int,
    endpoint_id: int,
    cluster_id: int,
    command_id: int,
    args: dict[str, Any],
) -> dict[str, Any]:
    """The command gate: allow-list, checks, send."""
    if (cluster_id, command_id) not in ALLOWED_COMMANDS:
        raise CommandRefused(
            "command_not_allowed", f"Command {cluster_id}/{command_id} is not allowed"
        )
    if set(args) != {"identifyTime"}:
        raise CommandRefused("invalid_value", "Identify takes only identifyTime")
    time = args["identifyTime"]
    if (
        isinstance(time, bool)
        or not isinstance(time, int)
        or not IDENTIFY_MIN <= time <= IDENTIFY_MAX
    ):
        raise CommandRefused(
            "invalid_value", f"identifyTime must be {IDENTIFY_MIN}-{IDENTIFY_MAX} seconds"
        )
    client = get_matter_client(hass)
    node = find_node(client, node_id)
    if node is None:
        raise CommandRefused("node_not_found", f"Node {node_id} does not exist")
    if not node.available:
        raise CommandRefused("node_unavailable", f"Node {node_id} is unavailable")
    prefix = f"{endpoint_id}/{IDENTIFY_CLUSTER}/"
    if not any(p.startswith(prefix) for p in node.node_data.attributes):
        raise CommandRefused(
            "no_identify", f"Endpoint {endpoint_id} of node {node_id} has no Identify cluster"
        )
    from chip.clusters import Objects as O  # noqa: N817

    command = O.Identify.Commands.Identify(identifyTime=time)
    _LOGGER.info(
        "Matter command node=%s endpoint=%s Identify identifyTime=%s", node_id, endpoint_id, time
    )
    await run_device_call(
        hass, _LOGGER, "command", f"command node={node_id} endpoint={endpoint_id} Identify",
        "Identify", client.send_device_command(node_id, endpoint_id, command), CommandRefused,
        device_timeout=DEVICE_TIMEOUT, node_id=node_id, endpoint_id=endpoint_id, command="Identify",
    )  # fmt: skip
    record_activity(
        hass,
        "command",
        node_id=node_id,
        endpoint_id=endpoint_id,
        command="Identify",
        ok=True,
        identify_time=time,
    )
    return {"ok": True, "identify_time": time}
