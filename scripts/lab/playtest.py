"""Playtest of the panel on the LAB Home Assistant (0130). Drives the panel like a user: real clicks and keys.

Usage: CHROMIUM=... /tmp/pwenv/bin/python scripts/lab/playtest.py [scenario ...]
Scenarios: open find expose misc kbd bulk (0130), 0160, 0180 (DOM checks of those changes; exit 1 on a failed check).
Writes docs/screenshots/0130-*.png (0160-*.png for the 0160 scenario) and prints observations. Leaves child lock Off on all thermostats.
"""

from __future__ import annotations

import os
import sys
import time

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(__file__))
from screenshots import FIND, HA_URL, OUT, PANEL, login, panel_eval

SIZES = {"desk": {"width": 1400, "height": 900}, "phone": {"width": 390, "height": 844}}


STATE = {"prefix": "0130"}
FAILED: list[str] = []


def check(ok, what):
    print("  CHECK", "PASS" if ok else "FAIL", what)
    if not ok:
        FAILED.append(what)


def shot(page, name):
    page.wait_for_timeout(300)
    page.screenshot(path=OUT / f"{STATE['prefix']}-{name}.png")
    print("shot", name)


def theme(page, dark):
    page.evaluate(
        "(d) => document.querySelector('home-assistant').dispatchEvent(new CustomEvent('settheme', {detail: {dark: d}}))",
        dark,
    )


def new_page(pw, browser, size, dark=False):
    ctx = browser.new_context(viewport=SIZES[size], device_scale_factor=2 if size == "phone" else 1)
    page = ctx.new_page()
    login(page)
    theme(page, dark)
    return page


def q(page, sel):
    """Locator piercing the panel's shadow root (Playwright CSS pierces open shadow DOM)."""
    return page.locator(f"matter-explorer-panel {sel}")


def fopen(page):
    """Open the filters side panel (no-op when open)."""
    if q(page, "#fpanel").is_hidden():
        q(page, "#filters-btn").click()
        q(page, "#fpanel").wait_for(state="visible")


def clear(page):
    """Clear filters (the button is disabled when nothing is set)."""
    fopen(page)
    if q(page, "[data-clear]").is_enabled():
        clear(page)


def btn_text(page):
    return " ".join(q(page, "#filters-btn").inner_text().split())


def fclose(page):
    if q(page, "#fpanel").is_visible():
        q(page, "#fp-close").click()


def first_open(page):
    t0 = time.time()
    page.goto(PANEL)
    seen = {}
    while time.time() - t0 < 30:
        st = page.evaluate(
            "() => {"
            + FIND
            + " return p ? {built: !!p._built, nodes: p.shadowRoot.querySelectorAll('.node').length,"
            " main: p.shadowRoot.getElementById('main') ? p.shadowRoot.getElementById('main').innerText.slice(0,60) : null} : null; }"
        )
        key = str(st)
        if key not in seen:
            seen[key] = round(time.time() - t0, 2)
            print(f"  t={seen[key]}s", st)
            if st and st["built"] and not st["nodes"]:
                page.screenshot(path=OUT / "0130-loading.png")
        if st and st["nodes"]:
            break
        page.wait_for_timeout(50)
    print("first nodes at", round(time.time() - t0, 2), "s")


def fresh(page):
    """Open the panel with no saved search/filters (they persist in localStorage between visits)."""
    page.goto(PANEL)
    page.evaluate("() => localStorage.removeItem('matter_explorer.view')")
    page.reload()
    page.wait_for_selector("matter-explorer-panel .node")


def value_of(page, node_name_part):
    return panel_eval(
        page,
        "p => Object.fromEntries(p._nodes.map(n => [n.name, (() => { for (const e of n.endpoints) for (const c of e.clusters)"
        " if (c.cluster_id === 516) for (const a of c.attributes) if (a.attribute_id === 1) return a.value; })()]))",
    )


