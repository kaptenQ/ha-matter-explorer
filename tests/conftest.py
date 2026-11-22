"""Shared fixtures: a fake MatterClient and a fake loaded `matter` config entry."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let HA load custom_components/matter_explorer."""


@pytest.fixture(autouse=True)
def reset_log_limits():
    """Every test starts with an empty warning rate limiter."""
    from custom_components.matter_explorer.errors import reset_log_limits as reset

    reset()
    yield


def load_node(name: str) -> SimpleNamespace:
    """A fake MatterNode from a node dump (the shape of MatterNodeData)."""
    data = json.loads((FIXTURES / name).read_text())
    return SimpleNamespace(
        node_id=data["node_id"],
        available=data["available"],
        node_data=SimpleNamespace(
            attributes=data["attributes"], is_bridge=data.get("is_bridge", False)
        ),
    )


class FakeMatterClient:
    """Just what matter_explorer uses."""

    def __init__(self, nodes: list[Any]) -> None:
        self._nodes = nodes
        self.listeners: list[Any] = []
        self.writes: list[tuple[int, str, Any]] = []
        self.write_result: Any = None
        self.commands: list[tuple[int, int, Any]] = []
        self.command_error: Exception | None = None
        self.readback: Any = "echo"  # "echo": the written value; "timeout": hang; else the value
        self.has_read_attribute = True
        self.server_info = SimpleNamespace(compressed_fabric_id=0xABCDEF, fabric_id=1)

    def subscribe_events(
        self, callback, event_filter=None, node_filter=None, attr_path_filter=None
    ):
        entry = (callback, event_filter, node_filter, attr_path_filter)
        self.listeners.append(entry)

        def unsubscribe() -> None:
            self.listeners.remove(entry)

        return unsubscribe

    async def write_attribute(self, node_id: int, path: str, value: Any, **_: Any) -> Any:
        self.writes.append((node_id, path, value))
        return self.write_result

    async def send_device_command(
        self, node_id: int, endpoint_id: int, command: Any, **_: Any
    ) -> Any:
        if self.command_error:
            raise self.command_error
        self.commands.append((node_id, endpoint_id, command))

    def __getattr__(self, name: str) -> Any:
        if name == "read_attribute" and self.has_read_attribute:
            return self._read_attribute
        raise AttributeError(name)

    async def _read_attribute(self, node_id: int, path: str) -> dict[str, Any]:
        import asyncio

        if self.readback == "timeout":
            await asyncio.sleep(3600)
        value = self.writes[-1][2] if self.readback == "echo" else self.readback
        return {path: value}

    def get_nodes(self) -> list[Any]:
        return list(self._nodes)

    def get_node(self, node_id: int) -> Any:
        for n in self._nodes:
            if n.node_id == node_id:
                return n
        from matter_server.common.errors import NodeNotExists

        raise NodeNotExists(f"Node {node_id} does not exist")

    def emit(
        self, event: Any, data: Any, node_id: int | None = None, path: str | None = None
    ) -> None:
        """Signal like MatterClient: filter by event, node, path; callback gets (event, data)."""
        for callback, event_filter, node_filter, path_filter in list(self.listeners):
            if (
                event_filter in (None, event)
                and node_filter in (None, node_id)
                and path_filter in (None, path)
            ):
                callback(event, data)

    def set_attribute(self, node_id: int, path: str, value: Any) -> None:
        """Signal an attribute update. Like the real client, node_data is NOT updated."""
        from matter_server.common.models import EventType

        self.emit(EventType.ATTRIBUTE_UPDATED, value, node_id=node_id, path=path)


@pytest.fixture
def fake_client() -> FakeMatterClient:
    return FakeMatterClient([load_node("liljebagge-node6.json")])


@pytest.fixture
def matter_entry(hass: HomeAssistant, fake_client: FakeMatterClient):
    """A `matter` entry that looks loaded, carrying the fake client like HA's does."""
    entry = MockConfigEntry(domain="matter", data={"url": "ws://fake"})
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    hass.config.components.add("matter")  # dependency satisfied, don't load the real one
    entry.runtime_data = SimpleNamespace(adapter=SimpleNamespace(matter_client=fake_client))
    yield entry
    entry.mock_state(hass, ConfigEntryState.NOT_LOADED)  # nothing real to unload at teardown
