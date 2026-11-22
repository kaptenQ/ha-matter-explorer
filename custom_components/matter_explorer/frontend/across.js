/* The across view: one attribute on all devices, and the bulk write bar.
 * Methods of <matter-explorer-panel>, mixed into its prototype by matter-explorer-panel.js (`this` is the panel). */

import { acrossRows } from "./filters.js";
import { rowBlock, selectableKeys } from "./bulk.js";
import { PRESETS, esc } from "./util.js";

export const acrossMethods = {
  _attributeIndex() {
    const idx = new Map();
    for (const n of this._nodes || [])
      for (const e of n.endpoints)
        for (const c of e.clusters)
          for (const a of c.attributes) {
            const k = `${c.cluster_id}/${a.attribute_id}`;
            if (!idx.has(k)) idx.set(k, { cluster: c.cluster_id, attribute: a.attribute_id, cname: c.name, aname: a.name });
          }
    return [...idx.values()];
  },

  _resolveAcross(commit) {
    const text = this._acrossInput.trim();
    this._candidates = [];
    const m = text.match(/^(0x[0-9a-f]+|\d+)\s*\/\s*(0x[0-9a-f]+|\d+)$/i);
    if (m) {
      this._across = { cluster: Number(m[1]), attribute: Number(m[2]) };
    } else if (text) {
      const t = text.toLowerCase().replace(/\s+/g, "");
      this._candidates = this._attributeIndex()
        .filter((i) => `${i.cname}/${i.aname}`.toLowerCase().includes(t) || i.aname.toLowerCase().includes(t))
        .slice(0, 30);
      if (this._candidates.length === 1 || (commit && this._candidates.length)) {
        const c = this._candidates[0];
        this._across = { cluster: c.cluster, attribute: c.attribute };
        if (this._candidates.length === 1) this._candidates = [];
      }
    }
    this._renderAcrossResults();
  },

  _acrossHtml() {
    return `<h2>Same attribute across all devices</h2>
      <div class="picker">
        ${PRESETS.map((p) => `<button data-preset="${p.cluster}/${p.attribute}" class="${this._across && this._across.cluster === p.cluster && this._across.attribute === p.attribute ? "active" : ""}">${esc(p.label)}</button>`).join("")}
        <input id="across-input" type="text" placeholder="cluster/attr (516/1) or name (KeypadLockout)" aria-label="Cluster and attribute" value="${esc(this._acrossInput)}" autocomplete="off">
      </div>
      <div id="across-results">${this._acrossResultsHtml()}</div>`;
  },

  _renderAcrossResults() {
    const el = this.shadowRoot.getElementById("across-results");
    if (el) el.innerHTML = this._acrossResultsHtml();
  },

  _acrossResultsHtml() {
    let out = "";
    if (this._candidates && this._candidates.length) {
      out += `<div class="cands">${this._candidates
        .map((c) => `<button data-preset="${c.cluster}/${c.attribute}">${esc(c.cname)}/${esc(c.aname)} <span class="id">${c.cluster}/${c.attribute}</span></button>`)
        .join("")}</div>`;
    }
    if (!this._across) return out + `<div class="empty">Pick an attribute, or use ⇄ on a row in the tree.</div>`;
    const { cluster, attribute } = this._across;
    const rows = [];
    let title = `${cluster}/${attribute}`;
    const found = acrossRows(this._nodes, cluster, attribute, this._filters);
    this._rows = found;
    const bulkKey = `${cluster}/${attribute}`;
    if (!this._bulk || this._bulk.key !== bulkKey) this._bulk = { key: bulkKey, selected: new Set(), value: undefined };
    const selectable = new Set(selectableKeys(found));
    for (const k of [...this._bulk.selected]) if (!selectable.has(k)) this._bulk.selected.delete(k);
    this._renderCount({ text: `${found.length} row${found.length === 1 ? "" : "s"}` });
    for (const { node: n, ep: e, cl: c, a } of found) {
      title = `${c.name} / ${a.name} (${cluster}/${attribute})`;
      const block = rowBlock(n, a);
      const sk = `${n.node_id}:${a.path}`;
      const first = block
        ? `<td class="sel"></td>`
        : `<td class="sel"><input type="checkbox" data-sel="${esc(sk)}" aria-label="Select ${esc(n.name)}" ${this._bulk.selected.has(sk) ? "checked" : ""}></td>`;
      rows.push(
        `<tr class="${n.available ? "" : "unavailable"}">${first}<td>${esc(n.name)} <span class="id">node ${n.node_id}</span> ${this._exportButtonHtml(n.node_id)}</td><td>${e.endpoint_id}</td>` +
          `<td class="val" data-vk="${n.node_id}:${esc(a.path)}">${this._valueHtml(a)}</td><td class="type">${esc(a.type)}</td>` +
          `<td><span class="badge ${n.available ? "" : "warn"}">${n.available ? "available" : "unavailable"}</span></td><td>${this._identifyHtml(n, this._identifyEndpoint(n, e))}${this._exposeHtml(n, a)}${block ? ` <span class="why">${esc(block)}</span>` : ""}</td></tr>`
      );
    }
    out += `<h2>${esc(title)}</h2>`;
    if (!rows.length) return out + `<div class="empty">No device has this attribute.</div>`;
    return (
      out +
      this._bulkBarHtml(found, selectable) +
      `<div class="tablewrap"><table><thead><tr><th></th><th>Device</th><th>Endpoint</th><th>Value</th><th>Type</th><th>Availability</th><th>Entity</th></tr></thead><tbody>${rows.join("")}</tbody></table></div>`
    );
  },

  /* Editor spec for the bulk value: the first writable row's table entry; int limits widened to all
   * ticked-able rows (each node is validated against its own limits when planning). */
  _bulkSpec(rows) {
    const w = rows.find(({ node, a }) => !rowBlock(node, a));
    if (!w) return null;
    const spec = { ...w.a.write };
    if (spec.type === "int") {
      for (const { node, a } of rows) {
        if (rowBlock(node, a) || a.write.min === null) continue;
        spec.min = Math.min(spec.min, a.write.min);
        spec.max = Math.max(spec.max, a.write.max);
      }
    }
    return { name: w.a.name, write: spec, value: w.a.value };
  },

  _bulkBarHtml(found, selectable) {
    if (!selectable.size) return "";
    const spec = this._bulkSpec(found);
    const value = this._bulk.value === undefined ? spec.value : this._bulk.value;
    const n = this._bulk.selected.size;
    return `<div class="bulk" id="bulkbar">
      <button data-bulk="all">Select all writable (${selectable.size})</button><button data-bulk="none">Select none</button>
      <span class="ctl" style="margin:0">${this._controlHtml({ entry: spec, value }, "bulk-ctl")}</span>
      <button class="active" data-bulk="open" id="bulk-open" ${n ? "" : "disabled"}>Set selected to…</button>
      <span class="hint" id="bulk-count">${n} selected</span></div>`;
  },

  _bulkUpdateBar() {
    const n = this._bulk.selected.size;
    const c = this.shadowRoot.getElementById("bulk-count");
    if (c) c.textContent = `${n} selected`;
    const b = this.shadowRoot.getElementById("bulk-open");
    if (b) b.disabled = !n;
  },

  _bulkSelect(which) {
    this._bulk.selected = which === "all" ? new Set(selectableKeys(this._rows)) : new Set();
    this._renderAcrossResults();
  },

  _bulkOpen() {
    const spec = this._bulkSpec(this._rows);
    if (!spec || !this._bulk.selected.size) return;
    const value = this._readControl({ entry: spec }, "bulk-ctl");
    if (typeof value === "number" && !Number.isFinite(value)) return this._showToast("Enter a number first.");
    this._bulk.value = value;
    this._startBulkDialog(value, spec, new Set(this._bulk.selected), true);
  },

  _pickAcross(key) {
    const [cluster, attribute] = key.split("/").map(Number);
    this._across = { cluster, attribute };
    this._acrossInput = key;
    this._candidates = [];
    this._view = "across";
    this._lastCount = null;
    this._render();
  },
};
