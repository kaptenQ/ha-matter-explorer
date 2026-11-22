"""Build the node → endpoint → cluster → attribute tree for the nodes command."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .metadata import (
    CENTI_CELSIUS,
    SETPOINT_LIMITS,
    display_value,
    get_attribute_meta,
    hex_name,
    parse_path,
)
from .writable import describe_write

BASIC_INFORMATION = 40
NODE_LABEL = 5
VENDOR_NAME = 1
VENDOR_ID = 2
PRODUCT_NAME = 3
BRIDGED_DEVICE_BASIC_INFORMATION = 57


def node_name(node_id: int, attributes: dict[str, Any]) -> str:
    """NodeLabel (0/40/5), else vendor + product, else "Node <id>"."""
    label = attributes.get("0/40/5")
    if isinstance(label, str) and label.strip():
        return label.strip()
    parts = [attributes.get("0/40/1"), attributes.get("0/40/3")]
    joined = " ".join(p.strip() for p in parts if isinstance(p, str) and p.strip())
    return joined or f"Node {node_id}"


def bridged_name(attributes: dict[str, Any], endpoint: int) -> str | None:
    """Name of the bridged device on an endpoint: NodeLabel, else ProductName (cluster 57)."""
    for attr in (NODE_LABEL, PRODUCT_NAME):
        value = attributes.get(f"{endpoint}/{BRIDGED_DEVICE_BASIC_INFORMATION}/{attr}")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _vendor_fields(attributes: dict[str, Any], endpoint: int, cluster: int) -> dict[str, Any]:
    """VendorName (1) and VendorID (2) of a (bridged) basic information cluster, if present."""
    out: dict[str, Any] = {}
    name = attributes.get(f"{endpoint}/{cluster}/{VENDOR_NAME}")
    if isinstance(name, str) and name.strip():
        out["vendor"] = name.strip()
    vid = attributes.get(f"{endpoint}/{cluster}/{VENDOR_ID}")
    if isinstance(vid, int) and not isinstance(vid, bool):
        out["vendor_id"] = vid
    return out


def _limits(
    attributes: dict[str, Any], endpoint: int, cluster: int, attribute: int
) -> tuple[int | None, int | None]:
    pair = SETPOINT_LIMITS.get((cluster, attribute))
    if pair is None:
        return None, None
    lo = attributes.get(f"{endpoint}/{cluster}/{pair[0]}")
    hi = attributes.get(f"{endpoint}/{cluster}/{pair[1]}")
    return (
        lo if isinstance(lo, int) and not isinstance(lo, bool) else None,
        hi if isinstance(hi, int) and not isinstance(hi, bool) else None,
    )


def attribute_entry(
    attributes: dict[str, Any], endpoint: int, cluster: int, attribute: int
) -> dict[str, Any]:
    """One attribute with raw value, display value, type and metadata."""
    path = f"{endpoint}/{cluster}/{attribute}"
    value = attributes[path]
    meta = get_attribute_meta(cluster, attribute)
    meta.min, meta.max = _limits(attributes, endpoint, cluster, attribute)
    entry: dict[str, Any] = {
        "attribute_id": attribute,
        "path": path,
        "name": meta.attribute_name,
        "value": value,
        "display_value": display_value(meta, value),
        "unit": "°C" if (cluster, attribute) in CENTI_CELSIUS else None,
        "type": meta.type,
        "meta": meta.as_dict(),
        "write": describe_write(attributes, endpoint, cluster, attribute),
    }
    return entry


def build_node(node: Any, overlay: Callable[[int], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Serialise one MatterNode (only node_id, available and node_data.attributes are used).

    ``overlay(node_id)`` gives raw values newer than the node's snapshot (see live.py).
    """
    attributes: dict[str, Any] = dict(node.node_data.attributes)
    if overlay:
        attributes.update({p: v for p, v in overlay(node.node_id).items() if p in attributes})
    tree: dict[int, dict[int, list[int]]] = {}
    for path in attributes:
        try:
            ep, cl, at = parse_path(path)
        except ValueError:
            continue
        tree.setdefault(ep, {}).setdefault(cl, []).append(at)

    endpoints = []
    for ep in sorted(tree):
        clusters = []
        for cl in sorted(tree[ep]):
            meta = get_attribute_meta(cl, 0)
            clusters.append(
                {
                    "cluster_id": cl,
                    "name": meta.cluster_name,
                    "unknown": meta.unknown_cluster,
                    "attributes": [
                        attribute_entry(attributes, ep, cl, at) for at in sorted(tree[ep][cl])
                    ],
                }
            )
        endpoints.append(
            {
                "endpoint_id": ep,
                "name": bridged_name(attributes, ep),
                # the bridged device's own maker (cluster 57), only when it reports one
                **{
                    f"bridged_{k}": v
                    for k, v in _vendor_fields(
                        attributes, ep, BRIDGED_DEVICE_BASIC_INFORMATION
                    ).items()
                },
                "clusters": clusters,
            }
        )

    return {
        "node_id": node.node_id,
        "name": node_name(node.node_id, attributes),
        "available": bool(node.available),
        "is_bridge": bool(getattr(node.node_data, "is_bridge", False)),
        "vendor": attributes.get("0/40/1"),
        "vendor_id": _vendor_fields(attributes, 0, BASIC_INFORMATION).get("vendor_id"),
        "product": attributes.get("0/40/3"),
        "endpoints": endpoints,
    }


def build_nodes(
    nodes: list[Any], overlay: Callable[[int], dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Serialise all nodes, ordered by node id."""
    return [build_node(n, overlay) for n in sorted(nodes, key=lambda n: n.node_id)]


__all__ = ["build_node", "build_nodes", "hex_name", "node_name"]
