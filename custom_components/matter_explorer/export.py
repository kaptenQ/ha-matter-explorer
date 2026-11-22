"""Diagnostics export: one flat, stable JSON document of nodes and attributes.

Built from the same tree as the nodes command (``nodes.build_nodes``), so the panel's "Export" and
"Compare" show exactly what the tree shows. Read-only.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .diagnostics import _server_info
from .nodes import build_nodes

EXPORT_FORMAT = 1


def build_export(
    client: Any,
    version: str,
    overlay: Callable[[int], dict[str, Any]] | None = None,
    node_id: int | None = None,
) -> dict[str, Any]:
    """The export document; ``node_id`` limits it to one node (``None``: the whole fabric)."""
    raw = [n for n in client.get_nodes() if node_id is None or n.node_id == node_id]
    nodes = []
    for node in build_nodes(raw, overlay):
        attributes = [
            {
                "path": a["path"],
                "endpoint": ep["endpoint_id"],
                "cluster": cl["cluster_id"],
                "attribute": a["attribute_id"],
                "cluster_name": cl["name"],
                "name": a["name"],
                "value": a["value"],
                "display_value": a["display_value"],
            }
            for ep in node["endpoints"]
            for cl in ep["clusters"]
            for a in cl["attributes"]
        ]
        nodes.append(
            {
                "node_id": node["node_id"],
                "name": node["name"],
                "vendor": node["vendor"],
                "product": node["product"],
                "available": node["available"],
                "attributes": attributes,
            }
        )
    return {
        "format": EXPORT_FORMAT,
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "integration_version": version,
        "server_info": _server_info(client),
        "scope": "fabric" if node_id is None else f"node {node_id}",
        "nodes": nodes,
    }
