#!/usr/bin/env python3
"""Idempotent lab bootstrap: commission sample devices, onboard lab HA, add Matter.

Run with the repo venv:  .venv/bin/python scripts/lab/bootstrap.py
Environment: MATTER_SERVER_URL (default ws://matter-server:5580/ws), HA_URL.
HA credentials are stored in $LAB_HOME/ha.json (mode 600) and never printed.
Commissioned sample device -> node id mapping lives in $LAB_HOME/nodes.json.
Only ever talks to the lab Matter Server and lab Home Assistant.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import socket
import sys
from pathlib import Path

import aiohttp
from labenv import CREDS as HA_CREDS
from labenv import HA_URL, MATTER_URL, NODE_MAP


def ha_matter_url() -> str:
    """URL HA should use for the Matter Server.

    The lab HA container has no IPv6 route, so the hostname (which also resolves to an IPv6
    address) makes its Matter config flow fail with cannot_connect. Use the IPv4 address.
    """
    from urllib.parse import urlsplit

    parts = urlsplit(MATTER_URL)
    try:
        ip = socket.getaddrinfo(parts.hostname, parts.port or 5580, socket.AF_INET)[0][4][0]
    except OSError:
        return MATTER_URL
    return MATTER_URL.replace(parts.hostname, ip, 1)


CLIENT_ID = f"{HA_URL}/"
DEVICES = {
    "dev-light": "20202021",
    "dev-sensor": "20202022",
    "dev-bridge": "20202023",
    "lab-thermostat": "20202024",  # runs in the dev container itself, see scripts/lab-thermostat.sh
    "lab-thermostat-2": "20202025",  # second instance (bulk write tests): scripts/lab-thermostat.sh 2
}
LOCAL_DEVICES = {"lab-thermostat", "lab-thermostat-2"}  # hostname of the device is this container's
REPO = Path(__file__).resolve().parents[2]
DISCRIMINATORS = {
    "dev-light": 3840,
    "dev-sensor": 3840,
    "dev-bridge": 3840,
    "lab-thermostat": 3844,
    "lab-thermostat-2": 3845,
}


def _verhoeff(digits: str) -> str:
    d = [
        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
        [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
        [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
        [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
        [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
        [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
        [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
        [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
        [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
        [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
    ]
    p = [
        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
        [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
        [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
        [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
        [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
        [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
        [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
        [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
    ]
    inv = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = d[c][p[(i + 1) % 8][int(ch)]]
    return str(inv[c])


def manual_code(passcode: int, discriminator: int) -> str:
    """11-digit manual pairing code (no vendor/product id) for passcode + 12-bit discriminator."""
    short = discriminator >> 8
    body = f"{(short >> 2) & 3}{((short & 3) << 14) | (passcode & 0x3FFF):05d}{passcode >> 14:04d}"
    return body + _verhoeff(body)


class Matter:
    def __init__(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        self.ws = ws
        self.n = 0

    async def call(self, command: str, timeout: float = 180, **args):
        self.n += 1
        mid = str(self.n)
        await self.ws.send_json({"message_id": mid, "command": command, "args": args})
        while True:
            msg = await self.ws.receive_json(timeout=timeout)
            if msg.get("message_id") == mid:
                if "error_code" in msg:
                    raise RuntimeError(f"{command}: error {msg['error_code']} {msg.get('details')}")
                return msg.get("result")


SIGNATURE = {  # how to recognise each sample device among existing nodes
    "dev-light": lambda n: (
        not n["is_bridge"]
        and "1/29/0" in n["attributes"]
        and any(d["0"] == 0x100 for d in n["attributes"]["1/29/0"])
    ),
    "dev-sensor": lambda n: (
        not n["is_bridge"] and any(d["0"] == 0x302 for d in n["attributes"].get("1/29/0", []))
    ),
    "dev-bridge": lambda n: n["is_bridge"],
    "lab-thermostat": lambda n: n["attributes"].get("0/40/5") == "Lab thermostat",
    "lab-thermostat-2": lambda n: n["attributes"].get("0/40/5") == "Lab thermostat 2",
}


def device_type_names(node: dict) -> str:
    attrs = node.get("attributes", {})
    parts = attrs.get("0/29/0", [])  # root parts list unused; use descriptor per endpoint
    del parts
    names = {}
    for key, val in attrs.items():
        ep, cluster, attr = key.split("/")
        if cluster == "29" and attr == "0":  # Descriptor.DeviceTypeList
            for dt in val:
                names.setdefault(int(ep), []).append(f"0x{dt['0']:04x}")
    return ", ".join(f"ep{ep}:{'+'.join(t)}" for ep, t in sorted(names.items()))


async def commission(m: Matter, name: str, code: str) -> int:
    host = socket.gethostname() if name in LOCAL_DEVICES else name
    ip6 = next(
        (
            a[4][0]
            for a in socket.getaddrinfo(host, None, socket.AF_INET6)
            if not a[4][0].startswith("fe80")
        ),
        None,
    )
    # 1) mDNS discovery by setup code (does not work on the lab Docker bridge so far)
    try:
        res = await m.call(
            "commission_with_code",
            timeout=90,
            code=manual_code(int(code), DISCRIMINATORS[name]),
            network_only=True,
        )
        return res["node_id"]
    except Exception as err:
        print(f"  {name}: commission_with_code failed ({err!r}); trying by IP {ip6}")
    # 2) by IP
    res = await m.call(
        "commission_on_network", setup_pin_code=int(code), ip_addr=ip6, filter_type=0
    )
    return res["node_id"]


async def commission_all() -> list[dict]:
    mapping = json.loads(NODE_MAP.read_text()) if NODE_MAP.exists() else {}
    async with aiohttp.ClientSession() as s, s.ws_connect(MATTER_URL) as ws:
        await ws.receive_json()
        m = Matter(ws)
        nodes = {n["node_id"]: n for n in await m.call("get_nodes")}
        for name, code in DEVICES.items():
            if mapping.get(name) not in nodes:
                found = [
                    i for i, n in nodes.items() if SIGNATURE[name](n) and i not in mapping.values()
                ]
                if found:
                    mapping[name] = found[0]
                    NODE_MAP.write_text(json.dumps(mapping))
            if mapping.get(name) in nodes:
                print(f"  {name}: already commissioned as node {mapping[name]}")
                continue
            print(f"  {name}: commissioning")
            try:
                mapping[name] = await commission(m, name, code)
                NODE_MAP.write_text(json.dumps(mapping))
            except Exception as err:
                print(f"  {name}: FAILED: {err!r}")
                if "test-net DCL" in str(err):
                    print(
                        "    -> the lab Matter Server must be started with --enable-test-net-dcl "
                        "(matter.js server) to accept test devices (see docs/DESIGN.md, Lab)"
                    )
        return await m.call("get_nodes")


async def ha_token(s: aiohttp.ClientSession) -> str | None:
    """Onboard HA if needed; return a long-lived access token (stored in HA_CREDS)."""
    creds = json.loads(HA_CREDS.read_text()) if HA_CREDS.exists() else {}
    if creds.get("token"):
        async with s.get(
            f"{HA_URL}/api/", headers={"Authorization": f"Bearer {creds['token']}"}
        ) as r:
            if r.status == 200:
                return creds["token"]
    async with s.get(f"{HA_URL}/api/onboarding") as r:
        steps = await r.json() if r.status == 200 else []
    pending = [x["step"] for x in steps if not x["done"]]
    if "user" in pending:
        creds = {
            "username": "labowner",
            "password": secrets.token_urlsafe(18),
        }
        async with s.post(
            f"{HA_URL}/api/onboarding/users",
            json={
                "client_id": CLIENT_ID,
                "name": "Lab Owner",
                "username": creds["username"],
                "password": creds["password"],
                "language": "en",
            },
        ) as r:
            r.raise_for_status()
            auth_code = (await r.json())["auth_code"]
        HA_CREDS.write_text(json.dumps(creds))
        HA_CREDS.chmod(0o600)
    elif not creds.get("username"):
        print("  HA is onboarded but credentials are not in", HA_CREDS)
        return None
    else:
        auth_code = None
    if auth_code is None:
        # log in through the login flow
        async with s.post(
            f"{HA_URL}/auth/login_flow",
            json={
                "client_id": CLIENT_ID,
                "handler": ["homeassistant", None],
                "redirect_uri": CLIENT_ID,
            },
        ) as r:
            flow = await r.json()
        async with s.post(
            f"{HA_URL}/auth/login_flow/{flow['flow_id']}",
            json={
                "username": creds["username"],
                "password": creds["password"],
                "client_id": CLIENT_ID,
            },
        ) as r:
            auth_code = (await r.json())["result"]
    async with s.post(
        f"{HA_URL}/auth/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "client_id": CLIENT_ID,
        },
    ) as r:
        r.raise_for_status()
        access = (await r.json())["access_token"]
    hdr = {"Authorization": f"Bearer {access}"}
    for step in ("core_config", "analytics"):
        async with s.post(f"{HA_URL}/api/onboarding/{step}", headers=hdr, json={}) as r:
            pass  # 200, or 403 if already done
    async with s.post(
        f"{HA_URL}/api/onboarding/integration",
        headers=hdr,
        json={"client_id": CLIENT_ID, "redirect_uri": CLIENT_ID},
    ):
        pass
    async with s.ws_connect(f"{HA_URL.replace('http', 'ws', 1)}/api/websocket") as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": access})
        await ws.receive_json()
        await ws.send_json(
            {
                "id": 1,
                "type": "auth/long_lived_access_token",
                "client_name": "lab-bootstrap",
                "lifespan": 3650,
            }
        )
        res = await ws.receive_json()
    creds["token"] = res["result"]
    HA_CREDS.write_text(json.dumps(creds))
    HA_CREDS.chmod(0o600)
    return creds["token"]


async def ha_matter(s: aiohttp.ClientSession, token: str) -> list[str]:
    hdr = {"Authorization": f"Bearer {token}"}
    async with s.get(f"{HA_URL}/api/config/config_entries/entry", headers=hdr) as r:
        entries = await r.json()
    if not any(e["domain"] == "matter" for e in entries):
        print("  adding the Matter integration")
        async with s.post(
            f"{HA_URL}/api/config/config_entries/flow",
            headers=hdr,
            json={"handler": "matter"},
        ) as r:
            flow = await r.json()
        if flow.get("type") == "form":
            async with s.post(
                f"{HA_URL}/api/config/config_entries/flow/{flow['flow_id']}",
                headers=hdr,
                json={"url": ha_matter_url()},
            ) as r:
                res = await r.json()
                print(
                    "  flow result:",
                    res.get("type"),
                    res.get("errors") or res.get("reason") or "",
                )
        else:
            print("  flow:", flow.get("type"), flow.get("reason"))
        await asyncio.sleep(10)
    # Matter devices known to HA's device registry, through the websocket API
    async with s.ws_connect(f"{HA_URL.replace('http', 'ws', 1)}/api/websocket") as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": token})
        await ws.receive_json()
        await ws.send_json({"id": 1, "type": "config/device_registry/list"})
        devs = (await ws.receive_json())["result"]
    return [
        d.get("name_by_user") or d.get("name") or "?"
        for d in devs
        if any(i[0] == "matter" for i in d.get("identifiers", []))
    ]


def start_thermostat() -> None:
    """Make sure the lab thermostat (matter.js, screen session) is running."""
    import subprocess

    script = str(REPO / "scripts" / "lab-thermostat.sh")
    for n in ("1", "2"):
        res = subprocess.run([script, n], check=False, capture_output=True, text=True)
        print(" ", (res.stdout or res.stderr).strip().splitlines()[-1:] or res.returncode)


async def main() -> int:
    start_thermostat()
    print("Matter Server:", MATTER_URL)
    nodes = await commission_all()
    print("\nNodes in the fabric:")
    for n in nodes:
        a = n["attributes"]
        print(
            f"  node {n['node_id']}: {a.get('0/40/3', '?')} "
            f"(bridge={n['is_bridge']}, available={n['available']}) {device_type_names(n)}"
        )
    print("\nHome Assistant:", HA_URL)
    async with aiohttp.ClientSession() as s:
        try:
            token = await ha_token(s)
            if token:
                devs = await ha_matter(s, token)
                print(f"  HA sees {len(devs)} Matter device(s): {', '.join(devs) or '-'}")
            else:
                print("  no HA token; skipped")
        except Exception as err:
            print(f"  HA step failed: {type(err).__name__}: {err}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
