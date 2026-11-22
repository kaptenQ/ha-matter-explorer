"""matter_explorer/write_many: sequential bulk writes through the write gate."""

import copy

import pytest
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.matter_explorer import writable
from custom_components.matter_explorer.writable import async_write_many

from .test_write import _setup

PATH = "1/516/1"


def _clone(fake_client, node_id: int, value=1):
    node = copy.deepcopy(fake_client.get_node(6))
    node.node_id = node_id
    node.node_data.attributes[PATH] = value
    fake_client._nodes.append(node)
    return node


def _items(*ids):
    return [{"node_id": i, "path": PATH} for i in ids]


@pytest.fixture
def sleeps(monkeypatch):
    calls: list[float] = []

    async def fake_sleep(delay):
        calls.append(delay)

    monkeypatch.setattr(writable.asyncio, "sleep", fake_sleep)
    return calls


async def test_sequential_and_spaced(hass, matter_entry, fake_client, sleeps) -> None:
    await _setup(hass)
    for i in (7, 8):
        _clone(fake_client, i)
    seen = []
    results = await async_write_many(
        hass,
        _items(6, 7, 8),
        2,
        lambda done, total, item: seen.append((done, total, item["node_id"])),
    )
    assert [w[0] for w in fake_client.writes] == [6, 7, 8]
    assert all(w[2] == 2 for w in fake_client.writes)
    assert [r["status"] for r in results] == ["ok"] * 3
    assert results[0]["old"] == 1 and results[0]["read_back"] == 2 and results[0]["matches"]
    assert sleeps == [writable.WRITE_SPACING] * 2  # between writes, not before the first
    assert seen == [(1, 3, 6), (2, 3, 7), (3, 3, 8)]


async def test_partial_failure_does_not_stop(hass, matter_entry, fake_client, sleeps) -> None:
    await _setup(hass)
    for i in (7, 8, 9):
        _clone(fake_client, i)
    original = fake_client.write_attribute

    async def flaky(node_id, path, value, **kw):
        if node_id == 7:
            raise RuntimeError("boom")
        return await original(node_id, path, value, **kw)

    fake_client.write_attribute = flaky
    fake_client.readback = 1  # nobody reflects the write: mismatch
    results = await async_write_many(hass, _items(6, 7, 8), 2)
    assert [r["status"] for r in results] == ["mismatch", "error", "mismatch"]
    assert "boom" in results[1]["error"]
    assert [w[0] for w in fake_client.writes] == [6, 8]


async def test_timeout_status(hass, matter_entry, fake_client, sleeps, monkeypatch) -> None:
    await _setup(hass)
    monkeypatch.setattr(writable, "READBACK_TIMEOUT", 0.05)
    fake_client.readback = "timeout"
    # the patched asyncio.sleep returns at once, so no timeout can fire: drop the patch for it
    monkeypatch.undo()
    monkeypatch.setattr(writable, "READBACK_TIMEOUT", 0.05)
    results = await async_write_many(hass, _items(6), 2)
    assert results[0]["status"] == "timeout"


async def test_no_change_not_written(hass, matter_entry, fake_client, sleeps) -> None:
    await _setup(hass)
    _clone(fake_client, 7, value=2)
    results = await async_write_many(hass, _items(6, 7), 2)
    assert [r["status"] for r in results] == ["ok", "no_change"]
    assert fake_client.writes == [(6, PATH, 2)]
    assert sleeps == []


async def test_no_change_uses_live_value_not_stale_snapshot(
    hass, matter_entry, fake_client, sleeps
) -> None:
    """The client's snapshot goes stale: a value changed live decides, not node_data."""
    _clone(fake_client, 7, value=1)  # snapshot 1 ... (cloned before setup: the store watches it)
    await _setup(hass)
    fake_client.set_attribute(7, PATH, 2)  # ... but the device is at 2 now
    fake_client.set_attribute(6, PATH, 0)  # snapshot of node 6 is 1, live value is 0
    await hass.async_block_till_done()
    results = await async_write_many(hass, _items(6, 7), 0)
    assert [r["status"] for r in results] == ["no_change", "ok"]
    assert results[1]["old"] == 2
    assert fake_client.writes == [(7, PATH, 0)]


