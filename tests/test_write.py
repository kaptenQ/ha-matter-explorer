"""Writability table, validation, the write gate and matter_explorer/write."""

import asyncio

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.matter_explorer import writable
from custom_components.matter_explorer.const import DOMAIN
from custom_components.matter_explorer.writable import (
    WRITABLE,
    WriteRefused,
    async_write,
    check_write,
    describe_write,
    writable_spec,
)


async def _setup(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)


async def _ws_write(hass, hass_ws_client, node_id, path, value):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "matter_explorer/write", "node_id": node_id, "path": path, "value": value}
    )
    return await client.receive_json()


def _refused(fake_client, path, value, node_id=6):
    with pytest.raises(WriteRefused) as err:
        check_write(fake_client.get_node(node_id), path, value)
    return err.value.code


# -- table -----------------------------------------------------------------------------------


def test_table_clusters_and_rows() -> None:
    assert {c for c, _ in WRITABLE} <= {3, 44, 45, 513, 516}
    for (cluster, attribute), spec in WRITABLE.items():
        assert writable_spec(cluster, attribute) is spec
        if spec.type == "enum":
            assert spec.values
        else:
            assert spec.min is not None or spec.limit_attrs


def test_table_matches_chip_enums() -> None:
    from chip.clusters import Objects as O  # noqa: N817

    pairs = {
        (516, 0): O.ThermostatUserInterfaceConfiguration.Enums.TemperatureDisplayModeEnum,
        (516, 1): O.ThermostatUserInterfaceConfiguration.Enums.KeypadLockoutEnum,
        (516, 2): O.ThermostatUserInterfaceConfiguration.Enums.ScheduleProgrammingVisibilityEnum,
        (513, 27): O.Thermostat.Enums.ControlSequenceOfOperationEnum,
        (513, 28): O.Thermostat.Enums.SystemModeEnum,
        (44, 0): O.TimeFormatLocalization.Enums.HourFormatEnum,
        (44, 1): O.TimeFormatLocalization.Enums.CalendarTypeEnum,
        (45, 0): O.UnitLocalization.Enums.TempUnitEnum,
    }
    for key, enum_cls in pairs.items():
        chip_values = {int(m.value) for m in enum_cls if m.name != "kUnknownEnumValue"}
        allowed = set(WRITABLE[key].values)
        if key == (513, 28):
            chip_values.discard(2)
        assert allowed == chip_values, key


def test_every_table_row_accepts_a_valid_value_and_refuses_bad_ones(fake_client) -> None:
    node = fake_client.get_node(6)
    node.node_data.attributes.update({"1/513/5": 1000, "1/513/6": 3200})  # abs cool limits
    for (cluster, attribute), spec in WRITABLE.items():
        path = f"1/{cluster}/{attribute}"
        node.node_data.attributes.setdefault(path, 0)
        lo, hi = writable.resolve_limits(spec, node.node_data.attributes, 1, cluster)
        if spec.type == "enum":
            good, bad = next(iter(spec.values)), max(spec.values) + 1
        else:
            good, bad = lo, hi + 1
        assert check_write(node, path, good) is spec
        for wrong in (bad, "1", 1.5, True, None):
            with pytest.raises(WriteRefused):
                check_write(node, path, wrong)


def test_enum_bounds_keypad_lockout(fake_client) -> None:
    node = fake_client.get_node(6)
    for ok in range(6):
        check_write(node, "1/516/1", ok)
    assert _refused(fake_client, "1/516/1", 6) == "invalid_value"
    assert _refused(fake_client, "1/516/1", -1) == "invalid_value"
    assert _refused(fake_client, "1/516/1", True) == "invalid_value"


def test_setpoint_limits_from_node(fake_client) -> None:
    node = fake_client.get_node(6)
    assert node.node_data.attributes["1/513/21"] == 500
    assert node.node_data.attributes["1/513/22"] == 3500
    check_write(node, "1/513/18", 500)
    check_write(node, "1/513/18", 3500)
    assert _refused(fake_client, "1/513/18", 499) == "invalid_value"
    assert _refused(fake_client, "1/513/18", 3501) == "invalid_value"
    assert _refused(fake_client, "1/513/18", 21.0) == "invalid_value"
    # node without Min/MaxHeatSetpointLimit: AbsMin/AbsMax
    attrs = node.node_data.attributes
    del attrs["1/513/21"], attrs["1/513/22"]
    attrs["1/513/3"], attrs["1/513/4"] = 700, 3000
    check_write(node, "1/513/18", 700)
    assert _refused(fake_client, "1/513/18", 600) == "invalid_value"
    # no limits at all: refused, and the panel gets no edit control
    del attrs["1/513/3"], attrs["1/513/4"]
    assert _refused(fake_client, "1/513/18", 2000) == "invalid_value"
    assert describe_write(attrs, 1, 513, 18) is None


def test_describe_write(fake_client) -> None:
    attrs = fake_client.get_node(6).node_data.attributes
    assert describe_write(attrs, 1, 513, 18) == {
        "type": "int",
        "min": 500,
        "max": 3500,
        "unit": "°C",
    }
    lock = describe_write(attrs, 1, 516, 1)
    assert lock["type"] == "enum" and lock["values"]["5"] == "Lockout5"
    for ro in ((513, 72), (513, 80), (513, 0), (293403649, 1), (516, 65533), (513, 65531)):
        assert describe_write(attrs, 1, *ro) is None