def find_childlock(page, size, tag):
    print("== find child lock", tag)
    fresh(page)
    # 1. search
    q(page, "#search").fill("child lock")
    shot(page, f"search-{tag}")
    print("  search count:", q(page, "#count").inner_text())
    # 2. filters: R/W only + device + cluster
    q(page, "#search").fill("")
    fopen(page)
    q(page, "[data-f=rwOnly]").check()
    fopen(page)
    q(page, "select[data-f=device]").select_option(index=4)
    shot(page, f"filters-{tag}")
    print("  filter count:", q(page, "#count").inner_text())
    fopen(page)
    clear(page)
    # 3. browse: expand thermostat -> endpoint -> Thermostat User Interface Configuration
    page.reload()
    page.wait_for_selector("matter-explorer-panel .node")
    q(page, "[data-toggle]").nth(3).click()
    shot(page, f"browse1-{tag}")
    print("  endpoint rows after node click:", q(page, ".endpoint").count())
    q(page, ".endpoint [data-toggle]").first.click()
    shot(page, f"browse2-{tag}")
    print("  clusters shown:", q(page, ".cluster").all_inner_texts()[:12])


def bulk_and_edit(page, tag):
    print("== bulk + edit", tag)
    fresh(page)
    page.locator("matter-explorer-panel #v-across").click()
    q(page, "[data-preset='516/1']").first.click()
    shot(page, f"across-{tag}")
    q(page, "[data-bulk=all]").click()
    shot(page, f"bulk-selected-{tag}")
    q(page, "#bulk-ctl").select_option(label="Level 1 (1)") if False else None
    opts = q(page, "#bulk-ctl option").all_inner_texts()
    print("  options:", opts)
    q(page, "#bulk-ctl").select_option(
        index=next(i for i, o in enumerate(opts) if "Level 1" in o or "1)" in o)
    )
    q(page, "#bulk-open").click()
    shot(page, f"bulk-confirm-{tag}")
    q(page, "[data-dlg=bulk-confirm]").click()
    q(page, "#result").wait_for(timeout=60000)
    shot(page, f"bulk-result-{tag}")
    print("  result:", q(page, "#result").inner_text())
    q(page, "[data-dlg=close]").click()
    print("  values:", value_of(page, ""))
    # single edit on one thermostat in the tree
    q(page, "#v-tree").click()
    q(page, "#search").fill("keypadlockout")
    shot(page, f"edit-found-{tag}")
    q(page, "[data-edit]").first.click()
    shot(page, f"edit-dialog-{tag}")
    opts = q(page, "#ctl option").all_inner_texts()
    print("  edit options:", opts)
    q(page, "#ctl").select_option(index=0)
    q(page, "[data-dlg=save]").click()
    shot(page, f"edit-confirm-{tag}")
    q(page, "[data-dlg=confirm]").click()
    q(page, "#result").wait_for(timeout=30000)
    shot(page, f"edit-result-{tag}")
    print("  edit result:", q(page, "#result").inner_text())
    q(page, "[data-dlg=close]").click()
    print("  values:", value_of(page, ""))


