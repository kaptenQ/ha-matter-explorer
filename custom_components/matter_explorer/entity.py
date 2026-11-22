"""Base entity for ticked attributes. State comes from ATTRIBUTE_UPDATED events, no polling."""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components.matter.const import DOMAIN as MATTER_DOMAIN
from homeassistant.components.matter.const import ID_TYPE_DEVICE_ID
from homeassistant.components.matter.helpers import get_device_id, get_node_device_identifier
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from matter_server.common.models import EventType

from .client import MatterClientUnavailable, find_node, get_matter_client
from .const import SIGNAL_MATTER_STATE, STORE_KEY
from .errors import log_limited
from .exposure import ExposeSpec, build_spec, get_exposed, make_unique_id
from .metadata import parse_path
from .writable import WriteRefused, async_write

_LOGGER = logging.getLogger(__name__)

NAME_SUFFIX = " (Explorer)"


def _device_identifier(client: Any, node: Any, path: str) -> tuple[str, str]:
    """Matter device identifier of this attribute, via the matter integration's helpers."""
    endpoint_id = parse_path(path)[0]
    endpoint = getattr(node, "endpoints", {}).get(endpoint_id)
    if endpoint is not None:
        return (MATTER_DOMAIN, f"{ID_TYPE_DEVICE_ID}_{get_device_id(client.server_info, endpoint)}")
    return get_node_device_identifier(client.server_info, node.node_id)


class ExplorerEntity(Entity):
    """One ticked attribute."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        client: Any,
        node_id: int,
        path: str,
        spec: ExposeSpec,
        device: dr.DeviceEntry | None,
    ) -> None:
        self._client = client
        self._node_id = node_id
        self._path = path
        self._spec = spec
        # Differs from the matter integration's own name, so new entity ids get no _2 suffix.
        # Existing registry entries keep their entity_id (generated on first registration only).
        self._attr_name = f"{spec.name}{NAME_SUFFIX}"
        self._attr_unique_id = make_unique_id(client, node_id, path)
        # Attach to the Matter integration's own device (as helper integrations do): setting
        # device_entry links the entity without making this entry own or create a device.
        self.device_entry = device
        self._raw: Any = None
        self._load_raw()

    # -- state ----------------------------------------------------------------------------

    def _node(self) -> Any | None:
        return find_node(self._client, self._node_id)

    def _load_raw(self) -> None:
        node = self._node()
        if node is not None:
            self._raw = node.node_data.attributes.get(self._path)
        store = self.hass.data.get(STORE_KEY) if self.hass else None
        if store is not None:
            self._raw = store.overlay(self._node_id).get(self._path, self._raw)

    @property
    def available(self) -> bool:
        try:  # raises when matter is unloaded, reloading or disconnected from the server
            if get_matter_client(self.hass) is not self._client:
                return False
        except MatterClientUnavailable:
            return False
        node = self._node()
        return bool(node is not None and node.available)

    async def async_added_to_hass(self) -> None:
        self._load_raw()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_MATTER_STATE, self.async_write_ha_state)
        )
        self.async_on_remove(
            self._client.subscribe_events(
                self._on_attribute,
                EventType.ATTRIBUTE_UPDATED,
                node_filter=self._node_id,
                attr_path_filter=self._path,
            )
        )
        for event in (EventType.NODE_UPDATED, EventType.NODE_REMOVED):
            self.async_on_remove(
                self._client.subscribe_events(self._on_node, event, node_filter=self._node_id)
            )

    @callback
    def _on_attribute(self, event: EventType, value: Any) -> None:
        self._raw = value
        self.async_write_ha_state()

    @callback
    def _on_node(self, event: EventType, data: Any) -> None:
        if event == EventType.NODE_UPDATED:
            self._load_raw_from(data)
        self.async_write_ha_state()

    def _load_raw_from(self, node: Any) -> None:
        with contextlib.suppress(AttributeError):
            self._raw = node.node_data.attributes.get(self._path, self._raw)

    @property
    def native(self) -> Any:
        """The raw value scaled to the entity's native unit."""
        if self._raw is None:
            return None
        if (
            self._spec.scale != 1
            and isinstance(self._raw, int | float)
            and not isinstance(self._raw, bool)
        ):
            return self._raw / self._spec.scale
        return self._raw

    # -- writes (only through the write gate) ----------------------------------------------

    async def _write(self, raw: Any) -> None:
        try:
            result = await async_write(self.hass, self._node_id, self._path, raw)
        except WriteRefused as err:
            raise HomeAssistantError(str(err)) from err
        if result["timeout"] is False:
            self._raw = result["read_back"]
        if not result["matches"]:
            _LOGGER.warning(
                "Node %s %s: wrote %r, read back %r", self._node_id, self._path, raw,
                result["read_back"],
            )  # fmt: skip
        self.async_write_ha_state()


def display_state(value: Any) -> str | int | float | None:
    """A sensor state: scalars as they are, lists/structs as short JSON."""
    if value is None or isinstance(value, str | int | float):
        return value
    if isinstance(value, bytes | bytearray):
        return bytes(value).hex()[:255]
    try:
        return json.dumps(value, default=str)[:255]
    except TypeError, ValueError:
        return str(value)[:255]


async def async_setup_platform(
    hass: HomeAssistant,
    entry: ConfigEntry,
    platform: Platform,
    async_add_entities: AddEntitiesCallback,
    factory: Callable[..., ExplorerEntity],
) -> None:
    """Create the entities of the ticked list that belong to ``platform``."""
    try:
        client = get_matter_client(hass)
    except MatterClientUnavailable as err:
        _LOGGER.warning("Not creating entities: %s", err)
        return
    registry = dr.async_get(hass)
    matter_entry_id = hass.config_entries.async_loaded_entries(MATTER_DOMAIN)[0].entry_id
    entities = []
    for item in get_exposed(entry):
        node_id, path = item["node_id"], item["path"]
        node = find_node(client, node_id)
        spec = None if node is None else build_spec(dict(node.node_data.attributes), path)
        if spec is None:
            if platform == Platform.SENSOR:  # warn once, not once per platform
                log_limited(
                    _LOGGER, ("missing", node_id, path),
                    "Exposed attribute %s of node %s no longer exists; no entity created",
                    path, node_id,
                )  # fmt: skip
            continue
        if spec.platform != platform:
            continue
        identifier = _device_identifier(client, node, path)
        device = registry.async_get_device_by_identifier(identifier, matter_entry_id)
        if device is None:
            log_limited(
                _LOGGER, ("nodevice", node_id, path),
                "No Matter device in the registry for node %s; %s gets no device", node_id, path,
            )  # fmt: skip
        entities.append(factory(hass, client, node_id, path, spec, device))
    async_add_entities(entities)