# -- gate ------------------------------------------------------------------------------------


async def test_gate_refuses_without_calling_client(hass, matter_entry, fake_client) -> None:
    await _setup(hass)
    node = fake_client.get_node(6)
    node.node_data.attributes["1/10000/1"] = 5
    cases = [
        ("1/293403649/1", 1),  # IKEA 0x117CFC01
        ("1/2085945345/1", 1),  # 0x7C40_0001-ish vendor prefix cluster
        ("1/513/72", []),  # presets list
        ("1/513/80", []),  # schedules list
        ("1/513/65532", 0),  # global
        ("1/513/65531", []),  # global
        ("1/513/0", 1000),  # not in the table
        ("1/40/5", "x"),  # basic information NodeLabel
        ("1/47/2", 1),  # power source: not in the table
        ("1/10000/1", 1),  # 0xFC00-range / unknown cluster
        ("1/516/99", 1),  # not existing
        ("garbage", 1),
    ]
    for path, value in cases:
        with pytest.raises(WriteRefused):
            await async_write(hass, 6, path, value)
    with pytest.raises(WriteRefused) as err:
        await async_write(hass, 99, "1/516/1", 1)
    assert err.value.code == "node_not_found"
    node.available = False
    with pytest.raises(WriteRefused) as err:
        await async_write(hass, 6, "1/516/1", 0)
    assert err.value.code == "node_unavailable"
    assert fake_client.writes == []


async def test_gate_match_and_logging(hass, matter_entry, fake_client, caplog) -> None:
    await _setup(hass)
    caplog.set_level("INFO")
    result = await async_write(hass, 6, "1/516/1", 3)
    assert result == {
        "ok": True,
        "written": 3,
        "read_back": 3,
        "matches": True,
        "timeout": False,
    }
    assert fake_client.writes == [(6, "1/516/1", 3)]
    assert "node=6 path=1/516/1 old=1 new=3" in caplog.text


async def test_gate_mismatch(hass, matter_entry, fake_client) -> None:
    await _setup(hass)
    fake_client.readback = 1
    result = await async_write(hass, 6, "1/516/1", 3)
    assert result["ok"] and result["matches"] is False and result["read_back"] == 1


async def test_gate_timeout(hass, matter_entry, fake_client, monkeypatch) -> None:
    await _setup(hass)
    monkeypatch.setattr(writable, "READBACK_TIMEOUT", 0.05)
    fake_client.readback = "timeout"
    result = await async_write(hass, 6, "1/516/1", 3)
    assert result["timeout"] is True and result["matches"] is False
    assert result["read_back"] is None
    assert len(fake_client.writes) == 1


async def test_gate_readback_from_event_without_read_attribute(
    hass, matter_entry, fake_client, monkeypatch
) -> None:
    await _setup(hass)
    fake_client.has_read_attribute = False
    task = hass.async_create_task(async_write(hass, 6, "1/516/1", 2))
    for _ in range(20):
        await asyncio.sleep(0)
    fake_client.set_attribute(6, "1/516/1", 2)
    result = await task
    assert result["matches"] is True

    monkeypatch.setattr(writable, "READBACK_TIMEOUT", 0.05)
    assert (await async_write(hass, 6, "1/516/1", 4))["timeout"] is True


async def test_gate_device_error(hass, matter_entry, fake_client) -> None:
    await _setup(hass)
    fake_client.write_result = [{"Path": "x", "Status": 135}]
    with pytest.raises(WriteRefused) as err:
        await async_write(hass, 6, "1/516/1", 3)
    assert err.value.code == "write_failed"


def test_write_attribute_only_called_in_gate() -> None:
    from pathlib import Path

    root = Path(writable.__file__).parent
    hits = [p.name for p in root.glob("*.py") if ".write_attribute(" in p.read_text()]
    assert hits == ["writable.py"]


# -- websocket -------------------------------------------------------------------------------


async def test_ws_write_ok_and_refused(
    hass, matter_entry, fake_client, hass_ws_client: WebSocketGenerator
) -> None:
    await _setup(hass)
    msg = await _ws_write(hass, hass_ws_client, 6, "1/516/1", 0)
    assert msg["success"] and msg["result"]["matches"] is True
    msg = await _ws_write(hass, hass_ws_client, 6, "1/516/1", 6)
    assert not msg["success"] and msg["error"]["code"] == "invalid_value"
    msg = await _ws_write(hass, hass_ws_client, 6, "1/293403649/1", 1)
    assert not msg["success"] and msg["error"]["code"] == "not_writable"
    assert fake_client.writes == [(6, "1/516/1", 0)]


async def test_ws_write_admin_only(
    hass, matter_entry, fake_client, hass_ws_client: WebSocketGenerator, hass_admin_user
) -> None:
    await _setup(hass)
    hass_admin_user.groups = []
    msg = await _ws_write(hass, hass_ws_client, 6, "1/516/1", 0)
    assert not msg["success"] and msg["error"]["code"] == "unauthorized"
    assert fake_client.writes == []
