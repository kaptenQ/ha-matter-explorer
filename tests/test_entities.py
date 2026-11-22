"""Entity platforms, options storage and matter_explorer/set_exposed."""

import pytest
from homeassistant.components.matter.helpers import get_node_device_identifier
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.matter_explorer.const import CONF_EXPOSED, DOMAIN
from custom_components.matter_explorer.writable import BOOL, WRITABLE, WritableAttr

CHILD_LOCK = {"node_id": 6, "path": "1/516/1"}
FABRIC = f"{0xABCDEF:016X}"


def uid(path: str, node: int = 6) -> str:
    ep, cl, at = path.split("/")
    return f"matter_explorer_{FABRIC}_{node}_{ep}_{cl}_{at}"


@pytest.fixture
def matter_device(hass: HomeAssistant, matter_entry, fake_client):
    """The Matter device of node 6 as the matter integration registers it."""
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=matter_entry.entry_id,
        identifiers={get_node_device_identifier(fake_client.server_info, 6)},
        name="Living room thermostat",
    )


async def _setup(hass: HomeAssistant, items: list[dict] | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={CONF_EXPOSED: items or []})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _entity(hass: HomeAssistant, path: str):
    reg = er.async_get(hass)
    ent_id = next((e.entity_id for e in reg.entities.values() if e.unique_id == uid(path)), None)
    return reg.async_get(ent_id) if ent_id else None


async def _ws(hass, hass_ws_client, msg):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(msg)
    return await client.receive_json()


async def test_select_child_lock(hass, matter_entry, fake_client, matter_device) -> None:
    await _setup(hass, [CHILD_LOCK])
    reg = _entity(hass, "1/516/1")
    assert reg.domain == "select" and reg.device_id == matter_device.id
    assert reg.entity_id == "select.living_room_thermostat_child_lock_explorer"
    state = hass.states.get(reg.entity_id)
    assert state.state == "Level 1"
    assert state.attributes["options"] == [
        "Off",
        "Level 1",
        "Level 2",
        "Level 3",
        "Level 4",
        "Level 5",
    ]
    assert state.attributes["friendly_name"] == "Living room thermostat Child lock (Explorer)"

    # write goes through the gate with readback
    await hass.services.async_call(
        "select", "select_option", {"entity_id": reg.entity_id, "option": "Off"}, blocking=True
    )
    assert fake_client.writes == [(6, "1/516/1", 0)]
    assert hass.states.get(reg.entity_id).state == "Off"
    # state follows events, not polling
    fake_client.set_attribute(6, "1/516/1", 3)
    assert hass.states.get(reg.entity_id).state == "Level 3"


async def test_availability_follows_node(hass, matter_entry, fake_client, matter_device) -> None:
    from matter_server.common.models import EventType

    await _setup(hass, [CHILD_LOCK])
    ent = _entity(hass, "1/516/1").entity_id
    node = fake_client.get_node(6)
    node.available = False
    fake_client.emit(EventType.NODE_UPDATED, node, node_id=6)
    assert hass.states.get(ent).state == "unavailable"
    node.available = True
    fake_client.emit(EventType.NODE_UPDATED, node, node_id=6)
    assert hass.states.get(ent).state == "Level 1"


async def test_no_write_when_node_unavailable(
    hass, matter_entry, fake_client, matter_device
) -> None:
    await _setup(hass, [CHILD_LOCK])
    ent = _entity(hass, "1/516/1").entity_id
    fake_client.get_node(6).available = False
    # the entity is unavailable, so HA does not call it; the gate would refuse anyway
    await hass.services.async_call(
        "select", "select_option", {"entity_id": ent, "option": "Off"}, blocking=True
    )
    assert fake_client.writes == []
    entity = hass.data["select"].get_entity(ent)
    with pytest.raises(HomeAssistantError):
        await entity.async_select_option("Off")
    assert fake_client.writes == []


