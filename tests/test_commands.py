"""The command gate and matter_explorer/identify."""

import pytest
from matter_server.common.errors import SDKStackError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.matter_explorer.commands import CommandRefused, async_command, async_identify
from custom_components.matter_explorer.const import DOMAIN


async def _setup(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)


async def _ws(hass, hass_ws_client, **kw):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "matter_explorer/identify", **kw})
    return await client.receive_json()


async def test_identify_sends_command(hass, matter_entry, fake_client) -> None:
    assert await async_identify(hass, 6, 1) == {"ok": True, "identify_time": 15}
    ((node_id, ep, cmd),) = fake_client.commands
    assert (node_id, ep, cmd.identifyTime, cmd.cluster_id, cmd.command_id) == (6, 1, 15, 3, 0)


@pytest.mark.parametrize(
    ("cluster", "command", "args", "code"),
    [
        (6, 2, {}, "command_not_allowed"),  # on/off toggle
        (3, 64, {"triggerEffect": 0}, "command_not_allowed"),
        (3, 1, {}, "command_not_allowed"),
        (3, 0, {"identifyTime": 15, "x": 1}, "invalid_value"),
        (3, 0, {}, "invalid_value"),
        (3, 0, {"identifyTime": 0}, "invalid_value"),
        (3, 0, {"identifyTime": 61}, "invalid_value"),
        (3, 0, {"identifyTime": "15"}, "invalid_value"),
        (3, 0, {"identifyTime": True}, "invalid_value"),
    ],
)
async def test_gate_refuses(hass, matter_entry, fake_client, cluster, command, args, code) -> None:
    with pytest.raises(CommandRefused) as err:
        await async_command(hass, 6, 1, cluster, command, args)
    assert err.value.code == code
    assert fake_client.commands == []


async def test_bounds_accepted(hass, matter_entry, fake_client) -> None:
    await async_identify(hass, 6, 1, 1)
    await async_identify(hass, 6, 1, 60)
    assert [c.identifyTime for _, _, c in fake_client.commands] == [1, 60]


async def test_refuses_unavailable_unknown_and_no_cluster(hass, matter_entry, fake_client) -> None:
    for node_id, ep, code in [(99, 1, "node_not_found"), (6, 77, "no_identify")]:
        with pytest.raises(CommandRefused) as err:
            await async_identify(hass, node_id, ep)
        assert err.value.code == code
    fake_client.get_node(6).available = False
    with pytest.raises(CommandRefused) as err:
        await async_identify(hass, 6, 1)
    assert err.value.code == "node_unavailable"
    assert fake_client.commands == []


async def test_client_failure(hass, matter_entry, fake_client) -> None:
    fake_client.command_error = SDKStackError("boom")
    with pytest.raises(CommandRefused) as err:
        await async_identify(hass, 6, 1)
    assert err.value.code == "command_failed"


async def test_ws_identify(hass, matter_entry, fake_client, hass_ws_client, caplog) -> None:
    await _setup(hass)
    caplog.set_level("INFO")
    msg = await _ws(hass, hass_ws_client, node_id=6, endpoint_id=1)
    assert msg["success"] and msg["result"]["identify_time"] == 15
    assert "Identify" in caplog.text
    msg = await _ws(hass, hass_ws_client, node_id=6, endpoint_id=1, identify_time=90)
    assert not msg["success"]
    msg = await _ws(hass, hass_ws_client, node_id=6, endpoint_id=9)
    assert msg["error"]["code"] == "no_identify"
    assert len(fake_client.commands) == 1


async def test_ws_identify_admin_only(
    hass, matter_entry, fake_client, hass_ws_client, hass_admin_user
) -> None:
    await _setup(hass)
    hass_admin_user.groups = []
    msg = await _ws(hass, hass_ws_client, node_id=6, endpoint_id=1)
    assert msg["error"]["code"] == "unauthorized"
    assert fake_client.commands == []
