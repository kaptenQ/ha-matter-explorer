/* Matter Explorer panel: a plain web component, no build step. Browsing is read-only; attributes the
 * backend marks writable (`entry.write`) get an Edit button -> edit / confirm / read-back dialog.
 * Talks to HA through the `hass` object: matter_explorer/nodes, /subscribe, /write and /write_many.
 *
 * The class is split over ES modules (plain files next to this one, loaded by relative import):
 * connection.js, tree.js, across.js, dialogs.js hold its methods (mixed in below); filters.js and
 * bulk.js are pure logic tested with node:test; util.js and styles.js are shared pieces. */

import { DEFAULT_FILTERS, ACROSS_FILTER_KEYS, hex, activeFilterCount, filtersNarrow, listClusters, listManufacturers, listDevices, hasRestored, loadPrefs, savePrefs } from "./filters.js";
import { esc } from "./util.js";
import { STYLE } from "./styles.js";
import { connectionMethods } from "./connection.js";
import { treeMethods } from "./tree.js";
import { acrossMethods } from "./across.js";
import { dialogsMethods } from "./dialogs.js";
import { exportMethods } from "./export.js";

class MatterExplorerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._nodes = null;
    this._error = null;
    this._expanded = new Set();
    const prefs = loadPrefs(this._storage());
    this._filter = prefs.search;
    this._filters = prefs.filters;
    this._restored = hasRestored(prefs); // show "Filters restored from last visit" until the user changes them
    this._changed = new Set(); // "node:path" of attributes that got a live update since the page opened
    this._view = "tree";
    this._across = null; // {cluster, attribute}
    this._acrossInput = "";
    this._unsub = null;
    this._subscribing = false;
    this._live = false;
    this._hass = null;
    this._built = false;
    this._missing = [];
    this._disconnected = false;
    this._connListeners = null;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (this._menu) this._menu.hass = hass;
    if (first && this.isConnected) this._start();
  }
  set narrow(v) {
    this._narrow = v;
    if (this._menu) this._menu.narrow = v;
  }
  set panel(_p) {}
  set route(_r) {}

  _storage() {
    try {
      return window.localStorage;
    } catch (_e) {
      return null; // blocked storage throws on access
    }
  }

  _savePrefs() {
    savePrefs(this._storage(), { filters: this._filters, search: this._filter });
  }

  _onKey = (e) => {
    if (e.key === "Escape" && this._fopen && !this._dlg) {
      e.preventDefault();
      this._openFilters(false);
      return;
    }
    if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey || !this._built) return;
    const t = e.composedPath()[0];
    if (t && (/^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName) || t.isContentEditable)) return;
    if (this._dlg) return;
    e.preventDefault();
    if (this._view !== "tree") this._setView("tree");
    const input = this.shadowRoot.getElementById("search");
    input.focus();
    input.select();
  };

  connectedCallback() {
    document.addEventListener("keydown", this._onKey);
    this._build();
    if (this._hass) this._start();
  }

  disconnectedCallback() {
    document.removeEventListener("keydown", this._onKey);
    this._stop();
  }

  /* ---- data ------------------------------------------------------------ */

  async _start() {
    this._watchConnection();
    if (!this._nodes && !this._loading) await this._load();
    await this._subscribe();
  }

  _node(id) {
    return (this._nodes || []).find((n) => n.node_id === id);
  }

  _attrByPath(node, path) {
    const [ep, cl, at] = path.split("/").map(Number);
    const endpoint = node.endpoints.find((e) => e.endpoint_id === ep);
    const cluster = endpoint && endpoint.clusters.find((c) => c.cluster_id === cl);
    return cluster && cluster.attributes.find((a) => a.attribute_id === at);
  }

  /* The backend's writability table decides: `write` is null for read-only attributes. */
  _isWritable(_node, entry) {
    return !!(entry && entry.write);
  }

  /* ---- skeleton -------------------------------------------------------- */

  _build() {
    if (this._built) return;
    this._built = true;
    const root = this.shadowRoot;
    root.innerHTML = `<style>${STYLE}</style>
      <header>
        <span id="menu"></span>
        <h1>Matter Explorer</h1>
        <button id="v-tree">Tree</button>
        <button id="v-across">Same attribute across devices</button>
        <label class="searchbox" id="searchbox"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9.5 3A6.5 6.5 0 0 1 16 9.5c0 1.61-.59 3.09-1.56 4.23l.27.27h.79l5 5-1.5 1.5-5-5v-.79l-.27-.27A6.52 6.52 0 0 1 9.5 16 6.5 6.5 0 0 1 3 9.5 6.5 6.5 0 0 1 9.5 3m0 2C7 5 5 7 5 9.5S7 14 9.5 14 14 12 14 9.5 12 5 9.5 5Z"/></svg>
          <input id="search" type="search" placeholder="Search … (name, id, value)" title="Press / to search" autocomplete="off" aria-label="Search"></label>
        <button id="filters-btn" aria-expanded="false" aria-controls="fpanel" title="Filters"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 18h4v-2h-4v2zM3 6v2h18V6H3zm3 7h12v-2H6v2z"/></svg> Filters<span class="fl-n"></span></button>
        <span id="count" class="count" aria-live="polite"></span>
        <span id="treebtns"><button id="expand">Expand all</button> <button id="collapse">Collapse all</button></span>
        <span class="spacer"></span>
        <span id="status" class="status"></span>
        <button id="export-all" title="Download every device as one JSON file">Export fabric</button>
        <button id="compare" title="Compare an earlier export file with now (in the browser, nothing is uploaded)">Compare…</button>
        <input id="compare-file" type="file" accept="application/json,.json" hidden>
        <button id="reload" title="Reload">Reload</button>
      </header>
      <aside id="fpanel" role="region" aria-labelledby="fp-title" hidden></aside>
      <div id="banner" class="banner" role="status" hidden></div>
      <div id="toast" class="toast" role="alert" hidden></div>
      <main id="main"></main>`;
    if (customElements.get("ha-menu-button")) {
      this._menu = document.createElement("ha-menu-button");
      this._menu.hass = this._hass;
      this._menu.narrow = this._narrow;
      root.getElementById("menu").appendChild(this._menu);
    }
    const $ = (id) => root.getElementById(id);
    $("v-tree").onclick = () => this._setView("tree");
    $("v-across").onclick = () => this._setView("across");
    $("search").value = this._filter;
    $("search").onkeydown = (e) => {
      if (e.key !== "Escape" || !e.target.value) return;
      e.preventDefault();
      e.stopPropagation();
      e.target.value = "";
      e.target.dispatchEvent(new Event("input"));
    };
    $("search").oninput = (e) => {
      this._restored = false;
      this._filter = e.target.value;
      this._savePrefs();
      this._renderMain();
    };
    $("filters-btn").onclick = () => this._openFilters(!this._fopen);
    const fp = $("fpanel");
    fp.addEventListener("change", (e) => {
      const t = e.target;
      this._restored = false;
      if (t.dataset && t.dataset.mfr !== undefined) {
        const set = new Set(this._filters.manufacturers);
        if (t.checked) set.add(t.dataset.mfr);
        else set.delete(t.dataset.mfr);
        this._filters = { ...this._filters, manufacturers: [...set].sort() };
        this._filtersChanged(`[data-mfr="${CSS.escape(t.dataset.mfr)}"]`);
        return;
      }
      const k = t.dataset && t.dataset.f;
      if (!k) return;
      this._filters = { ...this._filters, [k]: t.type === "checkbox" ? t.checked : t.value };
      this._filtersChanged(`[data-f="${k}"]`);
    });
    fp.addEventListener("click", (e) => {
      if (e.target.closest && e.target.closest("#fp-close")) this._openFilters(false);
      else if (e.target.closest && e.target.closest("[data-clear]")) this._resetFilters();
    });
    fp.addEventListener("keydown", (e) => {
      if (e.key === "Tab") this._trapTab(e);
    });
    $("expand").onclick = () => this._expandAll(true);
    $("collapse").onclick = () => this._expandAll(false);
    $("reload").onclick = () => this._load();
    $("export-all").onclick = () => this._exportDownload(null);
    $("compare").onclick = () => $("compare-file").click();
    $("compare-file").onchange = (e) => {
      const f = e.target.files && e.target.files[0];
      e.target.value = "";
      if (f) this._compareFile(f);
    };
    $("main").addEventListener("click", (e) => this._onClick(e));
    $("main").addEventListener("change", (e) => {
      if (e.target.dataset && e.target.dataset.cdev !== undefined && this._compare) {
        this._compare.device = e.target.value;
        this._renderMain();
        return;
      }
      if (e.target.dataset && e.target.dataset.expose !== undefined)
        this._toggleExpose(e.target.dataset.expose, e.target.checked);
      else if (e.target.dataset && e.target.dataset.sel !== undefined) {
        if (e.target.checked) this._bulk.selected.add(e.target.dataset.sel);
        else this._bulk.selected.delete(e.target.dataset.sel);
        this._bulkUpdateBar();
      } else if (e.target.id === "bulk-ctl") {
        const spec = this._bulkSpec(this._rows);
        if (spec) this._bulk.value = this._readControl({ entry: spec }, "bulk-ctl");
      }
    });
    $("main").addEventListener("input", (e) => {
      if (e.target.id === "across-input") {
        this._acrossInput = e.target.value;
        this._resolveAcross(false);
      }
    });
    $("main").addEventListener("keydown", (e) => {
      if (e.target.id === "across-input" && e.key === "Enter") this._resolveAcross(true);
      const row = e.target.dataset && e.target.dataset.toggle !== undefined ? e.target : null;
      if ((e.key === "Enter" || e.key === " ") && row) {
        e.preventDefault();
        row.click();
      }
    });
    this._render();
  }

  _setView(v) {
    this._view = v;
    this._lastCount = null;
    this._render();
  }

  _render() {
    if (!this._built) return;
    const $ = (id) => this.shadowRoot.getElementById(id);
    $("v-tree").classList.toggle("active", this._view === "tree");
    $("v-across").classList.toggle("active", this._view === "across");
    $("searchbox").style.display = this._view === "tree" ? "" : "none";
    $("treebtns").style.display = this._view === "tree" ? "" : "none";
    $("filters-btn").style.display = this._view === "compare" ? "none" : "";
    $("count").style.display = this._view === "compare" ? "none" : "";
    if (this._view === "compare") this._openFilters(false);
    this._renderStatus();
    this._renderBanner();
    this._renderFilters();
    this._renderMain();
    this._showToast(this._toast);
  }

  _filtersChanged(focusSel) {
    this._savePrefs();
    this._renderFilters();
    if (focusSel) {
      const el = this.shadowRoot.querySelector(`#fpanel ${focusSel}`);
      if (el) el.focus();
    }
    this._renderMain();
  }

  _check(key, label, hint) {
    const on = !!this._filters[key];
    return `<label class="frow" title="${esc(hint)}"><input type="checkbox" data-f="${key}" ${on ? "checked" : ""}><span>${esc(label)}</span></label>`;
  }

  /* The keys of the filters the current view understands (the across view has fewer). */
  _viewFilterKeys() {
    return this._view === "across" ? ACROSS_FILTER_KEYS : Object.keys(DEFAULT_FILTERS);
  }

  _renderFilters() {
    const panel = this.shadowRoot.getElementById("fpanel");
    if (!panel) return;
    const f = this._filters;
    const across = this._view === "across";
    const nodes = this._nodes || [];
    const mfr = listManufacturers(nodes);
    const known = new Set(mfr.map((m) => m.key));
    // a saved selection of a maker that is gone stays visible (and can be unticked)
    for (const k of f.manufacturers) if (!known.has(k)) mfr.push({ key: k, label: k || "Unknown", count: 0 });
    const body = panel.querySelector(".fbody");
    const scroll = body ? body.scrollTop : 0;
    const mlist = mfr.length
      ? mfr
          .map(
            (m) =>
              `<label class="frow"><input type="checkbox" data-mfr="${esc(m.key)}" ${f.manufacturers.includes(m.key) ? "checked" : ""}><span>${esc(m.label)} (${m.count})</span></label>`
          )
          .join("")
      : `<div class="fhint">No devices yet.</div>`;
    let html =
      `<div class="fhead"><h2 id="fp-title">Filters</h2><button id="fp-close" aria-label="Close filters" title="Close (Esc)">✕</button></div><div class="fbody">` +
      `<section><h3>Devices</h3><div class="fsub" id="fp-mfr-title">Manufacturer <span class="fhint">${f.manufacturers.length ? `${f.manufacturers.length} selected` : "all"}</span></div>` +
      `<div class="mlist" role="group" aria-labelledby="fp-mfr-title">${mlist}</div>`;
    if (!across) {
      html +=
        `<label class="fsel">Device<select data-f="device" class="${f.device ? "on" : ""}"><option value="">All devices</option>` +
        listDevices(nodes)
          .map((d) => `<option value="${esc(d.value)}" ${d.value === f.device ? "selected" : ""}>${esc(d.label)}</option>`)
          .join("") +
        `</select></label>`;
    }
    html += this._check("hideUnavailable", "Hide unavailable devices", "Hide devices that are not reachable") + `</section><section><h3>Attributes</h3>`;
    html += this._check("rwOnly", "R/W only", "Only attributes that can be written") + this._check("exposedOnly", "Exposed as entity", "Only attributes ticked as Add as entity");
    if (!across) {
      html +=
        this._check("hideGlobal", "Hide global attributes", "Hide attributeList, featureMap, clusterRevision … (ids from 0xFFF8)") +
        `<label class="fsel">Cluster<select data-f="cluster" class="${f.cluster ? "on" : ""}"><option value="">All clusters</option>` +
        listClusters(nodes)
          .map((c) => `<option value="${c.id}" ${String(c.id) === f.cluster ? "selected" : ""}>${esc(c.name)} (${c.id} · ${hex(c.id)})</option>`)
          .join("") +
        `</select></label>` +
        this._check("manufacturerOnly", "Vendor-specific clusters only", "Only manufacturer specific or unknown clusters and attributes") +
        `<div class="fhint indent">Clusters from 0xFC00, such as IKEA's 0x117C0001. Not the device maker above.</div>` +
        this._check("changedOnly", "Changed since opened", "Only attributes that got a live update since this page was opened");
    }
    html += `</section></div><div class="ffoot"><button data-clear ${activeFilterCount(f, this._viewFilterKeys()) ? "" : "disabled"} title="Reset all filters">Clear filters</button></div>`;
    panel.innerHTML = html;
    const nb = panel.querySelector(".fbody");
    if (nb) nb.scrollTop = scroll;
    const n = activeFilterCount(f, this._viewFilterKeys());
    const btn = this.shadowRoot.getElementById("filters-btn");
    btn.querySelector(".fl-n").textContent = n ? ` · ${n}` : "";
    btn.setAttribute("aria-label", n ? `Filters, ${n} active` : "Filters");
    btn.classList.toggle("has", n > 0);
    this._renderCount();
  }

  _openFilters(open) {
    const panel = this.shadowRoot.getElementById("fpanel");
    const btn = this.shadowRoot.getElementById("filters-btn");
    if (!panel || open === !panel.hidden) return;
    panel.hidden = !open;
    this._fopen = open;
    this.classList.toggle("fp-open", open);
    btn.setAttribute("aria-expanded", String(open));
    if (open) {
      this._renderFilters();
      panel.querySelector("#fp-close").focus();
    } else btn.focus();
  }

  /* Tab stays inside the open panel. */
  _trapTab(e) {
    const panel = this.shadowRoot.getElementById("fpanel");
    const items = [...panel.querySelectorAll("button:not([disabled]), input, select")];
    if (!items.length) return;
    const cur = this.shadowRoot.activeElement;
    const i = items.indexOf(cur);
    if (e.shiftKey && i <= 0) {
      e.preventDefault();
      items[items.length - 1].focus();
    } else if (!e.shiftKey && (i === -1 || i === items.length - 1)) {
      e.preventDefault();
      items[0].focus();
    }
  }

  _renderCount(result) {
    const el = this.shadowRoot.getElementById("count");
    if (!el) return;
    if (result) this._lastCount = result;
    const r = this._lastCount;
    el.textContent = r ? r.text : "";
  }

  // A failed action shows as a dismissible message above the tree; the tree stays.
  _showToast(message) {
    this._toast = message;
    const el = this.shadowRoot && this.shadowRoot.getElementById("toast");
    if (!el) return;
    el.textContent = message || "";
    el.hidden = !message;
    el.onclick = () => this._showToast(null);
    clearTimeout(this._toastTimer);
    if (message) this._toastTimer = setTimeout(() => this._showToast(null), 8000);
  }

  _renderStatus() {
    const el = this.shadowRoot && this.shadowRoot.getElementById("status");
    if (!el) return;
    const n = this._nodes ? this._nodes.length : 0;
    el.innerHTML = `${n} node${n === 1 ? "" : "s"} · <span class="${this._live ? "live" : "off"}">${this._disconnected ? "reconnecting…" : this._live ? "live" : "not live"}</span>`;
  }

  _renderMain() {
    const main = this.shadowRoot.getElementById("main");
    if (this._error) {
      main.innerHTML = `<div class="msg error">${esc(this._error)}</div>`;
    } else if (!this._nodes) {
      main.innerHTML = `<div class="msg">Loading…</div>`;
    } else if (this._view === "tree") {
      main.innerHTML = this._restoredHtml() + this._missingHtml() + this._treeHtml();
    } else if (this._view === "compare") {
      main.innerHTML = this._compareHtml();
    } else {
      main.innerHTML = this._acrossHtml();
    }
  }

  /* ---- values ---------------------------------------------------------- */

  /* ---- tree ------------------------------------------------------------ */

  /* ---- across ---------------------------------------------------------- */

  /* ---- bulk write ----------------------------------------------------- */

  /* ---- write dialog: edit -> confirm -> result --------------------------- */

  /* ---- clicks ---------------------------------------------------------- */

  _onClick(e) {
    const path = e.composedPath();
    const find = (attr) => path.find((el) => el.dataset && el.dataset[attr] !== undefined);
    if (path.some((el) => el.tagName === "DETAILS" || el.tagName === "SUMMARY")) return;
    const exp = find("export");
    if (exp) {
      this._exportDownload(Number(exp.dataset.export));
      return;
    }
    const cmp = find("compare");
    if (cmp) {
      this._setView("tree");
      return;
    }
    if (find("clearRestored")) {
      this._clearRestored();
      return;
    }
    const untick = find("untick");
    if (untick) {
      this._untickMissing(untick.dataset.untick);
      return;
    }
    const ident = find("identify");
    if (ident) {
      if (!ident.disabled) this._identify(ident.dataset.identify);
      return;
    }
    const edit = find("edit");
    if (edit) {
      const [nid, ...rest] = edit.dataset.edit.split("|");
      this._openEdit(Number(nid), rest.join("|"));
      return;
    }
    const bulk = find("bulk");
    if (bulk) {
      if (bulk.dataset.bulk === "open") this._bulkOpen();
      else this._bulkSelect(bulk.dataset.bulk);
      return;
    }
    const across = find("across");
    if (across) {
      this._pickAcross(across.dataset.across);
      return;
    }
    const preset = find("preset");
    if (preset) {
      this._pickAcross(preset.dataset.preset);
      return;
    }
    const toggle = find("toggle");
    if (toggle) {
      const k = toggle.dataset.toggle;
      if (this._filter || filtersNarrow(this._filters)) return; // while searching / filtering everything matching is shown open
      if (this._expanded.has(k)) this._expanded.delete(k);
      else this._expanded.add(k);
      this._renderMain();
      const again = this.shadowRoot.querySelector(`[data-toggle="${CSS.escape(k)}"]`);
      if (again && e.detail === 0) again.focus(); // keyboard activation: keep the place
    }
  }

}

Object.assign(
  MatterExplorerPanel.prototype,
  connectionMethods,
  treeMethods,
  acrossMethods,
  dialogsMethods,
  exportMethods,
);

customElements.define("matter-explorer-panel", MatterExplorerPanel);
