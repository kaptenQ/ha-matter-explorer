"""The "Add as entity" list: option storage, attribute -> entity mapping, set_exposed.

Ticked list in the config entry options: `{"exposed": [{"node_id": 6, "path": "1/516/1"}]}`
(no values). ``build_spec`` decides which platform an attribute becomes; writable platforms are only
offered for attributes the write gate (writable.py) accepts, and they write through ``async_write``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .client import MatterClientUnavailable, find_node, get_matter_client
from .const import CONF_EXPOSED, DOMAIN
from .errors import log_limited
from .metadata import BOOL, CENTI_CELSIUS, ENUM, friendly_labels, get_attribute_meta, parse_path
from .writable import describe_write, writable_spec

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

# Friendlier names than the spec's attribute name
FRIENDLY_NAMES: dict[tuple[int, int], str] = {(516, 1): "Child lock"}
# Scalar state is capped by HA at 255 characters
MAX_STATE = 255
_lock_key = f"{DOMAIN}_exposed_lock"


@dataclass
class ExposeSpec:
    """How one attribute becomes an entity."""

    platform: Platform
    name: str
    scale: int = 1  # raw = native * scale (100 for 0.01 °C)
    unit: str | None = None
    device_class: str | None = None
    options: dict[int, str] | None = None  # enum raw value -> label
    min: float | None = None  # native units
    max: float | None = None
    step: float = 1
    writable: bool = False


def friendly_name(cluster: int, attribute: int, attribute_name: str) -> str:
    """ "Child lock" for 516/1, else the CamelCase attribute name split into words."""
    if (cluster, attribute) in FRIENDLY_NAMES:
        return FRIENDLY_NAMES[cluster, attribute]
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", attribute_name)
    return words[:1].upper() + words[1:].lower() if words else attribute_name


def build_spec(attributes: dict[str, Any], path: str) -> ExposeSpec | None:
    """The entity an attribute becomes, or None if the path is invalid / absent."""
    if path not in attributes:
        return None
    try:
        endpoint, cluster, attribute = parse_path(path)
    except ValueError:
        return None
    meta = get_attribute_meta(cluster, attribute)
    key = (cluster, attribute)
    name = friendly_name(cluster, attribute, meta.attribute_name)
    celsius = key in CENTI_CELSIUS
    scale = 100 if celsius else 1
    unit = "°C" if celsius else None
    device_class = "temperature" if celsius else None

    write = describe_write(attributes, endpoint, cluster, attribute)
    if write is not None:
        spec = writable_spec(cluster, attribute)
        if write["type"] == "bool":
            return ExposeSpec(Platform.SWITCH, name, writable=True)
        if write["type"] == "enum" and spec is not None and spec.values:
            labels = friendly_labels(cluster, attribute) or {
                v: (meta.enum_values or {}).get(v, lbl) for v, lbl in spec.values.items()
            }
            return ExposeSpec(Platform.SELECT, name, options=dict(labels), writable=True)
        if write["type"] == "int":
            lo, hi = write["min"], write["max"]
            return ExposeSpec(
                Platform.NUMBER,
                name,
                scale=scale,
                unit=unit,
                device_class=device_class,
                min=lo / scale,
                max=hi / scale,
                step=0.5 if celsius else 1,
                writable=True,
            )
    if meta.type == BOOL:
        return ExposeSpec(Platform.BINARY_SENSOR, name)
    options = None
    if meta.type == ENUM and meta.enum_values:
        options = dict(meta.enum_values)
        device_class = "enum"
    return ExposeSpec(
        Platform.SENSOR, name, scale=scale, unit=unit, device_class=device_class, options=options
    )


def get_exposed(entry: ConfigEntry) -> list[dict[str, Any]]:
    """The ticked list from the options. Malformed items are skipped, with one warning each."""
    raw = entry.options.get(CONF_EXPOSED, [])
    if not isinstance(raw, list):
        log_limited(_LOGGER, ("malformed", "list"), "Ignoring malformed exposed list: %r", raw)
        return []
    items = []
    for item in raw:
        node_id = item.get("node_id") if isinstance(item, dict) else None
        path = item.get("path") if isinstance(item, dict) else None
        if isinstance(node_id, int) and not isinstance(node_id, bool) and isinstance(path, str):
            try:
                parse_path(path)
            except ValueError:
                pass
            else:
                items.append({"node_id": node_id, "path": path})
                continue
        log_limited(_LOGGER, ("malformed", repr(item)), "Ignoring malformed exposed item: %r", item)
    return items


def missing_exposed(client: Any, entry: ConfigEntry | None) -> list[dict[str, Any]]:
    """Ticked items whose node or attribute is gone: [{node_id, path, reason}]."""
    if entry is None:
        return []
    missing = []
    for item in get_exposed(entry):
        node = find_node(client, item["node_id"])
        reason: str | None
        if node is None:
            reason = "node not found"
        else:
            reason = None if item["path"] in node.node_data.attributes else "attribute not found"
        if reason:
            log_limited(
                _LOGGER, ("missing", item["node_id"], item["path"]),
                "Exposed attribute %s of node %s is missing (%s)",
                item["path"], item["node_id"], reason,
            )  # fmt: skip
            missing.append({**item, "reason": reason})
    return missing


def fabric_id(client: Any) -> str:
    """Compressed fabric id of the server (hex), the stable part of unique ids."""
    info = getattr(client, "server_info", None)
    for attr in ("compressed_fabric_id", "fabric_id"):
        value = getattr(info, attr, None)
        if isinstance(value, int):
            return f"{value:016X}"
    return "unknown"


def make_unique_id(client: Any, node_id: int, path: str) -> str:
    """matter_explorer_<fabric>_<node>_<ep>_<cluster>_<attr>."""
    endpoint, cluster, attribute = parse_path(path)
    return f"{DOMAIN}_{fabric_id(client)}_{node_id}_{endpoint}_{cluster}_{attribute}"


def entity_id_for(
    hass: HomeAssistant, client: Any, node_id: int, path: str, spec: ExposeSpec
) -> str | None:
    """The entity_id of a ticked attribute once its entity exists."""
    return er.async_get(hass).async_get_entity_id(
        spec.platform, DOMAIN, make_unique_id(client, node_id, path)
    )


def annotate_nodes(
    hass: HomeAssistant, entry: ConfigEntry | None, client: Any, nodes: list[dict[str, Any]]
) -> None:
    """Add ``entity`` (platform, exposed, entity_id) to every attribute of build_nodes output."""
    ticked = {(i["node_id"], i["path"]) for i in get_exposed(entry)} if entry else set()
    for node in nodes:
        attributes = {
            a["path"]: a["value"]
            for e in node["endpoints"]
            for c in e["clusters"]
            for a in c["attributes"]
        }
        for endpoint in node["endpoints"]:
            for cluster in endpoint["clusters"]:
                for attr in cluster["attributes"]:
                    spec = build_spec(attributes, attr["path"])
                    exposed = (node["node_id"], attr["path"]) in ticked
                    attr["entity"] = {
                        "platform": spec.platform.value if spec else None,
                        "exposed": exposed,
                        "entity_id": entity_id_for(
                            hass, client, node["node_id"], attr["path"], spec
                        )
                        if spec and exposed
                        else None,
                    }


class ExposeError(Exception):
    """set_exposed refused the request."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


