#!/usr/bin/env python3
"""Lab end to end scenarios, one subcommand each. LAB ONLY (refuses any other Home Assistant).

Usage:
  .venv/bin/python scripts/lab/e2e.py child-lock [NODE]
  .venv/bin/python scripts/lab/e2e.py entities tick|untick|check|write NODE PATH [VALUE]
  .venv/bin/python scripts/lab/e2e.py identify | new-node | robustness
  /tmp/pwenv/bin/python scripts/lab/e2e.py bulk-write [--skipped]   (needs Playwright, set CHROMIUM)

Each scenario's own notes are the comment block above its code. Exit status is non-zero on any FAIL.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from labenv import LAB_HA_CONFIG, NODE_MAP, is_lab_url

try:  # the websocket scenarios need aiohttp (the project venv)
    import aiohttp
    import bootstrap
    import ha_ws
    from ha_ws import CREDS, HA_URL, call
except ImportError:
    aiohttp = bootstrap = ha_ws = None
try:  # bulk-write drives the panel and needs Playwright (the throwaway venv)
    from playwright.sync_api import sync_playwright
    from screenshots import FIND, OUT, login, open_panel, panel_eval
except ImportError:
    sync_playwright = None

CMD = sys.argv[1] if len(sys.argv) > 1 else ""
ARGS = sys.argv[2:]


# ---- child-lock ----------------------------------------------------------------------------------
# Lab end to end for the thermostat child lock (1/516/1) and setpoint (1/513/18).
#
# Usage: .venv/bin/python scripts/lab/e2e_child_lock.py [NODE]   (default: node of "lab-thermostat" from
# $LAB_HOME/nodes.json). Talks only to the LAB Home Assistant. Exits non-zero on any failed check.
#
# Steps: nodes lists 1/516/1 with enum labels; write 0 -> 1 -> 0 via matter_explorer/write with readback
# match; tick the select, change it through HA, read back, untick; the same for 1/513/18 as a number (21.0 C).

LOCK, SETPOINT = "1/516/1", "1/513/18"
cl_failures: list[str] = []


def cl_check(ok: bool, what: str, detail: object = "") -> None:
    print(("PASS " if ok else "FAIL ") + what, detail)
    if not ok:
        cl_failures.append(what)


async def cl_attr(node: int, path: str) -> dict:
    for n in (await call("matter_explorer/nodes"))["result"]["nodes"]:
        for e in n["endpoints"]:
            for c in e["clusters"]:
                for a in c["attributes"]:
                    if n["node_id"] == node and a["path"] == path:
                        return a
    raise SystemExit(f"{path} not found on node {node}")


async def cl_state_of(entity_id: str) -> str:
    states = (await call("get_states"))["result"]
    return next(s["state"] for s in states if s["entity_id"] == entity_id)


async def cl_exposed_paths() -> list:
    return [
        (await cl_attr(n, p))["entity"]["exposed"]
        for n, p in ((CL_NODE, LOCK), (CL_NODE, SETPOINT))
    ]


async def cl_ha_set(entity_id: str, value: str) -> None:
    domain = entity_id.split(".", maxsplit=1)[0]
    if domain == "select":
        data, service = {"option": value}, "select_option"
    else:
        data, service = {"value": float(value)}, "set_value"
    res = await call(
        "call_service", domain=domain, service=service,
        service_data=data, target={"entity_id": entity_id},
    )  # fmt: skip
    cl_check(res.get("success", False), f"{domain}.{service} {value}", res.get("error", ""))
    await asyncio.sleep(2)


CL_LOG = LAB_HA_CONFIG / "home-assistant.log"


async def cl_main() -> None:
    # the write log lines are INFO; make them visible (runtime only, resets at HA restart)
    await call(
        "call_service", domain="logger", service="set_level",
        service_data={"custom_components.matter_explorer": "info"},
    )  # fmt: skip
    log_before = CL_LOG.read_text().count("Matter write node=") if CL_LOG.exists() else 0
    a = await cl_attr(CL_NODE, LOCK)
    labels = a["meta"].get("enum_values")
    cl_check(
        labels == {"0": "NoLockout", **{str(i): f"Lockout{i}" for i in range(1, 6)}},
        "nodes lists 1/516/1 with enum labels", labels,
    )  # fmt: skip
    for value in (0, 1, 0):
        res = await call("matter_explorer/write", node_id=CL_NODE, path=LOCK, value=value)
        r = res.get("result") or {}
        cl_check(
            bool(res.get("success")) and r.get("matches") is True and r.get("read_back") == value,
            f"write {LOCK} = {value}", r or res.get("error"),
        )  # fmt: skip
    lines = (
        [x for x in CL_LOG.read_text().splitlines() if "Matter write node=" in x]
        if CL_LOG.exists()
        else []
    )
    cl_check(
        len(lines) - log_before >= 6,
        "write log lines in the lab HA log",
        lines[-1:] and lines[-1][-90:],
    )
    # select entity
    res = await call("matter_explorer/set_exposed", node_id=CL_NODE, path=LOCK, exposed=True)
    cl_check(res.get("success", False), "tick child lock", res.get("result") or res.get("error"))
    a = await cl_attr(CL_NODE, LOCK)
    eid = a["entity"]["entity_id"]
    cl_check(bool(eid and eid.startswith("select.")), "select entity exists", eid)
    reg = next(
        e for e in (await call("config/entity_registry/list"))["result"] if e["entity_id"] == eid
    )
    print("  select options:", (await call("get_states"))["result"] and [
        s["attributes"].get("options") for s in (await call("get_states"))["result"]
        if s["entity_id"] == eid
    ], "device_id", reg.get("device_id"))  # fmt: skip
    await cl_ha_set(eid, "Level 3")
    a = await cl_attr(CL_NODE, LOCK)
    cl_check(a["value"] == 3, "HA select -> node value 3 (panel sees it)", a["display_value"])
    cl_check(await cl_state_of(eid) == "Level 3", "entity state follows", await cl_state_of(eid))
    await cl_ha_set(eid, "Off")
    a = await cl_attr(CL_NODE, LOCK)
    cl_check(a["value"] == 0, "HA select back -> node value 0", a["value"])
    res = await call("matter_explorer/set_exposed", node_id=CL_NODE, path=LOCK, exposed=False)
    cl_check(res.get("success", False), "untick child lock")
    cl_check(
        not (await cl_attr(CL_NODE, LOCK))["entity"]["exposed"], "child lock no longer exposed"
    )
    # setpoint
    await call("matter_explorer/set_exposed", node_id=CL_NODE, path=SETPOINT, exposed=True)
    a = await cl_attr(CL_NODE, SETPOINT)
    eid = a["entity"]["entity_id"]
    cl_check(bool(eid and eid.startswith("number.")), "number entity exists", eid)
    states = (await call("get_states"))["result"]
    st = next(s for s in states if s["entity_id"] == eid)
    print(
        "  number attrs:",
        {k: st["attributes"].get(k) for k in ("min", "max", "unit_of_measurement")},
    )
    await cl_ha_set(eid, "22.5")
    cl_check((await cl_attr(CL_NODE, SETPOINT))["value"] == 2250, "number 22.5 -> node 2250")
    await cl_ha_set(eid, "21.0")
    a = await cl_attr(CL_NODE, SETPOINT)
    cl_check(a["value"] == 2100, "number 21.0 -> node 2100", a["value"])
    await call("matter_explorer/set_exposed", node_id=CL_NODE, path=SETPOINT, exposed=False)
    cl_check(not (await cl_attr(CL_NODE, SETPOINT))["entity"]["exposed"], "setpoint untick")
    print("FAILED: " + ", ".join(cl_failures) if cl_failures else "ALL PASSED")
    sys.exit(1 if cl_failures else 0)


CL_NODE = 0
if CMD == "child-lock":
    CL_NODE = int(ARGS[0]) if ARGS else json.loads(NODE_MAP.read_text())["lab-thermostat"]


# ---- bulk-write ----------------------------------------------------------------------------------
# Lab end to end + screenshots for the bulk write in the across view (0090), on the LAB Home Assistant.
#
# Usage: /tmp/pwenv/bin/python scripts/lab/e2e_bulk_write.py [--skipped]
# Needs two lab thermostats (scripts/lab-thermostat.sh 2 + bootstrap). Drives the real panel: across view
# 516/1, select all writable, set child lock 0 -> 2 -> 0 with read-back per device, screenshots
# docs/screenshots/0090-{select,confirm,result}.png. With --skipped, stop the second thermostat first
# (`screen -S thermostat2 -X quit`) and wait until HA reports node unavailable: the row shows as
# not selectable and the confirm dialog lists it as skipped (0090-skipped.png).


def bw_wait_for(page, sel: str, timeout: int = 60000) -> None:
    page.wait_for_function(
        "() => {" + FIND + f" return !!p.shadowRoot.querySelector('{sel}'); }}", timeout=timeout
    )


bw_failures: list[str] = []


def bw_check(ok: bool, what: str, detail: object = "") -> None:
    print(("PASS " if ok else "FAIL ") + what, detail)
    if not ok:
        bw_failures.append(what)


def bw_values(page) -> dict:
    return panel_eval(
        page,
        "p => Object.fromEntries(p._nodes.filter(n => n.endpoints.some(e => e.clusters.some(c => c.cluster_id === 516)))"
        ".map(n => [n.node_id, p._attrByPath(n, '1/516/1').value]))",
    )


def bw_bulk(page, value: int, name: str, shots: bool) -> None:
    panel_eval(page, "p => { p._pickAcross('516/1'); }")
    page.wait_for_timeout(500)
    panel_eval(page, "p => p._bulkSelect('all')")
    panel_eval(
        page,
        f"p => {{ const c = p.shadowRoot.getElementById('bulk-ctl'); c.value = '{value}'; c.dispatchEvent(new Event('change', {{bubbles: true}})); }}",
    )
    page.wait_for_timeout(300)
    if shots:
        page.screenshot(path=OUT / "0090-select.png")
    panel_eval(page, "p => p.shadowRoot.getElementById('bulk-open').click()")
    bw_wait_for(page, ".dialog button[data-dlg=bulk-confirm]")
    if shots:
        page.screenshot(path=OUT / "0090-confirm.png")
    print(
        "confirm button:",
        panel_eval(page, "p => p.shadowRoot.querySelector('[data-dlg=bulk-confirm]').textContent"),
    )
    panel_eval(page, "p => p.shadowRoot.querySelector('[data-dlg=bulk-confirm]').click()")
    bw_wait_for(page, "#result")
    page.wait_for_timeout(500)
    if shots:
        page.screenshot(path=OUT / name)
    print("result:", panel_eval(page, "p => p.shadowRoot.getElementById('result').textContent"))
    panel_eval(page, "p => p.shadowRoot.querySelector('[data-dlg=close]').click()")
    page.wait_for_timeout(500)


def bw_main() -> None:
    skipped = "--skipped" in sys.argv
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM"))
        page = browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
        login(page)
        open_panel(page)
        if skipped:
            panel_eval(page, "p => p._pickAcross('516/1')")
            page.wait_for_timeout(500)
            page.screenshot(path=OUT / "0090-skipped-select.png")
            target = 0 if 2 in bw_values(page).values() else 2  # something must change
            bw_bulk(page, target, "0090-result.png", True)
            print("values", bw_values(page))
        else:
            start = bw_values(page)
            print("start", start)
            bw_check(len(start) >= 2, "two thermostats in the lab", start)
            bw_bulk(page, 2, "0090-result.png", True)
            v = bw_values(page)
            bw_check(all(x == 2 for x in v.values()), "all child locks are 2 (panel)", v)
            bw_bulk(page, 0, "0090-back.png", False)
            v = bw_values(page)
            bw_check(all(x == 0 for x in v.values()), "all child locks are 0 (panel)", v)
        browser.close()
    sys.exit(1 if bw_failures else 0)


# ---- entities ------------------------------------------------------------------------------------
# Lab end to end for "Add as entity". Usage: e2e_entities.py tick|write|untick|check NODE PATH [VALUE]
#
# Talks only to the LAB Home Assistant. Defaults to nothing; the caller picks node and path
# (child lock is 6/1/516/1 once the lab thermostat is commissioned; until then identifyTime of the
# light works: node 2, path 1/3/0).


async def en_entity_of(node: int, path: str) -> dict | None:
    res = await call("matter_explorer/nodes")
    for n in res["result"]["nodes"]:
        for e in n["endpoints"]:
            for c in e["clusters"]:
                for a in c["attributes"]:
                    if n["node_id"] == node and a["path"] == path:
                        return a
    return None


async def en_main() -> None:
    cmd, node, path = ARGS[0], int(ARGS[1]), ARGS[2]
    if cmd in ("tick", "untick"):
        res = await call(
            "matter_explorer/set_exposed", node_id=node, path=path, exposed=cmd == "tick"
        )
        print(res)
    elif cmd == "check":
        a = await en_entity_of(node, path)
        print("value", a["value"], "entity", a["entity"])
        if a["entity"]["entity_id"]:
            states = (await call("get_states"))["result"]
            print([s for s in states if s["entity_id"] == a["entity"]["entity_id"]])
        reg = (await call("config/entity_registry/list"))["result"]
        print("registry:", [e["entity_id"] for e in reg if e["platform"] == "matter_explorer"])
    elif (
        cmd == "write"
    ):  # through the HA entity (service call), value is the entity's option / number
        a = await en_entity_of(node, path)
        eid = a["entity"]["entity_id"]
        domain = eid.split(".")[0]
        value = ARGS[3]
        if domain == "select":
            res = await call(
                "call_service", domain="select", service="select_option",
                service_data={"option": value}, target={"entity_id": eid},
            )  # fmt: skip
        else:
            res = await call(
                "call_service", domain="number", service="set_value",
                service_data={"value": float(value)}, target={"entity_id": eid},
            )  # fmt: skip
        print(res)
        await asyncio.sleep(1)
        a = await en_entity_of(node, path)
        print("value now", a["value"])


# ---- identify ------------------------------------------------------------------------------------
# Lab e2e for Identify (0110): send Identify to the lab light and thermostat, watch attribute 3/0.
#
# Usage: .venv/bin/python scripts/lab/e2e_identify.py


def idn_identify_time(node: dict, ep: int):
    for e in node["endpoints"]:
        if e["endpoint_id"] == ep:
            for c in e["clusters"]:
                for a in c["attributes"]:
                    if a["path"] == f"{ep}/3/0":
                        return a["value"]
    return None


async def idn_main() -> int:
    nodes = (await call("matter_explorer/nodes"))["result"]["nodes"]
    bad = 0
    for n in nodes:
        eps = [
            e["endpoint_id"]
            for e in n["endpoints"]
            if e["endpoint_id"] and any(c["cluster_id"] == 3 for c in e["clusters"])
        ]
        if not eps or not n["available"]:
            continue
        ep = eps[0]
        res = await call("matter_explorer/identify", node_id=n["node_id"], endpoint_id=ep)
        await asyncio.sleep(3)
        after = next(
            x
            for x in (await call("matter_explorer/nodes"))["result"]["nodes"]
            if x["node_id"] == n["node_id"]
        )
        t = idn_identify_time(after, ep)
        ok = res.get("success") and isinstance(t, int) and 0 < t <= 15
        print(
            f"{'PASS' if ok else 'FAIL'} node {n['node_id']} {n['name']!r} ep {ep}: {res.get('success')} 3/0={t}"
        )
        bad += not ok
    res = await call("matter_explorer/identify", node_id=99999, endpoint_id=1)
    print("unknown node:", res.get("error", {}).get("code"))
    return bad


# ---- new-node ------------------------------------------------------------------------------------
# Lab check for 0100: a node commissioned while HA runs shows live values without a restart.
#
# Usage: .venv/bin/python scripts/lab/e2e_new_node.py
# Then reloads HA's matter entry (what HA does itself when the Matter Server connection drops, with a new
# MatterClient) and checks again: before 0.6.1 the values froze at the reconnect snapshot. Removes the second lab thermostat (node 30) from the lab Matter Server, commissions it again while the lab
# HA keeps running, then changes keypadLockout (516/1) through the Matter Server a few times and compares the
# value of `matter_explorer/nodes` with the Matter Server's. Lab only.

#!/usr/bin/env python3

NN_NAME = "lab-thermostat-2"
NN_PATH = "1/516/1"


async def nn_ha_value(node_id: int):
    res = await ha_ws.call("matter_explorer/nodes")
    for n in res["result"]["nodes"]:
        if n["node_id"] == node_id:
            for e in n["endpoints"]:
                for c in e["clusters"]:
                    for a in c["attributes"]:
                        if a["path"] == NN_PATH:
                            return a["value"]
    return "missing"


async def nn_main() -> int:
    mapping = json.loads(bootstrap.NODE_MAP.read_text())
    failures = 0
    async with aiohttp.ClientSession() as s, s.ws_connect(bootstrap.MATTER_URL) as ws:
        await ws.receive_json()
        m = bootstrap.Matter(ws)
        old = mapping.get(NN_NAME)
        if old is not None:
            print("removing node", old)
            await m.call("remove_node", node_id=old)
            await asyncio.sleep(3)
        node_id = await bootstrap.commission(m, NN_NAME, bootstrap.DEVICES[NN_NAME])
        mapping[NN_NAME] = node_id
        bootstrap.NODE_MAP.write_text(json.dumps(mapping))
        print("commissioned as node", node_id)
        await asyncio.sleep(5)
        failures += await nn_check(m, node_id, (2, 0, 1, 2))
        print("reloading the matter entry")
        await nn_reload_matter()
        await asyncio.sleep(10)
        failures += await nn_check(m, node_id, (1, 0, 2, 0))
    return 1 if failures else 0


async def nn_reload_matter() -> None:
    token = json.loads(ha_ws.CREDS.read_text())["token"]
    entries = (await ha_ws.call("config_entries/get", domain="matter"))["result"]
    async with aiohttp.ClientSession() as s:
        url = f"{ha_ws.HA_URL}/api/config/config_entries/entry/{entries[0]['entry_id']}/reload"
        async with s.post(url, headers={"Authorization": f"Bearer {token}"}) as resp:
            resp.raise_for_status()


async def nn_check(m, node_id: int, values) -> int:
    failures = 0
    for value in values:
        await m.call("write_attribute", node_id=node_id, attribute_path=NN_PATH, value=value)
        await asyncio.sleep(2)
        server = (await m.call("get_node", node_id=node_id))["attributes"][NN_PATH]
        ha = await nn_ha_value(node_id)
        ok = server == value and ha == value
        failures += not ok
        print("PASS" if ok else "FAIL", f"wrote {value}: matter server {server}, nodes {ha}")

    return failures


# ---- robustness ----------------------------------------------------------------------------------
# Lab e2e for 0120: the lab HA's matter entry goes away and comes back (LAB ONLY).
#
# 1. Disable the matter entry: the repair issue opens, websocket commands answer matter_unavailable,
#    explorer entities (if any) go unavailable. Enable it again: the issue clears, nodes come back.
# 2. Reload the matter entry (what HA does when the Matter Server connection drops): the explorer
#    follows the new client, values flow again without an HA restart.
# 3. A panel-like websocket subscribes, the socket is closed and reopened: subscribe + nodes work again.
#
# Usage: .venv/bin/python scripts/lab/e2e_robustness.py


async def rb_ws_cmds(*cmds: dict) -> list[dict]:
    token = json.loads(CREDS.read_text())["token"]
    out = []
    async with (
        aiohttp.ClientSession() as s,
        s.ws_connect(HA_URL + "/api/websocket", max_msg_size=0) as ws,
    ):
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": token})
        assert (await ws.receive_json())["type"] == "auth_ok"
        for i, c in enumerate(cmds, 1):
            await ws.send_json({"id": i, **c})
            while True:
                msg = await ws.receive_json()
                if msg.get("id") == i and msg["type"] == "result":
                    out.append(msg)
                    break
    return out


async def rb_issue_open() -> bool:
    (res,) = await rb_ws_cmds({"type": "repairs/list_issues"})
    return any(i["domain"] == "matter_explorer" for i in res["result"]["issues"])


async def rb_matter_entry_id() -> str:
    (res,) = await rb_ws_cmds({"type": "config_entries/get", "domain": "matter"})
    return res["result"][0]["entry_id"]


async def rb_wait(predicate, what: str, seconds: int = 90) -> bool:
    for _ in range(seconds):
        if await predicate():
            return True
        await asyncio.sleep(1)
    print(f"  timeout waiting for {what}")
    return False


async def rb_nodes_ok() -> bool:
    res = await call("matter_explorer/nodes")
    return bool(res.get("success") and res["result"]["nodes"])


async def rb_main() -> int:
    bad = 0
    eid = await rb_matter_entry_id()

    print("== 1. matter entry disabled (unloaded)")
    await rb_ws_cmds({"type": "config_entries/disable", "entry_id": eid, "disabled_by": "user"})
    await asyncio.sleep(3)
    res = await call("matter_explorer/nodes")
    code = res.get("error", {}).get("code")
    ok = code == "matter_unavailable"
    print(
        f"{'PASS' if ok else 'FAIL'} nodes while unloaded: {code} {res.get('error', {}).get('message')}"
    )
    bad += not ok
    ok = await rb_issue_open()
    print(f"{'PASS' if ok else 'FAIL'} repair issue open: {ok}")
    bad += not ok
    await rb_ws_cmds({"type": "config_entries/disable", "entry_id": eid, "disabled_by": None})
    ok = await rb_wait(rb_nodes_ok, "nodes after re-enable")
    print(f"{'PASS' if ok else 'FAIL'} nodes back after re-enable: {ok}")
    bad += not ok
    ok = not await rb_issue_open()
    print(f"{'PASS' if ok else 'FAIL'} repair issue cleared: {ok}")
    bad += not ok

    print("== 2. matter entry reload (new client)")
    token = json.loads(CREDS.read_text())["token"]
    async with (
        aiohttp.ClientSession() as s,
        s.post(
            f"{HA_URL}/api/config/config_entries/entry/{eid}/reload",
            headers={"Authorization": f"Bearer {token}"},
        ) as r,
    ):
        print("  reload ->", r.status)
    ok = await rb_wait(rb_nodes_ok, "nodes after reload")
    print(f"{'PASS' if ok else 'FAIL'} nodes after reload: {ok}")
    bad += not ok
    await asyncio.sleep(5)
    res = await call("matter_explorer/identify", node_id=2, endpoint_id=1)
    ok = res.get("success", False)
    print(f"{'PASS' if ok else 'FAIL'} identify works after reload: {ok}")
    bad += not ok

    print("== 4. websocket dropped and reopened")
    for n in (1, 2):
        res = await rb_ws_cmds(
            {"type": "matter_explorer/subscribe"}, {"type": "matter_explorer/nodes"}
        )
        ok = all(r["success"] for r in res)
        print(f"{'PASS' if ok else 'FAIL'} connection {n}: subscribe + nodes: {ok}")
        bad += not ok
    return bad


SCENARIOS = {
    "child-lock": cl_main,
    "bulk-write": bw_main,
    "entities": en_main,
    "identify": idn_main,
    "new-node": nn_main,
    "robustness": rb_main,
}


def main() -> int:
    if CMD not in SCENARIOS:
        sys.exit(__doc__)
    if CMD == "bulk-write":
        if sync_playwright is None:
            sys.exit(
                "bulk-write needs Playwright: /tmp/pwenv/bin/python scripts/lab/e2e.py bulk-write"
            )
    elif aiohttp is None:
        sys.exit("needs aiohttp: use .venv/bin/python")
    if aiohttp is not None and not is_lab_url(HA_URL):
        sys.exit("refusing: not the lab HA")
    run = SCENARIOS[CMD]
    result = asyncio.run(run()) if inspect.iscoroutinefunction(run) else run()
    return int(result or 0)


if __name__ == "__main__":
    sys.exit(main())