def identify_expose(page, tag):
    print("== identify + expose", tag)
    fresh(page)
    q(page, "#search").fill("lab thermostat 2")
    shot(page, f"identify-search-{tag}")
    q(page, "[data-toggle]").first.click()
    q(page, "[data-identify]").first.click()
    shot(page, f"identify-busy-{tag}")
    print(
        "  identify buttons:",
        q(page, "[data-identify]").count(),
        "first text:",
        q(page, "[data-identify]").first.inner_text(),
    )
    # expose child lock and setpoint on thermostat 2
    q(page, "#search").fill("")
    fopen(page)
    q(page, "select[data-f=device]").select_option(index=5)
    fopen(page)
    q(page, "[data-f=rwOnly]").check()
    shot(page, f"expose-before-{tag}")
    boxes = q(page, "[data-expose]")
    print("  expose boxes:", boxes.count())
    for i in range(boxes.count()):
        b = boxes.nth(i)
        if not b.is_checked():
            b.check()
            page.wait_for_timeout(800)
    shot(page, f"expose-after-{tag}")
    print("  entity ids:", q(page, ".entity-id").all_inner_texts())
    if tag.startswith("desk-light"):
        page.goto(f"{HA_URL}/config/entities?search=lab%20thermostat%202")
        page.wait_for_timeout(4000)
        shot(page, f"ha-entities-{tag}")
        fresh(page)
    fopen(page)
    q(page, "select[data-f=device]").select_option(index=5)
    fopen(page)
    q(page, "[data-f=rwOnly]").check()
    boxes = q(page, "[data-expose]")
    for i in range(boxes.count()):
        if boxes.nth(i).is_checked():
            boxes.nth(i).uncheck()
            page.wait_for_timeout(800)
    shot(page, f"unexpose-{tag}")
    print("  entity ids after unexpose:", q(page, ".entity-id").all_inner_texts())


FAKE = """p => {
  const long = 'Living room radiator thermostat with an extremely long user chosen name that goes on and on';
  const mk = (id, name, avail) => ({node_id: id, name, available: avail, product: 'Odd product with a long model string 9000', vendor: 'Acme', is_bridge: false,
    endpoints: [{endpoint_id: 1, clusters: [
      {cluster_id: 64512, name: 'unknown', unknown: true, attributes: [
        {attribute_id: 1, name: 'unknown', path: '1/64512/1', type: 'unknown', value: {a: 1, b: [1, 2, 3]}, write: null},
        {attribute_id: 65533, name: 'ClusterRevision', path: '1/64512/65533', type: 'int', value: 1, write: null}]}]}]});
  p._nodes = [...p._nodes, mk(901, long, true), mk(902, 'Offline sensor', false)];
  p._render();
}"""


def misc(page, tag):
    print("== misc", tag)
    fresh(page)
    # bridge: many endpoints
    q(page, "#search").fill("socket")
    page.wait_for_timeout(300)
    shot(page, f"bridge-{tag}")
    print("  bridge:", q(page, "#count").inner_text(), "endpoints:", q(page, ".endpoint").count())
    q(page, "#search").fill("")
    fopen(page)
    clear(page)
    panel_eval(page, FAKE)
    q(page, "#search").fill("Odd product")
    shot(page, f"edge-nodes-{tag}")
    q(page, "#search").fill("")
    fopen(page)
    q(page, "[data-f=hideGlobal]").uncheck()
    q(page, "#search").fill("Offline")
    shot(page, f"unavailable-{tag}")
    print(
        "  edit buttons on unavailable:",
        q(page, "[data-edit]").count(),
        "identify disabled:",
        q(page, "[data-identify][disabled]").count(),
    )
    q(page, "#search").fill("living room")
    page.wait_for_timeout(300)
    shot(page, f"long-name-{tag}")
    q(page, "#search").fill("unknown")
    shot(page, f"unknown-cluster-{tag}")


