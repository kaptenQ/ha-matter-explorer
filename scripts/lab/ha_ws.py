"""Call a websocket command on the LAB Home Assistant and print the JSON result.

Usage: .venv/bin/python scripts/lab/ha_ws.py matter_explorer/nodes [--summary]
"""

from __future__ import annotations

import asyncio
import json
import sys

import aiohttp
from labenv import CREDS, HA_URL


async def call(command: str, **payload) -> dict:
    token = json.loads(CREDS.read_text())["token"]
    async with (
        aiohttp.ClientSession() as s,
        s.ws_connect(HA_URL + "/api/websocket", max_msg_size=0) as ws,
    ):
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": token})
        assert (await ws.receive_json())["type"] == "auth_ok"
        await ws.send_json({"id": 1, "type": command, **payload})
        return await ws.receive_json()


if __name__ == "__main__":
    res = asyncio.run(call(sys.argv[1]))
    if "--summary" in sys.argv and res.get("success"):
        for n in res["result"]["nodes"]:
            attrs = sum(len(c["attributes"]) for e in n["endpoints"] for c in e["clusters"])
            print(
                f"node {n['node_id']}: {n['name']!r} available={n['available']} "
                f"endpoints={len(n['endpoints'])} attributes={attrs}"
            )
    else:
        print(json.dumps(res)[:2000])
