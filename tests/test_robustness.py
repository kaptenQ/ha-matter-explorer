"""Error handling: matter entry states, server loss, device timeouts, bad options, input fuzz,
log rate limit and diagnostics."""

import asyncio
import logging
from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from matter_server.client.exceptions import ConnectionClosed, NotConnected
from matter_server.common.errors import NodeNotExists, SDKStackError
from matter_server.common.models import EventType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.matter_explorer import commands as commands_mod
from custom_components.matter_explorer import errors, writable
from custom_components.matter_explorer.client import MatterClientUnavailable, get_matter_client
from custom_components.matter_explorer.const import (
    CONF_EXPOSED,
    DOMAIN,
    ISSUE_MATTER_NOT_LOADED,
    STORE_KEY,
)
from custom_components.matter_explorer.diagnostics import async_get_config_entry_diagnostics
from custom_components.matter_explorer.exposure import get_exposed, missing_exposed
from custom_components.matter_explorer.writable import WriteRefused, async_write


async def _setup(hass: HomeAssistant, options=None) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options or {})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _issue(hass):
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_MATTER_NOT_LOADED)


async def _ws(hass, hass_ws_client, payload):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(payload)
    return await client.receive_json()


# -- 1. the matter entry ---------------------------------------------------------------------


async def test_matter_missing_at_setup_is_not_ready_with_issue(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    hass.config.components.add("matter")
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert _issue(hass) is not None


async def test_issue_cleared_when_matter_comes_back(
    hass: HomeAssistant, matter_entry, fake_client
) -> None:
    entry = await _setup(hass)
    assert _issue(hass) is None
    matter_entry.mock_state(hass, ConfigEntryState.SETUP_RETRY)  # setup-retry
    assert _issue(hass) is not None
    assert entry.state is ConfigEntryState.LOADED  # no crash
    matter_entry.mock_state(hass, ConfigEntryState.LOADED)  # same client is back
    assert _issue(hass) is None


async def test_matter_unloaded_websocket_error_and_entities_unavailable(
    hass: HomeAssistant, matter_entry, fake_client, hass_ws_client: WebSocketGenerator
) -> None:
    await _setup(hass, {CONF_EXPOSED: [{"node_id": 6, "path": "1/516/1"}]})
    states = hass.states.async_all()
    assert states and all(s.state != "unavailable" for s in states)
    matter_entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
    await hass.async_block_till_done()
    assert all(s.state == "unavailable" for s in hass.states.async_all())
    msg = await _ws(hass, hass_ws_client, {"type": "matter_explorer/nodes"})
    assert msg["error"]["code"] == "matter_unavailable"
    matter_entry.mock_state(hass, ConfigEntryState.LOADED)
    await hass.async_block_till_done()
    assert all(s.state != "unavailable" for s in hass.states.async_all())


async def test_new_client_reloads_entry_and_clears_issue(
    hass: HomeAssistant, matter_entry, fake_client
) -> None:
    entry = await _setup(hass)
    matter_entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
    assert _issue(hass) is not None
    new = type(fake_client)([])
    matter_entry.runtime_data = SimpleNamespace(adapter=SimpleNamespace(matter_client=new))
    matter_entry.mock_state(hass, ConfigEntryState.LOADED)
    await hass.async_block_till_done()
    assert _issue(hass) is None
    assert entry.state is ConfigEntryState.LOADED
    assert hass.data[STORE_KEY]._client is new


# -- 2. Matter Server disconnected ------------------------------------------------------------


async def test_server_disconnected(
    hass: HomeAssistant, matter_entry, fake_client, hass_ws_client: WebSocketGenerator
) -> None:
    await _setup(hass, {CONF_EXPOSED: [{"node_id": 6, "path": "1/516/1"}]})
    fake_client.connection = SimpleNamespace(connected=False)
    with pytest.raises(MatterClientUnavailable, match="Not connected"):
        get_matter_client(hass)
    client = await hass_ws_client(hass)
    for payload in (
        {"type": "matter_explorer/nodes"},
        {"type": "matter_explorer/subscribe"},
        {"type": "matter_explorer/write", "node_id": 6, "path": "1/516/1", "value": 1},
        {"type": "matter_explorer/identify", "node_id": 6, "endpoint_id": 1},
        {"type": "matter_explorer/set_exposed", "node_id": 6, "path": "1/516/1", "exposed": False},
    ):
        await client.send_json_auto_id(payload)
        msg = await client.receive_json()
        assert msg["error"]["code"] == "matter_unavailable", payload
        assert "Matter Server" in msg["error"]["message"]
    # back again, no restart
    fake_client.connection = SimpleNamespace(connected=True)
    await client.send_json_auto_id({"type": "matter_explorer/nodes"})
    assert (await client.receive_json())["success"]


async def test_client_error_in_get_nodes_is_a_reply_not_a_traceback(
    hass: HomeAssistant, matter_entry, fake_client, hass_ws_client, caplog
) -> None:
    await _setup(hass)

    def boom():
        raise ConnectionClosed("gone")

    fake_client.get_nodes = boom
    msg = await _ws(hass, hass_ws_client, {"type": "matter_explorer/nodes"})
    assert msg["error"]["code"] == "matter_error" and "gone" in msg["error"]["message"]

    def bug():
        raise ValueError("bug")

    fake_client.get_nodes = bug
    msg = await _ws(hass, hass_ws_client, {"type": "matter_explorer/nodes"})
    assert msg["error"]["code"] == "unknown_error"
    assert "Traceback" not in msg["error"]["message"]
    assert "Unexpected error in matter_explorer/nodes" in caplog.text


async def test_write_client_errors(hass: HomeAssistant, matter_entry, fake_client) -> None:
    await _setup(hass)
    for err in (NotConnected(), SDKStackError("sdk"), ConnectionClosed("x")):

        async def fail(*_a, _e=err, **_k):
            raise _e

        fake_client.write_attribute = fail
        with pytest.raises(WriteRefused) as caught:
            await async_write(hass, 6, "1/516/1", 2)
        assert caught.value.code == "write_failed"
    assert [r["code"] for r in hass.data[errors.ACTIVITY_KEY]] == ["write_failed"] * 3


async def test_node_gone_is_node_not_found(hass: HomeAssistant, matter_entry, fake_client) -> None:
    await _setup(hass)
    with pytest.raises(WriteRefused) as caught:
        await async_write(hass, 99, "1/516/1", 2)
    assert caught.value.code == "node_not_found"
    with pytest.raises(NodeNotExists):
        fake_client.get_node(99)


# -- 3. slow or sleeping devices --------------------------------------------------------------


async def test_write_timeout_message_and_late_update(
    hass: HomeAssistant, matter_entry, fake_client, monkeypatch
) -> None:
    await _setup(hass)
    monkeypatch.setattr(writable, "DEVICE_TIMEOUT", 0.05)

    async def slow(*_a, **_k):
        await asyncio.sleep(3600)

    fake_client.write_attribute = slow
    with pytest.raises(WriteRefused) as caught:
        await async_write(hass, 6, "1/516/1", 2)
    assert caught.value.code == "timeout"
    assert "didn't answer within" in str(caught.value) and "Node 6" in str(caught.value)
    # the late ATTRIBUTE_UPDATED still lands in the live overlay
    fake_client.set_attribute(6, "1/516/1", 2)
    assert hass.data[STORE_KEY].overlay(6)["1/516/1"] == 2
    assert hass.data[errors.ACTIVITY_KEY][-1]["code"] == "timeout"


async def test_command_timeout(hass: HomeAssistant, matter_entry, fake_client, monkeypatch) -> None:
    await _setup(hass)
    monkeypatch.setattr(commands_mod, "DEVICE_TIMEOUT", 0.05)

    async def slow(*_a, **_k):
        await asyncio.sleep(3600)

    fake_client.send_device_command = slow
    with pytest.raises(commands_mod.CommandRefused) as caught:
        await commands_mod.async_identify(hass, 6, 1)
    assert caught.value.code == "timeout"
    assert "didn't answer within" in str(caught.value)


async def test_ws_write_timeout_code(
    hass: HomeAssistant, matter_entry, fake_client, hass_ws_client, monkeypatch
) -> None:
    await _setup(hass)
    monkeypatch.setattr(writable, "DEVICE_TIMEOUT", 0.05)

    async def slow(*_a, **_k):
        await asyncio.sleep(3600)

    fake_client.write_attribute = slow
    msg = await _ws(
        hass,
        hass_ws_client,
        {"type": "matter_explorer/write", "node_id": 6, "path": "1/516/1", "value": 2},
    )
    assert msg["error"]["code"] == "timeout"


async def test_bulk_timeout_row_and_lost_connection(
    hass: HomeAssistant, matter_entry, fake_client, monkeypatch
) -> None:
    await _setup(hass)
    monkeypatch.setattr(writable, "DEVICE_TIMEOUT", 0.05)

    async def _nosleep(_d):
        return

    monkeypatch.setattr(writable, "_pause", lambda: _nosleep(0))

    async def slow(*_a, **_k):
        await asyncio.sleep(3600)

    fake_client.write_attribute = slow
    results = await writable.async_write_many(hass, [{"node_id": 6, "path": "1/516/1"}], 2)
    assert results[0]["status"] == "timeout" and "didn't answer" in results[0]["error"]


# -- 5. bad stored options ---------------------------------------------------------------------


async def test_bad_options_one_warning_each_and_missing_list(
    hass: HomeAssistant, matter_entry, fake_client, hass_ws_client, caplog
) -> None:
    options = {
        CONF_EXPOSED: [
            {"node_id": 6, "path": "1/516/1"},
            {"node_id": 99, "path": "1/516/1"},  # node gone
            {"node_id": 6, "path": "1/516/9999"},  # attribute gone
            {"node_id": "six", "path": "1/516/1"},  # malformed
            {"node_id": 6, "path": "nonsense"},  # malformed
            "junk",
            {"node_id": True, "path": "1/1/1"},
        ]
    }
    caplog.set_level(logging.WARNING)
    entry = await _setup(hass, options)
    assert entry.state is ConfigEntryState.LOADED
    assert len(get_exposed(entry)) == 3
    msg = await _ws(hass, hass_ws_client, {"type": "matter_explorer/nodes"})
    missing = msg["result"]["missing_exposed"]
    assert {(m["node_id"], m["path"], m["reason"]) for m in missing} == {
        (99, "1/516/1", "node not found"),
        (6, "1/516/9999", "attribute not found"),
    }
    # asking again does not repeat the warnings
    for _ in range(3):
        await _ws(hass, hass_ws_client, {"type": "matter_explorer/nodes"})
        get_exposed(entry)
    for needle in ("'six'", "'nonsense'", "'junk'", "node_id': True"):
        assert sum(needle in r.getMessage() for r in caplog.records) == 1, needle
    assert (
        sum("Exposed attribute 1/516/9999 of node 6" in r.getMessage() for r in caplog.records) == 1
    )
    # a missing item can be unticked
    msg = await _ws(
        hass,
        hass_ws_client,
        {"type": "matter_explorer/set_exposed", "node_id": 99, "path": "1/516/1", "exposed": False},
    )
    assert msg["success"]
    assert missing_exposed(fake_client, entry)[0]["node_id"] == 6


async def test_malformed_list_option(hass: HomeAssistant, matter_entry, fake_client) -> None:
    entry = await _setup(hass, {CONF_EXPOSED: "oops"})
    assert entry.state is ConfigEntryState.LOADED
    assert get_exposed(entry) == []


# -- 6. input validation -----------------------------------------------------------------------

BAD = [
    {"type": "matter_explorer/write", "node_id": "6", "path": "1/516/1", "value": 1},
    {"type": "matter_explorer/write", "node_id": True, "path": "1/516/1", "value": 1},
    {"type": "matter_explorer/write", "node_id": -1, "path": "1/516/1", "value": 1},
    {"type": "matter_explorer/write", "node_id": 6, "path": "1/516", "value": 1},
    {"type": "matter_explorer/write", "node_id": 6, "path": "a/b/c", "value": 1},
    {"type": "matter_explorer/write", "node_id": 6, "path": "1/516/1" * 50, "value": 1},
    {"type": "matter_explorer/write", "node_id": 6, "path": 5, "value": 1},
    {"type": "matter_explorer/write", "node_id": 6, "path": "1/516/1", "value": [1]},
    {"type": "matter_explorer/write", "node_id": 6, "path": "1/516/1", "value": None},
    {"type": "matter_explorer/write", "node_id": 6, "path": "1/516/1", "value": 10**30},
    {"type": "matter_explorer/write", "node_id": 6, "path": "1/516/1", "value": "x" * 1000},
    {"type": "matter_explorer/write", "node_id": 6, "path": "1/516/1"},
    {"type": "matter_explorer/write_many", "items": [], "value": 1},
    {"type": "matter_explorer/write_many", "items": "x", "value": 1},
    {"type": "matter_explorer/write_many", "items": [{"node_id": 6}], "value": 1},
    {"type": "matter_explorer/write_many", "items": [{"node_id": 6, "path": "../x"}], "value": 1},
    {"type": "matter_explorer/set_exposed", "node_id": 6, "path": "1/516/1", "exposed": "yes"},
    {"type": "matter_explorer/set_exposed", "node_id": 1.5, "path": "1/516/1", "exposed": True},
    {"type": "matter_explorer/set_exposed", "node_id": 6, "path": "x" * 100, "exposed": True},
    {"type": "matter_explorer/identify", "node_id": 6, "endpoint_id": -1},
    {"type": "matter_explorer/identify", "node_id": 6, "endpoint_id": 100000},
    {"type": "matter_explorer/identify", "node_id": 6, "endpoint_id": 1, "identify_time": 0},
    {"type": "matter_explorer/identify", "node_id": 6, "endpoint_id": 1, "identify_time": True},
    {"type": "matter_explorer/identify", "node_id": 6, "endpoint_id": 1, "identify_time": "5"},
    {"type": "matter_explorer/identify", "node_id": None, "endpoint_id": 1},
]


@pytest.mark.parametrize("payload", BAD)
async def test_bad_input_is_an_error_not_a_traceback(
    hass: HomeAssistant, matter_entry, fake_client, hass_ws_client, payload, caplog
) -> None:
    await _setup(hass)
    msg = await _ws(hass, hass_ws_client, payload)
    assert msg["success"] is False
    assert msg["error"]["code"] in ("invalid_format", "invalid_path")
    assert "Traceback" not in caplog.text
    assert fake_client.writes == [] and fake_client.commands == []


async def test_unticking_a_bad_path_works(hass: HomeAssistant, matter_entry, fake_client) -> None:
    from custom_components.matter_explorer.exposure import ExposeError, async_set_exposed

    entry = await _setup(hass)
    with pytest.raises(ExposeError) as caught:
        await async_set_exposed(hass, entry, fake_client, 6, "bad", True)
    assert caught.value.code == "invalid_path"
    assert (await async_set_exposed(hass, entry, fake_client, 6, "bad", False))["exposed"] is False


# -- 7. logging --------------------------------------------------------------------------------


def test_log_limited(caplog) -> None:
    log = logging.getLogger("custom_components.matter_explorer.test")
    caplog.set_level(logging.DEBUG)
    assert errors.log_limited(log, ("k", 1), "first %s", 1) is True
    assert errors.log_limited(log, ("k", 1), "first %s", 1) is False
    assert errors.log_limited(log, ("k", 2), "other %s", 2) is True
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert any(r.getMessage().startswith("(repeated)") for r in caplog.records)


async def test_listener_exception_is_logged_and_does_not_stop_others(
    hass: HomeAssistant, matter_entry, fake_client, caplog
) -> None:
    await _setup(hass)
    store = hass.data[STORE_KEY]
    seen = []

    def bad(_p):
        raise RuntimeError("listener broke")

    store.add_listener(bad)
    store.add_listener(seen.append)
    fake_client.set_attribute(6, "1/516/1", 0)
    assert len(seen) == 1
    assert "A panel listener failed" in caplog.text


async def test_endpoint_event_for_vanished_node(
    hass: HomeAssistant, matter_entry, fake_client
) -> None:
    await _setup(hass)
    fake_client.emit(EventType.ENDPOINT_ADDED, {"node_id": 99})  # NodeNotExists is swallowed


# -- 8. diagnostics ----------------------------------------------------------------------------


async def test_diagnostics(hass: HomeAssistant, matter_entry, fake_client) -> None:
    entry = await _setup(hass, {CONF_EXPOSED: [{"node_id": 6, "path": "1/516/1"}]})
    await async_write(hass, 6, "1/516/1", 2)
    data = await async_get_config_entry_diagnostics(hass, entry)
    assert data["options"][CONF_EXPOSED] == [{"node_id": 6, "path": "1/516/1"}]
    assert data["counts"]["nodes"] == 1 and data["counts"]["exposed"] == 1
    assert data["client"]["available"] and data["client"]["server_info"]["fabric_id"] == 1
    assert data["recent_results"][-1]["kind"] == "write" and data["recent_results"][-1]["ok"]
    assert data["device_timeout_s"] == errors.DEVICE_TIMEOUT
    assert "attributes" not in str(data)  # no attribute dumps
    matter_entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
    data = await async_get_config_entry_diagnostics(hass, entry)
    assert data["client"]["available"] is False and data["issue_open"] is True


async def test_activity_log_is_capped(hass: HomeAssistant) -> None:
    for i in range(errors.ACTIVITY_MAX + 5):
        errors.record_activity(hass, "write", n=i)
    log = hass.data[errors.ACTIVITY_KEY]
    assert len(log) == errors.ACTIVITY_MAX and log[-1]["n"] == errors.ACTIVITY_MAX + 4
