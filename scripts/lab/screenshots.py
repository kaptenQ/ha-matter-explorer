"""Take the panel screenshots on the LAB Home Assistant (Playwright; not a project dependency).

Usage: /tmp/pwenv/bin/python scripts/lab/screenshots.py <scenario>   (uv venv /tmp/pwenv; uv pip install playwright)
Scenarios: export (0150-*), tour (tree, search, across, dark: 0040-*), entities, filters, write, identify, reconnect.
Set CHROMIUM to a Chrome binary if Playwright's own browser is missing. Other scripts import the helpers
(login, open_panel, panel_eval, FIND, OUT) from here. Credentials come from the lab credentials file (labenv.CREDS) and are
never printed. Each scenario's own notes are the comment block above its code.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, os.path.dirname(__file__))
import labenv

HA_URL = labenv.HA_URL
CREDS = json.loads(labenv.CREDS.read_text())
OUT = Path(__file__).resolve().parents[2] / "docs" / "screenshots"
PANEL = f"{HA_URL}/matter-explorer"
CMD = sys.argv[1] if len(sys.argv) > 1 else ""


def lab_thermostat_node() -> int:
    return json.loads(labenv.NODE_MAP.read_text())["lab-thermostat"]


def login(page: Page) -> None:
    page.goto(HA_URL)
    page.wait_for_selector("input[name=username]")
    page.fill("input[name=username]", CREDS["username"])
    page.fill("input[name=password]", CREDS["password"])
    page.press("input[name=password]", "Enter")
    page.wait_for_function("() => !location.pathname.startsWith('/auth')", timeout=30000)
    page.wait_for_timeout(2000)


FIND = (
    "const find = (root) => { for (const el of root.querySelectorAll('*')) {"
    " if (el.tagName === 'MATTER-EXPLORER-PANEL') return el;"
    " if (el.shadowRoot) { const r = find(el.shadowRoot); if (r) return r; } } return null; };"
    " const p = find(document);"
)


def open_panel(page: Page) -> None:
    page.goto(PANEL)
    page.wait_for_function(
        "() => {" + FIND + " return p && p.shadowRoot.querySelectorAll('.node').length > 0; }",
        timeout=30000,
    )
    page.wait_for_timeout(500)


def panel_eval(page: Page, js: str):
    return page.evaluate("() => {" + FIND + f" return ({js})(p); }}")


def tour_main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM"))
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        page = ctx.new_page()
        login(page)
        open_panel(page)
        # tree: thermostat expanded at 516
        panel_eval(
            page,
            """p => { p._filter = ''; p._expandAll(false);
              const has = id => n => n.endpoints.some(e => e.clusters.some(c => c.cluster_id === id));
              const t = p._nodes.find(has(513)) || p._nodes[0]; const want = p._nodes.find(has(513)) ? 516 : 6;
              p._expanded.add('n'+t.node_id);
              for (const e of t.endpoints) { p._expanded.add('n'+t.node_id+'/e'+e.endpoint_id);
                for (const c of e.clusters) if (c.cluster_id === want) p._expanded.add('n'+t.node_id+'/e'+e.endpoint_id+'/c'+want); }
              p._renderMain(); }""",
        )
        page.screenshot(path=OUT / "0040-tree.png")
        # search
        panel_eval(
            page,
            "p => { const i = p.shadowRoot.getElementById('search'); i.value=p._nodes.some(n => JSON.stringify(n).includes('Keypad')) ? 'keypad' : 'startup'; i.dispatchEvent(new Event('input')); }",
        )
        page.wait_for_timeout(300)
        page.screenshot(path=OUT / "0040-search.png")
        # across
        panel_eval(
            page,
            "p => { p._filter=''; p.shadowRoot.getElementById('search').value=''; p._pickAcross(p._nodes.some(n => n.endpoints.some(e => e.clusters.some(c => c.cluster_id === 516))) ? '516/1' : '6/0'); }",
        )
        page.wait_for_timeout(300)
        page.screenshot(path=OUT / "0040-across.png")
        # dark theme
        page.evaluate("() => localStorage.setItem('selectedTheme', JSON.stringify({dark: true}))")
        page.reload()
        open_panel(page)
        panel_eval(
            page,
            "p => p._pickAcross(p._nodes.some(n => n.endpoints.some(e => e.clusters.some(c => c.cluster_id === 516))) ? '516/1' : '6/0')",
        )
        page.wait_for_timeout(300)
        page.screenshot(path=OUT / "0040-dark.png")
        browser.close()


# ---- entities ------------------------------------------------------------------------------------
# Screenshots of "Add as entity" on the LAB Home Assistant (0060).
#
# Usage: /tmp/pwenv/bin/python scripts/lab/screenshots_entities.py
# Ticks keypadLockout / child lock of the lab thermostat (1/516/1) through the real checkbox, shows the panel and the
# device page, then unticks it again through the checkbox.

EN_NODE = lab_thermostat_node() if CMD == "entities" else 0
EN_BOX = f"input[data-expose='{EN_NODE}|1/516/1']"
EN_EXPAND = (
    f"p => {{ p._expandAll(false); p._expanded.add('n{EN_NODE}'); p._expanded.add('n{EN_NODE}/e1'); "
    f"p._expanded.add('n{EN_NODE}/e1/c516'); p._renderMain(); }}"
)


def en_main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM"))
        page = browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
        login(page)
        open_panel(page)
        panel_eval(
            page,
            EN_EXPAND,
        )
        page.locator(EN_BOX).click()  # real checkbox -> set_exposed
        page.wait_for_timeout(3000)
        page.screenshot(path=OUT / "0070-checkbox.png")
        panel_eval(page, "p => p._pickAcross('516/1')")
        page.wait_for_timeout(500)
        page.screenshot(path=OUT / "0070-across.png")
        dev = page.evaluate(
            """async () => { const h = document.querySelector('home-assistant').hass;
              const r = await h.callWS({type: 'config/entity_registry/list'});
              return r.find(e => e.platform === 'matter_explorer').device_id; }"""
        )
        page.goto(f"{HA_URL}/config/devices/device/{dev}")
        page.wait_for_timeout(4000)
        page.screenshot(path=OUT / "0070-device.png")
        open_panel(page)
        panel_eval(
            page,
            EN_EXPAND,
        )
        page.locator(EN_BOX).click()  # untick
        page.wait_for_timeout(3000)
        browser.close()


# ---- filters -------------------------------------------------------------------------------------
# Screenshots of the tree filters on the LAB Home Assistant (0080).
#
# Usage: /tmp/pwenv/bin/python scripts/lab/screenshots_filters.py
# Uses the real chips and the "/" shortcut. Writes docs/screenshots/0080-*.png.

FL_CLEAR = (
    "p => { p._filters = {...p._filters}; p.shadowRoot.querySelector('[data-clear]')?.click(); }"
)

FL_DEVICE = (
    "p => { const n = p._nodes.find(n => n.endpoints.some(e => e.clusters.some(c => c.cluster_id === 513))); "
    "p._filters = {...p._filters, device: String(n.node_id)}; p._filtersChanged(''); }"
)


def fl_chip(page, key):
    page.evaluate(
        "(k) => { const f = (r) => { for (const e of r.querySelectorAll('*')) { if (e.tagName === 'MATTER-EXPLORER-PANEL')"
        " return e; if (e.shadowRoot) { const x = f(e.shadowRoot); if (x) return x; } } }; "
        "f(document).shadowRoot.querySelector(`[data-f=${k}]`).click(); }",
        key,
    )
    page.wait_for_timeout(300)


def fl_main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM"))
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        page = ctx.new_page()
        login(page)
        open_panel(page)
        panel_eval(page, FL_CLEAR)
        fl_chip(page, "rwOnly")
        panel_eval(page, FL_DEVICE)
        # keyboard shortcut focuses the search
        page.keyboard.press("/")
        page.wait_for_timeout(300)
        focused = panel_eval(
            page, "p => p.shadowRoot.activeElement && p.shadowRoot.activeElement.id"
        )
        print("focused after '/':", focused)
        page.screenshot(path=OUT / "0080-rw-only.png")
        print("count:", panel_eval(page, "p => p.shadowRoot.getElementById('count').textContent"))
        # persisted across reload
        page.reload()
        open_panel(page)
        print("after reload rwOnly:", panel_eval(page, "p => p._filters.rwOnly"))
        panel_eval(page, FL_CLEAR)
        panel_eval(page, "p => { p.shadowRoot.getElementById('search').value = ''; }")
        fl_chip(page, "manufacturerOnly")
        print(
            "manufacturer count:",
            panel_eval(page, "p => p.shadowRoot.getElementById('count').textContent"),
        )
        panel_eval(page, FL_CLEAR)
        phone = browser.new_context(
            viewport={"width": 390, "height": 844}, device_scale_factor=2
        ).new_page()
        login(phone)
        open_panel(phone)
        fl_chip(phone, "rwOnly")
        phone.screenshot(path=OUT / "0080-filters-phone.png")
        panel_eval(phone, FL_CLEAR)
        dark = browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
        login(dark)
        dark.evaluate(
            "() => { const h = document.querySelector('home-assistant'); h.dispatchEvent(new CustomEvent('settheme',"
            " {detail: {dark: true}})); }"
        )
        open_panel(dark)
        fl_chip(dark, "rwOnly")
        panel_eval(dark, FL_DEVICE)
        dark.screenshot(path=OUT / "0080-dark.png")
        panel_eval(dark, FL_CLEAR)
        browser.close()


# ---- write ---------------------------------------------------------------------------------------
# Screenshots of the write dialog on the LAB Home Assistant (0050).
#
# Usage: /tmp/pwenv/bin/python scripts/lab/screenshots_write.py
# Writes keypadLockout (child lock, 1/516/1) of the lab thermostat 0 -> 1 -> back to 0 through the real dialog.

WR_NODE = lab_thermostat_node() if CMD == "write" else 0


def wr_main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM"))
        page = browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
        login(page)
        open_panel(page)
        panel_eval(
            page,
            f"""p => {{ p._expandAll(false);
              p._expanded.add('n{WR_NODE}'); p._expanded.add('n{WR_NODE}/e1'); p._expanded.add('n{WR_NODE}/e1/c516');
              p._renderMain(); p._openEdit({WR_NODE}, '1/516/1'); }}""",
        )
        page.screenshot(path=OUT / "0050-edit.png")
        panel_eval(page, "p => { p.shadowRoot.getElementById('ctl').value = '1'; }")
        panel_eval(page, "p => p._onDialogClick('save')")
        page.wait_for_timeout(300)
        page.screenshot(path=OUT / "0050-confirm.png")
        panel_eval(page, "p => p._onDialogClick('confirm')")
        page.wait_for_timeout(3000)
        page.screenshot(path=OUT / "0050-result.png")
        panel_eval(page, "p => p._onDialogClick('close')")
        # put it back through the dialog too
        panel_eval(
            page,
            f"p => {{ p._openEdit({WR_NODE}, '1/516/1'); p.shadowRoot.getElementById('ctl').value = '0'; p._onDialogClick('save'); }}",
        )
        page.wait_for_timeout(200)
        panel_eval(page, "p => p._onDialogClick('confirm')")
        page.wait_for_timeout(3000)
        browser.close()


# ---- identify ------------------------------------------------------------------------------------
# Screenshot of the Identify button (0110) on the LAB HA. /tmp/pwenv/bin/python scripts/lab/screenshot_identify.py


def idn_main() -> None:
    sys.path.insert(0, os.path.dirname(__file__))
    from screenshots import OUT, login, open_panel, panel_eval

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM"))
        page = browser.new_context(viewport={"width": 1400, "height": 700}).new_page()
        login(page)
        open_panel(page)
        panel_eval(
            page,
            "p => { p._expanded = new Set(); for (const n of p._nodes) { p._expanded.add('n'+n.node_id);"
            " for (const e of n.endpoints) if (e.endpoint_id) p._expanded.add('n'+n.node_id+'/e'+e.endpoint_id);} p._render(); }",
        )
        page.wait_for_timeout(500)
        panel_eval(page, "p => p.shadowRoot.querySelector('[data-identify]').click()")
        page.wait_for_timeout(800)
        page.screenshot(path=OUT / "0110-identify.png")
        browser.close()


# ---- reconnect -----------------------------------------------------------------------------------
# Lab check for 0120 case 4: the panel loses its websocket, shows the banner, recovers.
#
# /tmp/pwenv/bin/python scripts/lab/screenshot_reconnect.py


def rc_main() -> None:
    sys.path.insert(0, os.path.dirname(__file__))
    from screenshots import OUT, login, open_panel, panel_eval

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM"))
        ctx = browser.new_context(viewport={"width": 1400, "height": 600})
        page = ctx.new_page()
        login(page)
        open_panel(page)
        print("before:", panel_eval(page, "p => p.shadowRoot.getElementById('status').textContent"))
        print(
            "listeners:",
            panel_eval(
                page,
                "p => [!!p._connListeners, typeof p._hass.connection.addEventListener, p._hass.connection.constructor.name]",
            ),
        )
        panel_eval(
            page,
            "p => { window.__ev = []; for (const e of ['disconnected','ready','reconnect-error']) p._hass.connection.addEventListener(e, () => window.__ev.push([e, Date.now()])); }",
        )
        # drop the socket like a network blip; the HA frontend reconnects by itself after a moment
        ctx.set_offline(True)  # keep it down so the banner can be seen
        panel_eval(page, "p => { p._hass.connection.socket.close(); }")
        page.wait_for_timeout(1500)
        print(
            "banner:",
            panel_eval(
                page,
                "p => { const b = p.shadowRoot.getElementById('banner'); return [b.hidden, b.textContent]; }",
            ),
        )
        page.screenshot(path=OUT / "0120-reconnecting.png")
        ctx.set_offline(False)
        for _ in range(40):
            page.wait_for_timeout(500)
            if panel_eval(page, "p => p.shadowRoot.getElementById('banner').hidden"):
                break
        page.wait_for_timeout(1500)
        print(
            "after banner hidden:",
            panel_eval(page, "p => p.shadowRoot.getElementById('banner').hidden"),
        )
        print("events:", page.evaluate("window.__ev"))
        print("after:", panel_eval(page, "p => p.shadowRoot.getElementById('status').textContent"))
        browser.close()


# ---- export --------------------------------------------------------------------------------------
# 0150: Export (download of one device and of the fabric) and Compare against an earlier file.
# Writes one value on the lab thermostat's KeypadLockout between the export and the compare, then restores it.


def ex_main() -> None:
    import tempfile

    sys.path.insert(0, os.path.dirname(__file__))
    from screenshots import OUT, login, open_panel, panel_eval

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM"))
        page = browser.new_context(
            viewport={"width": 1400, "height": 800}, accept_downloads=True
        ).new_page()
        login(page)
        open_panel(page)
        tmp = Path(tempfile.mkdtemp())
        nid = lab_thermostat_node()
        with page.expect_download() as dl:
            panel_eval(
                page, f"p => p.shadowRoot.querySelector('button[data-export=\"{nid}\"]').click()"
            )
        node_file = tmp / dl.value.suggested_filename
        dl.value.save_as(node_file)
        with page.expect_download() as dl:
            panel_eval(page, "p => p.shadowRoot.getElementById('export-all').click()")
        fabric_file = tmp / dl.value.suggested_filename
        dl.value.save_as(fabric_file)
        print(
            "files:",
            node_file.name,
            node_file.stat().st_size,
            fabric_file.name,
            fabric_file.stat().st_size,
        )
        page.screenshot(path=OUT / "0150-export-buttons.png")
        # change one value, then compare
        path = "1/516/1"
        cur = panel_eval(page, f"p => p._attrByPath(p._node({nid}), '{path}').value")
        new = 2 if cur != 2 else 1
        print(
            "write:",
            panel_eval(
                page,
                f"p => p._hass.callWS({{type: 'matter_explorer/write', node_id: {nid}, path: '{path}', value: {new}}}).then(r => 'ok', e => JSON.stringify(e))",
            ),
        )
        page.wait_for_timeout(1500)
        handle = page.evaluate_handle(
            "() => { " + FIND + " return p.shadowRoot.getElementById('compare-file'); }"
        )
        handle.as_element().set_input_files(str(fabric_file))
        page.wait_for_function(
            "() => { " + FIND + " return p._view === 'compare'; }", timeout=15000
        )
        page.wait_for_timeout(500)
        print(
            "compare rows:",
            panel_eval(
                page,
                "p => p._compare.rows.map(r => [r.node_id, r.kind, r.path, r.before.value, r.after.value])",
            ),
        )
        page.screenshot(path=OUT / "0150-compare.png")
        panel_eval(page, f"p => {{ p._compare.device = '{nid}'; p._renderMain(); }}")
        page.wait_for_timeout(300)
        page.screenshot(path=OUT / "0150-compare-device.png")
        panel_eval(
            page,
            f"p => p._hass.callWS({{type: 'matter_explorer/write', node_id: {nid}, path: '{path}', value: {cur}}})",
        )
        browser.close()


SCENARIOS = {
    "export": ex_main,
    "tour": tour_main,
    "entities": en_main,
    "filters": fl_main,
    "write": wr_main,
    "identify": idn_main,
    "reconnect": rc_main,
}

if __name__ == "__main__":
    if CMD not in SCENARIOS:
        sys.exit(__doc__)
    SCENARIOS[CMD]()
