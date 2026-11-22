"""Shared settings for the lab scripts (all overridable through environment variables).

LAB_HOME      directory for lab state: ha.json (HA credentials, mode 600), nodes.json (node ids),
              thermostat/ (matter.js storage). Default ~/.matter-explorer-lab
LAB_HA_CONFIG the lab HA's /config directory as seen from here. Default <repo>/lab/ha-config
HA_URL        the lab Home Assistant. Default http://homeassistant:8123
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[2]
LAB_HOME = Path(os.environ.get("LAB_HOME", Path.home() / ".matter-explorer-lab"))
HA_URL = os.environ.get("HA_URL", "http://homeassistant:8123").rstrip("/")
MATTER_URL = os.environ.get("MATTER_SERVER_URL", "ws://matter-server:5580/ws")
CREDS = Path(os.environ.get("LAB_HA_CREDS", LAB_HOME / "ha.json"))
NODE_MAP = Path(os.environ.get("LAB_NODES", LAB_HOME / "nodes.json"))
LAB_HA_CONFIG = Path(os.environ.get("LAB_HA_CONFIG", REPO / "lab" / "ha-config"))
LAB_HOSTS = {"homeassistant", "localhost", "127.0.0.1", "::1"}


def is_lab_url(url: str) -> bool:
    """Guard: the scripts only talk to a lab HA (set LAB_ALLOW_HA_URL=1 for a lab with another host name)."""
    return os.environ.get("LAB_ALLOW_HA_URL") == "1" or urlparse(url).hostname in LAB_HOSTS
