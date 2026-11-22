from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.matter_explorer.const import DOMAIN
from custom_components.matter_explorer.nodes import node_name


async def _setup(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)


def _attr(node: dict, path: str) -> dict:
    ep, cl, at = (int(x) for x in path.split("/"))
    endpoint = next(e for e in node["endpoints"] if e["endpoint_id"] == ep)
    cluster = next(c for c in endpoint["clusters"] if c["cluster_id"] == cl)
    return next(a for a in cluster["attributes"] if a["attribute_id"] == at)


async def test_nodes_tree(
    hass: HomeAssistant, matter_entry, hass_ws_client: WebSocketGenerator
) -> None:
    await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "matter_explorer/nodes"})
    msg = await client.receive_json()
    assert msg["success"], msg
    [node] = msg["result"]["nodes"]
    assert node["node_id"] == 6
    assert node["name"] == "Living room thermostat"
    assert node["available"] is True

    lock = _attr(node, "1/516/1")
    assert lock["value"] == 1
    assert lock["display_value"] == "Level 1"
    assert lock["meta"]["enum_labels"]["5"] == "Level 5"
    assert lock["type"] == "enum"
    assert lock["meta"]["enum_values"]["5"] == "Lockout5"

    temp = _attr(node, "1/513/0")
    assert temp["value"] == 1950 and temp["display_value"] == 19.5 and temp["unit"] == "°C"

    setpoint = _attr(node, "1/513/18")
    assert setpoint["value"] == 2100 and setpoint["display_value"] == 21.0
    assert (setpoint["meta"]["min"], setpoint["meta"]["max"]) == (500, 3500)

    assert isinstance(_attr(node, "1/513/72")["value"], list)  # presets, raw kept

    cluster = next(
        c for e in node["endpoints"] for c in e["clusters"] if c["cluster_id"] == 293403649
    )
    assert cluster["unknown"] is True
    assert cluster["name"] == "0x117CFC01"


async def test_nodes_unavailable_and_lab_node(
    hass: HomeAssistant, matter_entry, fake_client, hass_ws_client: WebSocketGenerator
) -> None:
    from tests.conftest import load_node

    lab = load_node("lab-node.json")
    lab.available = False
    fake_client._nodes.append(lab)
    await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "matter_explorer/nodes"})
    msg = await client.receive_json()
    assert msg["success"]
    nodes = msg["result"]["nodes"]
    assert [n["node_id"] for n in nodes] == sorted(n["node_id"] for n in nodes)
    assert nodes[-1]["available"] is False
    assert nodes[-1]["name"]
    assert nodes[-1]["endpoints"]


async def test_non_admin_denied(
    hass: HomeAssistant,
    matter_entry,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
) -> None:
    await _setup(hass)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id({"type": "matter_explorer/nodes"})
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "unauthorized"


async def test_matter_missing_gives_error(
    hass: HomeAssistant, matter_entry, hass_ws_client: WebSocketGenerator
) -> None:
    await _setup(hass)
    matter_entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "matter_explorer/nodes"})
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "matter_unavailable"


def test_node_name_fallbacks() -> None:
    assert node_name(3, {"0/40/5": "", "0/40/1": "IKEA", "0/40/3": "Thing"}) == "IKEA Thing"
    assert node_name(3, {}) == "Node 3"


def test_bridged_device_names() -> None:
    """Bridge endpoints carry the bridged device's name: NodeLabel, else ProductName."""
    from types import SimpleNamespace

    from custom_components.matter_explorer.nodes import build_node

    attrs = {
        "0/40/5": "Bridge",
        "1/57/5": " Kitchen lamp ",
        "1/57/3": "Lamp",
        "2/57/3": "Sensor X",
        "2/57/5": "",
        "3/6/0": True,
    }
    node = SimpleNamespace(
        node_id=9, available=True, node_data=SimpleNamespace(attributes=attrs, is_bridge=True)
    )
    names = {e["endpoint_id"]: e["name"] for e in build_node(node)["endpoints"]}
    assert names == {0: None, 1: "Kitchen lamp", 2: "Sensor X", 3: None}


def test_vendor_fields() -> None:
    """Node vendor name / id (0/40/1, 0/40/2) and the bridged device's own (cluster 57)."""
    from types import SimpleNamespace

    from custom_components.matter_explorer.nodes import build_node

    attrs = {
        "0/40/1": "Bridge Co",
        "0/40/2": 4476,
        "1/57/1": " Lamp Maker ",
        "1/57/2": 4999,
        "2/57/2": 4999,
        "2/57/1": "",
        "3/57/3": "Only a name",
        "4/6/0": True,
    }
    node = SimpleNamespace(
        node_id=9, available=True, node_data=SimpleNamespace(attributes=attrs, is_bridge=True)
    )
    built = build_node(node)
    assert built["vendor"] == "Bridge Co"
    assert built["vendor_id"] == 4476
    eps = {e["endpoint_id"]: e for e in built["endpoints"]}
    assert eps[1]["bridged_vendor"] == "Lamp Maker"
    assert eps[1]["bridged_vendor_id"] == 4999
    assert "bridged_vendor" not in eps[2]
    assert eps[2]["bridged_vendor_id"] == 4999
    assert "bridged_vendor" not in eps[3]
    assert "bridged_vendor_id" not in eps[4]
    bare = SimpleNamespace(
        node_id=1, available=True, node_data=SimpleNamespace(attributes={}, is_bridge=False)
    )
    assert build_node(bare)["vendor_id"] is None
