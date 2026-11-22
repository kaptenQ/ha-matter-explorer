"""Diagnostics download: options, exposed list, client and server info, counts, recent results.

Nothing here is sensitive, and no node attribute values are included.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from .client import MatterClientUnavailable, get_matter_client
from .const import ISSUE_MATTER_NOT_LOADED, MATTER_DOMAIN
from .errors import ACTIVITY_KEY, DEVICE_TIMEOUT
from .exposure import get_exposed, missing_exposed

_SERVER_FIELDS = (
    "sdk_version",
    "wifi_credentials_set",
    "thread_credentials_set",
    "min_supported_schema_version",
    "schema_version",
    "bluetooth_enabled",
)


def _server_info(client: Any) -> dict[str, Any]:
    info = getattr(client, "server_info", None)
    if info is None:
        return {}
    if is_dataclass(info) and not isinstance(info, type):
        data = asdict(info)
    else:
        data = {k: getattr(info, k) for k in dir(info) if not k.startswith("_")}
    # only plain scalars; fabric ids are public identifiers of this fabric, not secrets
    return {
        k: v
        for k, v in data.items()
        if k in _SERVER_FIELDS or k in ("fabric_id", "compressed_fabric_id")
        if isinstance(v, bool | int | float | str)
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Everything needed to understand a bug report, without attribute dumps."""
    matter_entries = hass.config_entries.async_entries(MATTER_DOMAIN)
    out: dict[str, Any] = {
        "options": dict(entry.options),
        "exposed": get_exposed(entry),
        "device_timeout_s": DEVICE_TIMEOUT,
        "matter_entry_states": [str(e.state) for e in matter_entries],
        "recent_results": list(hass.data.get(ACTIVITY_KEY, [])),
        "entities": len(er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)),
        "issue_open": ir.async_get(hass).async_get_issue(entry.domain, ISSUE_MATTER_NOT_LOADED)
        is not None,
    }
    try:
        client = get_matter_client(hass)
    except MatterClientUnavailable as err:
        out["client"] = {"available": False, "reason": str(err)}
        return out
    nodes = client.get_nodes()
    out["client"] = {
        "available": True,
        "class": type(client).__name__,
        "server_info": _server_info(client),
    }
    out["counts"] = {
        "nodes": len(nodes),
        "nodes_available": sum(1 for n in nodes if n.available),
        "bridges": sum(1 for n in nodes if getattr(n.node_data, "is_bridge", False)),
        "exposed": len(get_exposed(entry)),
        "exposed_missing": len(missing_exposed(client, entry)),
    }
    return out