async def test_number_setpoint_in_celsius(hass, matter_entry, fake_client, matter_device) -> None:
    await _setup(hass, [{"node_id": 6, "path": "1/513/18"}])
    reg = _entity(hass, "1/513/18")
    assert reg.domain == "number"
    state = hass.states.get(reg.entity_id)
    assert float(state.state) == 21.0
    assert state.attributes["min"] == 5.0 and state.attributes["max"] == 35.0
    assert state.attributes["step"] == 0.5
    assert state.attributes["unit_of_measurement"] == "°C"
    await hass.services.async_call(
        "number", "set_value", {"entity_id": reg.entity_id, "value": 19.5}, blocking=True
    )
    assert fake_client.writes == [(6, "1/513/18", 1950)]
    assert float(hass.states.get(reg.entity_id).state) == 19.5


async def test_sensor_and_binary_sensor(hass, matter_entry, fake_client, matter_device) -> None:
    await _setup(
        hass,
        [
            {"node_id": 6, "path": "1/513/0"},
            {"node_id": 6, "path": "0/40/5"},
            {"node_id": 6, "path": "0/42/1"},
        ],
    )
    temp = hass.states.get(_entity(hass, "1/513/0").entity_id)
    assert float(temp.state) == 19.5
    assert temp.attributes["device_class"] == "temperature"
    assert temp.attributes["unit_of_measurement"] == "°C"
    assert _entity(hass, "0/40/5").domain == "sensor"
    assert hass.states.get(_entity(hass, "0/40/5").entity_id).state == "Living room thermostat"
    binary = _entity(hass, "0/42/1")
    assert binary.domain == "binary_sensor"
    assert hass.states.get(binary.entity_id).state == "on"
    fake_client.set_attribute(6, "0/42/1", False)
    assert hass.states.get(binary.entity_id).state == "off"
    fake_client.set_attribute(6, "1/513/0", 2025)
    assert float(hass.states.get(_entity(hass, "1/513/0").entity_id).state) == 20.25


async def test_switch(hass, matter_entry, fake_client, matter_device, monkeypatch) -> None:
    monkeypatch.setitem(WRITABLE, (42, 1), WritableAttr("Test", BOOL))
    await _setup(hass, [{"node_id": 6, "path": "0/42/1"}])
    reg = _entity(hass, "0/42/1")
    assert reg.domain == "switch"
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": reg.entity_id}, blocking=True
    )
    assert fake_client.writes == [(6, "0/42/1", False)]
    assert hass.states.get(reg.entity_id).state == "off"


async def test_no_matter_device_no_device_and_warning(
    hass, matter_entry, fake_client, caplog
) -> None:
    await _setup(hass, [CHILD_LOCK])
    reg = _entity(hass, "1/516/1")
    assert reg is not None and reg.device_id is None
    assert "No Matter device in the registry for node 6" in caplog.text
    assert not dr.async_get(hass).devices


async def test_missing_items_stay_in_options_one_warning(
    hass, matter_entry, fake_client, matter_device, caplog
) -> None:
    items = [{"node_id": 99, "path": "1/516/1"}, {"node_id": 6, "path": "1/516/77"}]
    entry = await _setup(hass, items)
    assert entry.options[CONF_EXPOSED] == items
    assert not er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert caplog.text.count("no longer exists") == 2  # one per item, not per platform


async def test_set_exposed_add_remove(
    hass, matter_entry, fake_client, matter_device, hass_ws_client: WebSocketGenerator
) -> None:
    entry = await _setup(hass)
    msg = {"type": "matter_explorer/set_exposed", **CHILD_LOCK, "exposed": True}
    res = await _ws(hass, hass_ws_client, msg)
    assert res["success"]
    assert res["result"]["entity_id"] == "select.living_room_thermostat_child_lock_explorer"
    assert entry.options[CONF_EXPOSED] == [CHILD_LOCK]
    assert hass.states.get("select.living_room_thermostat_child_lock_explorer")

    # idempotent
    assert (await _ws(hass, hass_ws_client, msg))["success"]
    assert entry.options[CONF_EXPOSED] == [CHILD_LOCK]

    # nodes shows it
    res = await _ws(hass, hass_ws_client, {"type": "matter_explorer/nodes"})
    attrs = {
        a["path"]: a
        for e in res["result"]["nodes"][0]["endpoints"]
        for c in e["clusters"]
        for a in c["attributes"]
    }
    assert attrs["1/516/1"]["entity"] == {
        "platform": "select",
        "exposed": True,
        "entity_id": "select.living_room_thermostat_child_lock_explorer",
    }
    assert attrs["1/516/0"]["entity"]["exposed"] is False

    # untick: gone from registry, not only the state
    res = await _ws(
        hass, hass_ws_client, {**msg, "type": "matter_explorer/set_exposed", "exposed": False}
    )
    assert res["success"]
    assert entry.options[CONF_EXPOSED] == []
    assert _entity(hass, "1/516/1") is None
    assert hass.states.get("select.living_room_thermostat_child_lock_explorer") is None


