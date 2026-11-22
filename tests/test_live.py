"""Live values: event order for a node added while HA runs, and a new client after a reload."""

from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from matter_server.common.models import EventType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.matter_explorer.const import DOMAIN, STORE_KEY
from custom_components.matter_explorer.live import LiveStore
from custom_components.matter_explorer.nodes import build_node

from .conftest import FakeMatterClient, load_node

PATH = "1/516/1"


def _value(node, overlay) -> object:
    for ep in build_node(node, overlay)["endpoints"]:
        for cl in ep["clusters"]:
            for at in cl["attributes"]:
                if at["path"] == PATH:
                    return at["value"]
    return "missing"


def test_node_added_attribute_then_node_updated_in_real_order() -> None:
    """Server order for a new node: NODE_ADDED, ATTRIBUTE_UPDATED, (NODE_UPDATED)."""
    client = FakeMatterClient([])
    store = LiveStore(client)
    node = load_node("liljebagge-node6.json")
    old = node.node_data.attributes[PATH]
    new = 2 if old != 2 else 3
    client._nodes.append(node)  # the client stores the node before it signals NODE_ADDED
    client.emit(EventType.NODE_ADDED, node, node_id=node.node_id)
    client.set_attribute(node.node_id, PATH, new)  # the client leaves node_data alone
    assert _value(node, store.overlay) == new
    # NODE_UPDATED carries a fresh snapshot (with the new value): still right, still watched
    node.node_data.attributes[PATH] = new
    client.emit(EventType.NODE_UPDATED, node, node_id=node.node_id)
    assert _value(node, store.overlay) == new
    client.set_attribute(node.node_id, PATH, old)
    assert _value(node, store.overlay) == old
    store.close()
    assert not client.listeners


async def test_reload_of_matter_entry_with_new_client_reloads_explorer(
    hass: HomeAssistant, matter_entry, fake_client
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    first = hass.data[STORE_KEY]
    assert first._client is fake_client

    # what HA's matter integration does after a lost connection: a new entry run with a new client
    new_client = FakeMatterClient([load_node("liljebagge-node6.json")])
    matter_entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
    matter_entry.runtime_data = SimpleNamespace(adapter=SimpleNamespace(matter_client=new_client))
    matter_entry.mock_state(hass, ConfigEntryState.LOADED)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    store = hass.data[STORE_KEY]
    assert store is not first and store._client is new_client
    assert not fake_client.listeners  # nothing left on the old client
    new_client.set_attribute(6, PATH, 2)
    assert store.overlay(6)[PATH] == 2


async def test_same_client_state_change_does_not_reload(
    hass: HomeAssistant, matter_entry, fake_client
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    first = hass.data[STORE_KEY]
    matter_entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
    matter_entry.mock_state(hass, ConfigEntryState.LOADED)
    await hass.async_block_till_done()
    assert hass.data[STORE_KEY] is first
