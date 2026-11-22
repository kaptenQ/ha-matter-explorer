"""The panel is split over plain ES modules: every relative import must be served and exist."""

from __future__ import annotations

import json
import re
from pathlib import Path

from homeassistant.core import HomeAssistant

from custom_components.matter_explorer import FRONTEND_DIR

from .test_websocket_subscribe import _setup

IMPORT = re.compile(r'from "\./([\w.-]+\.js)"')


def _closure(name: str, seen: set[str]) -> set[str]:
    seen.add(name)
    for dep in IMPORT.findall((FRONTEND_DIR / name).read_text()):
        if dep not in seen:
            _closure(dep, seen)
    return seen


def test_relative_imports_all_exist() -> None:
    modules = _closure("matter-explorer-panel.js", set())
    assert {"filters.js", "bulk.js", "tree.js", "across.js", "dialogs.js"} <= modules
    assert all((FRONTEND_DIR / m).is_file() for m in modules)


async def test_modules_served_and_url_has_version(
    hass: HomeAssistant, matter_entry, hass_client
) -> None:
    await _setup(hass)
    version = json.loads((Path(FRONTEND_DIR).parent / "manifest.json").read_text())["version"]
    panel = hass.data["frontend_panels"]["matter-explorer"]
    assert panel.config["_panel_custom"]["module_url"].endswith(f".js?v={version}")
    http = await hass_client()
    for module in _closure("matter-explorer-panel.js", set()):
        resp = await http.get(f"/matter_explorer_static/{module}")
        assert resp.status == 200, module
