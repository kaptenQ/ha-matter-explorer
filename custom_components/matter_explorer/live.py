"""Live attribute values from the shared MatterClient.

Two facts about ``MatterClient`` shape this module:

* ``subscribe_events`` calls back with ``(event_type, data)`` only. For ATTRIBUTE_UPDATED ``data``
  is the new raw value; node id and path are only used for filtering. So there is one
  ATTRIBUTE_UPDATED subscription per node and attribute path (node id and path by closure).
* The client does not write live updates back into ``node.node_data.attributes`` (that is
  the snapshot from connect / the last NODE_UPDATED). The store therefore keeps an overlay of the
  newest raw values, which ``build_nodes`` applies, so a (re)loaded panel is never stale.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from matter_server.common.errors import NodeNotExists
from matter_server.common.models import EventType

from .metadata import display_value, get_attribute_meta, parse_path

_LOGGER = logging.getLogger(__name__)

Listener = Callable[[dict[str, Any]], None]


class LiveStore:
    """Overlay of live attribute values plus fan-out of events to panel subscriptions."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self._overlay: dict[int, dict[str, Any]] = {}
        self._listeners: list[Listener] = []
        self._node_unsubs: dict[int, list[Callable[[], None]]] = {}
        self._unsubs: list[Callable[[], None]] = [
            client.subscribe_events(self._on_node_event, EventType.NODE_ADDED),
            client.subscribe_events(self._on_node_event, EventType.NODE_UPDATED),
            client.subscribe_events(self._on_node_event, EventType.NODE_REMOVED),
            client.subscribe_events(self._on_endpoint_event, EventType.ENDPOINT_ADDED),
            client.subscribe_events(self._on_endpoint_event, EventType.ENDPOINT_REMOVED),
        ]
        for node in client.get_nodes():
            self._watch(node)

    # -- public ---------------------------------------------------------------------------

    def overlay(self, node_id: int) -> dict[str, Any]:
        """Raw values that are newer than the node's snapshot."""
        return self._overlay.get(node_id, {})

    def add_listener(self, listener: Listener) -> Callable[[], None]:
        """Receive panel events; returns the function that removes the listener again."""
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def close(self) -> None:
        """Remove every subscription from the client."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for node_id in list(self._node_unsubs):
            self._unwatch(node_id)
        self._overlay.clear()
        self._listeners.clear()

    # -- internals ------------------------------------------------------------------------

    def _send(self, payload: dict[str, Any]) -> None:
        for listener in list(self._listeners):
            try:
                listener(payload)
            except (
                Exception
            ):  # outer edge of a callback: one broken panel connection must not stop the rest
                _LOGGER.exception("A panel listener failed on %s", payload.get("event"))

    def _watch(self, node: Any) -> None:
        node_id = node.node_id
        self._unwatch(node_id)
        unsubs = []
        for path in node.node_data.attributes:

            def on_attribute(
                event: EventType, value: Any, _n: int = node_id, _p: str = path
            ) -> None:
                self._on_attribute(_n, _p, value)

            unsubs.append(
                self._client.subscribe_events(
                    on_attribute,
                    EventType.ATTRIBUTE_UPDATED,
                    node_filter=node_id,
                    attr_path_filter=path,
                )
            )
        self._node_unsubs[node_id] = unsubs

    def _unwatch(self, node_id: int) -> None:
        for unsub in self._node_unsubs.pop(node_id, []):
            unsub()

    def _on_attribute(self, node_id: int, path: str, value: Any) -> None:
        self._overlay.setdefault(node_id, {})[path] = value
        try:
            _, cluster, attribute = parse_path(path)
        except ValueError:
            return
        self._send(
            {
                "event": "attribute_updated",
                "node_id": node_id,
                "path": path,
                "value": value,
                "display_value": display_value(get_attribute_meta(cluster, attribute), value),
            }
        )

    def _on_node_event(self, event: EventType, data: Any) -> None:
        if event == EventType.NODE_REMOVED:
            node_id = data if isinstance(data, int) else getattr(data, "node_id", None)
            if node_id is not None:
                self._unwatch(node_id)
                self._overlay.pop(node_id, None)
            self._send({"event": "node_removed", "node_id": node_id})
            return
        # NODE_ADDED / NODE_UPDATED carry a fresh snapshot: the overlay is obsolete
        self._overlay.pop(data.node_id, None)
        self._watch(data)
        if event == EventType.NODE_ADDED:
            self._send({"event": "node_added", "node_id": data.node_id})
        else:
            self._send(
                {
                    "event": "node_updated",
                    "node_id": data.node_id,
                    "available": bool(data.available),
                }
            )

    def _on_endpoint_event(self, event: EventType, data: Any) -> None:
        node_id = data.get("node_id") if isinstance(data, dict) else None
        if node_id is None:
            return
        try:
            self._watch(self._client.get_node(node_id))
        except NodeNotExists:  # node gone meanwhile
            return
        self._send({"event": "node_added", "node_id": node_id})  # panel reloads the tree
