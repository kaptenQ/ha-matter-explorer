"""matter_explorer/export: same data as the nodes command, one node or the fabric, admin only."""

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from tests.conftest import load_node

from .test_websocket_nodes import _setup


async def _call(client, **extra):
    await client.send_json_auto_id({"type": "matter_explorer/export", **extra})
    return await client.receive_json()


async def test_export_fabric_and_node(
    hass: HomeAssistant, matter_entry, fake_client, hass_ws_client: WebSocketGenerator
) -> None:
    lab = load_node("lab-node.json")
    lab.node_id = 9
    fake_client._nodes.append(lab)
    await _setup(hass)
    client = await hass_ws_client(hass)

    msg = await _call(client)
    assert msg["success"], msg
    doc = msg["result"]
    assert doc["scope"] == "fabric" and doc["integration_version"]
    assert doc["exported_at"].endswith("+00:00") and "server_info" in doc
    assert len(doc["nodes"]) == 2

    node = next(n for n in doc["nodes"] if n["node_id"] == 6)
    assert node["name"] == "Living room thermostat" and node["available"] is True
    by_path = {a["path"]: a for a in node["attributes"]}
    lock = by_path["1/516/1"]
    assert (lock["value"], lock["display_value"], lock["name"]) == (1, "Level 1", "KeypadLockout")
    assert (lock["endpoint"], lock["cluster"], lock["attribute"]) == (1, 516, 1)
    assert isinstance(by_path["1/513/72"]["value"], list)

    # the same attributes as the nodes command
    await client.send_json_auto_id({"type": "matter_explorer/nodes"})
    tree = (await client.receive_json())["result"]["nodes"]
    expected = {
        a["path"]
        for n in tree
        if n["node_id"] == 6
        for e in n["endpoints"]
        for c in e["clusters"]
        for a in c["attributes"]
    }
    assert set(by_path) == expected

    one = (await _call(client, node_id=6))["result"]
    assert one["scope"] == "node 6" and [n["node_id"] for n in one["nodes"]] == [6]


async def test_export_unknown_node_and_non_admin(
    hass: HomeAssistant,
    matter_entry,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user,
    hass_read_only_access_token,
) -> None:
    await _setup(hass)
    client = await hass_ws_client(hass)
    msg = await _call(client, node_id=999)
    assert not msg["success"] and msg["error"]["code"] == "node_not_found"

    user = await hass_ws_client(hass, hass_read_only_access_token)
    msg = await _call(user)
    assert not msg["success"] and msg["error"]["code"] == "unauthorized"