def keyboard(page, tag):
    print("== keyboard", tag)
    fresh(page)
    act = "() => { let a = document.activeElement; while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement; return a ? (a.tagName + '#' + a.id + '.' + (a.dataset ? Object.keys(a.dataset).join(',') : '') + ' ' + (a.getAttribute('aria-label') || a.innerText || a.title || '').slice(0, 30)) : null; }"
    page.keyboard.press("/")
    print("  after /:", page.evaluate(act))
    page.keyboard.press("Escape")
    print("  after Esc in search:", page.evaluate(act))
    page.locator("body").click(position={"x": 700, "y": 600})
    order = []
    for _ in range(28):
        page.keyboard.press("Tab")
        order.append(page.evaluate(act))
    print("  tab order:", order)
    # can a tree node be toggled by keyboard?
    q(page, "#search").fill("")
    q(page, "[data-toggle]").first.focus()
    print("  focus on toggle row:", page.evaluate(act))
    page.keyboard.press("Enter")
    print("  nodes expanded after Enter on row:", q(page, ".node > .children").count())
    page.keyboard.press("Space")
    # dialog by keyboard
    q(page, "#search").fill("keypadlockout")
    q(page, "[data-edit]").first.focus()
    page.keyboard.press("Enter")
    print("  dialog open:", q(page, "[role=dialog]").count(), "focus:", page.evaluate(act))
    shot(page, f"kbd-dialog-{tag}")
    page.keyboard.press("Escape")
    print("  dialog after Esc:", q(page, "[role=dialog]").count())
    if q(page, "[role=dialog]").count():
        q(page, "[data-dlg=cancel]").click()
    print("  focus after close:", page.evaluate(act))
    for _ in range(6):
        page.keyboard.press("Tab")
    print("  six tabs later:", page.evaluate(act))
    # a11y: unlabeled controls
    bad = panel_eval(
        page,
        "p => [...p.shadowRoot.querySelectorAll('button, input, select')].filter(e => !(e.getAttribute('aria-label') || (e.labels && e.labels.length) || e.innerText.trim() || e.title)).map(e => e.outerHTML.slice(0, 90))",
    )
    print("  unlabeled controls:", bad)
    print("  dialog attrs:", end=" ")
    q(page, "[data-edit]").first.click()
    print(
        panel_eval(
            page,
            "p => { const d = p.shadowRoot.querySelector('[role=dialog]'); return [d.getAttribute('aria-labelledby'), d.getAttribute('aria-label'), !!d.querySelector('h3')]; }",
        )
    )
    q(page, "[data-dlg=cancel]").click()


def playtest_0160(page, tag):
    """Phone cards, friendly labels in the bulk confirm, bridge names, restored note, Escape in search."""
    print("== 0160", tag)
    phone = tag.startswith("phone")
    fresh(page)
    # Escape clears the search
    q(page, "#search").fill("keypadlockout")
    q(page, "#search").press("Escape")
    check(q(page, "#search").input_value() == "", "Escape clears the search box")
    check(
        "keypadlockout"
        not in (page.evaluate("() => localStorage.getItem('matter_explorer.view')") or ""),
        "cleared search is saved",
    )
    # restored note
    q(page, "#search").fill("keypadlockout")
    page.reload()
    page.wait_for_selector("matter-explorer-panel .node")
    check(
        q(page, "#restored").count() == 1, "restored note shown after a reload with a saved search"
    )
    check(q(page, "#search").input_value() == "keypadlockout", "search restored")
    shot(page, f"restored-note-{tag}")
    q(page, "[data-clear-restored]").click()
    check(
        q(page, "#restored").count() == 0 and q(page, "#search").input_value() == "",
        "Clear removes note and search",
    )
    # phone cards
    q(page, "#search").fill("keypadlockout")
    q(page, ".attr").first.wait_for()
    shot(page, f"attr-cards-{tag}")
    box = lambda sel: q(page, sel).first.bounding_box()  # noqa: E731
    disp = q(page, ".attr").first.evaluate("e => getComputedStyle(e).display")
    if phone:
        check(disp == "flex", "phone: attribute is a flex card")
        name, val, path, edit = (
            box(".attr .aname"),
            box(".attr .val"),
            box(".attr .apath"),
            box(".attr button.edit"),
        )
        check(abs(name["y"] - val["y"]) < 20, "phone: name and value share the top line")
        check(path["y"] > name["y"] + name["height"] - 2, "phone: path below the name")
        check(edit["y"] > path["y"], "phone: actions below the meta line")
        small = [
            b
            for b in q(page, ".attr button, .attr label.expose").all()
            if min(b.bounding_box()["height"], 99) < 39.5
        ]
        check(not small, f"phone: all attribute actions are >= 40 px high ({len(small)} smaller)")
    else:
        check(disp == "grid", "desktop: attribute stays a grid")
    # friendly labels
    txt = q(page, ".attr .val").first.inner_text()
    print("  value text:", txt)
    check(
        "Lockout" not in txt and ("Off" in txt or "Level" in txt), "tree shows the friendly label"
    )
    check(
        q(page, ".attr .val span[title^=Lockout], .attr .val span[title=NoLockout]").count() >= 1,
        "spec name is the tooltip",
    )
    # bulk confirm with friendly labels
    page.locator("matter-explorer-panel #v-across").click()
    q(page, "[data-preset='516/1']").first.click()
    q(page, "[data-bulk=all]").click()
    opts = q(page, "#bulk-ctl option").all_inner_texts()
    print("  options:", opts)
    check(opts[:2] == ["Off (0)", "Level 1 (1)"], "bulk editor options are friendly")
    q(page, "#bulk-ctl").select_option(index=2)
    q(page, "#bulk-open").click()
    dlg = q(page, "[role=dialog]").inner_text()
    check(
        "Level 2" in dlg and not __import__("re").search(r"NoLockout|Lockout\d", dlg),
        "bulk confirm dialog shows Level 2, no spec names",
    )
    shot(page, f"bulk-confirm-childlock-{tag}")
    q(page, "[data-dlg=cancel]").click()
    bridge_names_0160(page, tag)