async def async_apply_exposed(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entity platforms for the current options and drop entities no longer ticked."""
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    remove_stale_entities(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)


def remove_stale_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove this entry's entity registry entries whose item is no longer in the options."""
    try:
        client = get_matter_client(hass)
    except MatterClientUnavailable:  # matter not loaded: nothing to compare against
        return
    keep = {make_unique_id(client, i["node_id"], i["path"]) for i in get_exposed(entry)}
    registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.unique_id not in keep:
            registry.async_remove(reg_entry.entity_id)


async def async_set_exposed(
    hass: HomeAssistant,
    entry: ConfigEntry,
    client: Any,
    node_id: int,
    path: str,
    exposed: bool,
) -> dict[str, Any]:
    """Add or remove one item, store it in the options, and reload the platforms."""
    if exposed:  # unticking works for any stored path, even a broken one
        try:
            parse_path(path)
        except ValueError as err:
            raise ExposeError("invalid_path", f"Bad attribute path {path!r}") from err
    lock = hass.data.setdefault(_lock_key, asyncio.Lock())
    async with lock:
        items = get_exposed(entry)
        present = any(i["node_id"] == node_id and i["path"] == path for i in items)
        if exposed and not present:
            node = find_node(client, node_id)
            if node is None:
                raise ExposeError("node_not_found", f"Node {node_id} does not exist")
            spec = build_spec(dict(node.node_data.attributes), path)
            if spec is None:
                raise ExposeError("not_found", f"{path} does not exist on node {node_id}")
            items.append({"node_id": node_id, "path": path})
        elif not exposed and present:
            items = [i for i in items if not (i["node_id"] == node_id and i["path"] == path)]
        if exposed != present:
            hass.config_entries.async_update_entry(
                entry, options={**entry.options, CONF_EXPOSED: items}
            )
            await async_apply_exposed(hass, entry)
    entity_id = None
    if exposed:
        node = find_node(client, node_id)
        spec = None if node is None else build_spec(dict(node.node_data.attributes), path)
        if spec:
            entity_id = entity_id_for(hass, client, node_id, path, spec)
    return {"exposed": exposed, "entity_id": entity_id, "items": get_exposed(entry)}