async def test_set_exposed_errors(
    hass, matter_entry, fake_client, matter_device, hass_ws_client: WebSocketGenerator
) -> None:
    await _setup(hass)
    base = {"type": "matter_explorer/set_exposed", "exposed": True}
    res = await _ws(hass, hass_ws_client, {**base, "node_id": 99, "path": "1/516/1"})
    assert res["error"]["code"] == "node_not_found"
    res = await _ws(hass, hass_ws_client, {**base, "node_id": 6, "path": "1/516/77"})
    assert res["error"]["code"] == "not_found"
    res = await _ws(hass, hass_ws_client, {**base, "node_id": 6, "path": "bogus"})
    assert res["error"]["code"] == "invalid_path"


async def test_set_exposed_admin_only(
    hass, matter_entry, fake_client, matter_device, hass_ws_client, hass_read_only_access_token
) -> None:
    entry = await _setup(hass)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id(
        {"type": "matter_explorer/set_exposed", **CHILD_LOCK, "exposed": True}
    )
    msg = await client.receive_json()
    assert msg["error"]["code"] == "unauthorized"
    assert entry.options.get(CONF_EXPOSED) == []


async def test_options_survive_reload(hass, matter_entry, fake_client, matter_device) -> None:
    entry = await _setup(hass, [CHILD_LOCK])
    ent = _entity(hass, "1/516/1").entity_id
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.options[CONF_EXPOSED] == [CHILD_LOCK]
    assert _entity(hass, "1/516/1").entity_id == ent
    assert hass.states.get(ent).state == "Level 1"
    # unload leaves no subscriptions of the entity behind
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert fake_client.listeners == []


async def test_stale_entity_removed_on_setup(
    hass, matter_entry, fake_client, matter_device
) -> None:
    entry = await _setup(hass, [CHILD_LOCK])
    assert _entity(hass, "1/516/1")
    await hass.config_entries.async_unload(entry.entry_id)
    hass.config_entries.async_update_entry(entry, options={CONF_EXPOSED: []})
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert _entity(hass, "1/516/1") is None


async def test_existing_entity_keeps_its_entity_id(
    hass, matter_entry, fake_client, matter_device
) -> None:
    """Entities registered before 0.10.0 keep their entity_id; only the name gets the suffix."""
    reg = er.async_get(hass)
    old = reg.async_get_or_create(
        "select",
        DOMAIN,
        uid("1/516/1"),
        suggested_object_id="living_room_thermostat_child_lock",
        original_name="Child lock",
        device_id=matter_device.id,
    )
    assert old.entity_id == "select.living_room_thermostat_child_lock"
    await _setup(hass, [CHILD_LOCK])
    now = _entity(hass, "1/516/1")
    assert now.entity_id == "select.living_room_thermostat_child_lock"
    assert now.original_name == "Child lock (Explorer)"
    assert hass.states.get(now.entity_id).attributes["friendly_name"].endswith("(Explorer)")


async def test_new_entity_does_not_collide_with_matter_name(
    hass, matter_entry, fake_client, matter_device
) -> None:
    er.async_get(hass).async_get_or_create(
        "select", "matter", "other", suggested_object_id="living_room_thermostat_child_lock"
    )
    await _setup(hass, [CHILD_LOCK])
    assert _entity(hass, "1/516/1").entity_id == "select.living_room_thermostat_child_lock_explorer"