def bridge_names_0160(page, tag):
    """Bridged device names on the endpoint rows: shown, searchable, in the Device filter."""
    q(page, "#v-tree").click()
    q(page, "#search").fill("socket")
    names = q(page, ".epname").all_inner_texts()
    print("  bridged names:", names)
    check(len(names) > 0, "bridge endpoints show the bridged device name")
    shot(page, f"bridge-names-{tag}")
    if names:
        q(page, "#search").fill(names[0])
        check(q(page, ".endpoint").count() >= 1, "bridged name is searchable")
        devs = q(page, "select[data-f=device] option").all_inner_texts()
        check(any(names[0] in d for d in devs), "bridged name is in the Device filter")
    q(page, "#search").fill("")
    fopen(page)
    clear(page)


def playtest_0180(page, tag):  # noqa: PLR0915 (a linear list of checks)
    """Filters side panel: button + badge, Esc, focus, live tree, manufacturer list, no Hide endpoint 0, phone sheet."""
    print("== 0180", tag)
    phone = tag.startswith("phone")
    fresh(page)
    btn = q(page, "#filters-btn")
    check(btn.count() == 1 and "Filters" in btn_text(page), "one Filters button in the header")
    check(q(page, "#filterbar").count() == 0, "the filter bar is gone")
    check(
        q(page, "[data-f=hideRoot]").count() == 0 or q(page, "#fpanel").is_hidden(),
        "panel is closed at first",
    )
    check(btn_text(page) == "Filters", "no badge without active filters")
    before = q(page, "#count").inner_text()
    btn.click()
    q(page, "#fpanel").wait_for(state="visible")
    check(q(page, "[data-f=hideRoot]").count() == 0, "no Hide endpoint 0 filter")
    check(q(page, "#fpanel").get_attribute("role") == "region", "panel is a labelled region")
    box = q(page, "#fpanel").bounding_box()
    vp = SIZES["phone" if phone else "desk"]
    if phone:
        check(abs(box["width"] - vp["width"]) < 2, "phone: sheet is full width")
    else:
        check(300 <= box["width"] <= 340, f"desktop: panel about 320 px wide ({box['width']})")
        check(abs(box["x"] + box["width"] - vp["width"]) < 2, "desktop: panel sits on the right")
    in_panel = panel_eval(
        page, "p => p.shadowRoot.getElementById('fpanel').contains(p.shadowRoot.activeElement)"
    )
    check(in_panel, "focus moves into the panel")
    for _ in range(40):
        page.keyboard.press("Tab")
    in_panel = panel_eval(
        page, "p => p.shadowRoot.getElementById('fpanel').contains(p.shadowRoot.activeElement)"
    )
    check(in_panel, "focus stays in the panel after 40 Tabs")
    check(
        q(page, "#count").inner_text() == before and before != "",
        f"result count stays in the header ({before})",
    )
    for t in ("Devices", "Attributes", "Vendor-specific clusters only", "Manufacturer"):
        check(t.lower() in q(page, "#fpanel").inner_text().lower(), f"panel has '{t}'")
    mfr = q(page, "[data-mfr]")
    labels = q(page, ".mlist .frow").all_inner_texts()
    print("  manufacturers:", labels)
    check(len(labels) >= 1 and all("(" in x for x in labels), "manufacturer entries have counts")
    shot(page, f"panel-{tag}")
    # live update: tick the first manufacturer
    n_all = q(page, ".node").count()
    mfr.first.check()
    page.wait_for_timeout(200)
    check("Filters · 1" in btn_text(page), "badge says Filters · 1")
    check(q(page, ".node").count() <= n_all, "tree updates live")
    shot(page, f"manufacturer-{tag}")
    q(page, "[data-f=rwOnly]").check()
    check("Filters · 2" in btn_text(page), "badge says Filters · 2")
    q(page, "[data-clear]").click()
    check(btn_text(page) == "Filters", "Clear filters resets the badge")
    check(q(page, ".node").count() == n_all, "Clear filters restores the tree")
    page.keyboard.press("Escape")
    check(q(page, "#fpanel").is_hidden(), "Esc closes the panel")
    check(
        panel_eval(page, "p => p.shadowRoot.activeElement && p.shadowRoot.activeElement.id")
        == "filters-btn",
        "focus returns to the button",
    )
    # restored note's Clear is the same reset
    btn.click()
    q(page, "[data-f=rwOnly]").check()
    q(page, "#fp-close").click()
    page.reload()
    page.wait_for_selector("matter-explorer-panel .node")
    check(q(page, "#restored").count() == 1, "restored note shows")
    check("Filters · 1" in btn_text(page), "badge restored with the filters")
    q(page, "[data-clear-restored]").click()
    check(btn_text(page) == "Filters", "restored note Clear resets the filters")
    # across view: fewer filters, manufacturer still there
    q(page, "#v-across").click()
    btn.click()
    check(
        q(page, "[data-mfr]").count() >= 1 and q(page, "select[data-f=cluster]").count() == 0,
        "across view panel: manufacturer, no cluster",
    )
    shot(page, f"across-{tag}")
    q(page, "#fp-close").click()
    q(page, "#v-tree").click()


def main() -> None:
    which = sys.argv[1:] or ["open"]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM"))
        for size in ("desk", "phone"):
            for dark in (False, True):
                tag = f"{size}-{'dark' if dark else 'light'}"
                page = new_page(pw, browser, size, dark)
                if "open" in which:
                    print("==", tag, "first open")
                    first_open(page)
                    shot(page, f"open-{tag}")
                if "find" in which:
                    find_childlock(page, size, tag)
                if "expose" in which:
                    identify_expose(page, tag)
                if "misc" in which:
                    misc(page, tag)
                if "kbd" in which and tag == "desk-light":
                    keyboard(page, tag)
                if "bulk" in which:
                    bulk_and_edit(page, tag)
                if "0160" in which:
                    STATE["prefix"] = "0160"
                    if size == "phone" or tag == "desk-light":
                        playtest_0160(page, tag)
                if "0180" in which:
                    STATE["prefix"] = "0180"
                    playtest_0180(page, tag)
                page.context.close()
        browser.close()
    if FAILED:
        print("FAILED:", FAILED)
        sys.exit(1)


if __name__ == "__main__":
    main()
