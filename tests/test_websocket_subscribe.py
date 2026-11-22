"""matter_explorer/subscribe: forwarding, unsubscribe, admin only."""

from homeassistant.core import HomeAssistant
from matter_server.common.models import EventType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.matter_explorer.const import DOMAIN, STORE_KEY


async def _setup(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)


async def test_subscribe_forwards_and_unsubscribes(
    hass: HomeAssistant, matter_entry, fake_client, hass_ws_client: WebSocketGenerator
) -> None:
    await _setup(hass)
    client = await hass_ws_client(hass)
    sub_id = 1
    await client.send_json({"id": sub_id, "type": "matter_explorer/subscribe"})
    assert (await client.receive_json())["success"]
    store = hass.data[STORE_KEY]
    assert len(store._listeners) == 1

    fake_client.set_attribute(6, "1/516/1", 0)
    msg = await client.receive_json()
    assert msg["id"] == sub_id and msg["type"] == "event"
    assert msg["event"] == {
        "event": "attribute_updated",
        "node_id": 6,
        "path": "1/516/1",
        "value": 0,
        "display_value": "Off",
    }

    node = fake_client.get_node(6)
    node.available = False
    fake_client.emit(EventType.NODE_UPDATED, node, node_id=6)
    msg = await client.receive_json()
    assert msg["event"] == {"event": "node_updated", "node_id": 6, "available": False}

    fake_client.emit(EventType.NODE_REMOVED, 6, node_id=6)
    assert (await client.receive_json())["event"]["event"] == "node_removed"

    # a path the node does not have is never subscribed, so it is not forwarded
    fake_client.set_attribute(6, "1/516/999999", 1)

    # unsupported events and bad paths are ignored
    fake_client.emit(EventType.SERVER_SHUTDOWN, None)

    await client.send_json({"id": 2, "type": "unsubscribe_events", "subscription": sub_id})
    assert (await client.receive_json())["success"]
    assert store._listeners == []


async def test_subscribe_cleans_up_on_disconnect(
    hass: HomeAssistant, matter_entry, fake_client, hass_ws_client: WebSocketGenerator
) -> None:
    await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "matter_explorer/subscribe"})
    assert (await client.receive_json())["success"]
    store = hass.data[STORE_KEY]
    assert len(store._listeners) == 1
    await client.close()
    await hass.async_block_till_done()
    assert store._listeners == []


async def test_subscribe_admin_only(
    hass: HomeAssistant,
    matter_entry,
    fake_client,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
) -> None:
    await _setup(hass)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id({"type": "matter_explorer/subscribe"})
    msg = await client.receive_json()
    assert not msg["success"] and msg["error"]["code"] == "unauthorized"
    assert hass.data[STORE_KEY]._listeners == []


async def test_panel_registered_and_served(hass: HomeAssistant, matter_entry, hass_client) -> None:
    await _setup(hass)
    panel = hass.data["frontend_panels"]["matter-explorer"]
    assert panel.require_admin is True
    assert panel.sidebar_title == "Matter Explorer"
    assert panel.sidebar_icon == "mdi:graph-outline"
    http = await hass_client()
    resp = await http.get("/matter_explorer_static/matter-explorer-panel.js")
    assert resp.status == 200
    assert "matter-explorer-panel" in await resp.text()


async def test_nodes_reflect_live_values_and_unload_removes_all_listeners(
    hass: HomeAssistant, matter_entry, fake_client, hass_ws_client: WebSocketGenerator
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert fake_client.listeners  # the store watches nodes and attributes
    fake_client.set_attribute(6, "1/516/1", 0)  # snapshot in node_data still says 1

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "matter_explorer/nodes"})
    msg = await client.receive_json()
    [node] = msg["result"]["nodes"]
    ep = next(e for e in node["endpoints"] if e["endpoint_id"] == 1)
    cl = next(c for c in ep["clusters"] if c["cluster_id"] == 516)
    assert next(a for a in cl["attributes"] if a["attribute_id"] == 1)["value"] == 0

    fake_client.emit(EventType.NODE_UPDATED, fake_client.get_node(6), node_id=6)
    assert hass.data[STORE_KEY].overlay(6) == {}  # fresh snapshot replaces the overlay

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert fake_client.listeners == []