async def test_skipped_rows_never_reach_client(hass, matter_entry, fake_client, sleeps) -> None:
    await _setup(hass)
    off = _clone(fake_client, 7)
    off.available = False
    items = [
        {"node_id": 7, "path": PATH},  # unavailable
        {"node_id": 99, "path": PATH},  # unknown node
        {"node_id": 6, "path": "1/516/99"},  # not in the table
        {"node_id": 6, "path": "1/513/0"},  # not writable
        {"node_id": 6, "path": "nonsense"},
    ]
    results = await async_write_many(hass, items, 2)
    assert [r["status"] for r in results] == ["skipped"] * 5
    assert [r["code"] for r in results] == [
        "node_unavailable", "node_not_found", "not_writable", "not_writable", "invalid_path",
    ]  # fmt: skip
    assert results[0]["reason"] == "unavailable"
    assert fake_client.writes == []


async def test_out_of_range_per_node(hass, matter_entry, fake_client, sleeps) -> None:
    """Limits come per node: one value passes on one node, is skipped on another."""
    await _setup(hass)
    path = "1/513/17"
    wide = _clone(fake_client, 7)
    for node, (lo, hi) in ((fake_client.get_node(6), (500, 3500)), (wide, (500, 2000))):
        node.node_data.attributes.update(
            {path: 2100, "1/513/5": lo, "1/513/6": hi, "1/513/7": lo, "1/513/8": hi}
        )
    items = [{"node_id": 6, "path": path}, {"node_id": 7, "path": path}]
    results = await async_write_many(hass, items, 2400)
    assert results[0]["status"] in ("ok", "mismatch", "timeout")
    assert results[1]["status"] == "skipped" and results[1]["reason"] == "out of range"
    assert fake_client.writes == [(6, path, 2400)]


async def test_every_write_goes_through_async_write(
    hass, matter_entry, fake_client, sleeps, monkeypatch
) -> None:
    await _setup(hass)
    _clone(fake_client, 7)
    calls = []
    real = writable.async_write

    async def spy(hass_, node_id, path, value):
        calls.append((node_id, path, value))
        return await real(hass_, node_id, path, value)

    monkeypatch.setattr(writable, "async_write", spy)
    await async_write_many(hass, _items(6, 7), 3)
    assert calls == fake_client.writes == [(6, PATH, 3), (7, PATH, 3)]


async def _ws(hass, hass_ws_client, items, value):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "matter_explorer/write_many", "items": items, "value": value}
    )
    return client, await client.receive_json()


async def test_ws_streams_progress(
    hass, matter_entry, fake_client, sleeps, hass_ws_client: WebSocketGenerator
) -> None:
    await _setup(hass)
    _clone(fake_client, 7)
    client, ack = await _ws(hass, hass_ws_client, _items(6, 7), 2)
    assert ack["success"]
    p1 = await client.receive_json()
    p2 = await client.receive_json()
    done = await client.receive_json()
    assert p1["event"] == {"event": "progress", "done": 1, "total": 2, "item": p1["event"]["item"]}
    assert p2["event"]["done"] == 2
    assert done["event"]["event"] == "done"
    assert [r["status"] for r in done["event"]["results"]] == ["ok", "ok"]


async def test_ws_limit_and_validation(
    hass, matter_entry, fake_client, hass_ws_client: WebSocketGenerator
) -> None:
    await _setup(hass)
    _, msg = await _ws(hass, hass_ws_client, _items(*([6] * 50)), 2)
    assert msg["success"]
    _, msg = await _ws(hass, hass_ws_client, _items(*([6] * 51)), 2)
    assert not msg["success"] and msg["error"]["code"] == "invalid_format"
    _, msg = await _ws(hass, hass_ws_client, [], 2)
    assert not msg["success"]
    _, msg = await _ws(hass, hass_ws_client, _items(6), [1])
    assert not msg["success"]


async def test_ws_admin_only(
    hass, matter_entry, fake_client, hass_ws_client: WebSocketGenerator, hass_admin_user
) -> None:
    await _setup(hass)
    hass_admin_user.groups = []
    _, msg = await _ws(hass, hass_ws_client, _items(6), 2)
    assert not msg["success"] and msg["error"]["code"] == "unauthorized"
    assert fake_client.writes == []
