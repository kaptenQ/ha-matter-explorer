/* The tree view: clusters, attribute rows, "Add as entity" ticks, Identify.
 * Methods of <matter-explorer-panel>, mixed into its prototype by matter-explorer-panel.js (`this` is the panel). */

import { DEFAULT_FILTERS, hex, tokenize, filterNodes, resultSummary } from "./filters.js";
import { errText } from "./bulk.js";
import { esc, isStructured, fmtScalar } from "./util.js";

export const treeMethods = {
  /* Ticked "Add as entity" items whose node or attribute is gone, with an untick button each. */
  _missingHtml() {
    if (!this._missing || !this._missing.length) return "";
    const rows = this._missing
      .map(
        (m) =>
          `<div class="row" data-missing="${esc(`${m.node_id}|${m.path}`)}"><b>missing</b> node ${m.node_id} <code>${esc(m.path)}</code> <span class="why">(${esc(m.reason)})</span> <button data-untick="${esc(`${m.node_id}|${m.path}`)}">Untick</button></div>`
      )
      .join("");
    return `<div class="missing" id="missing"><div>${this._missing.length} ticked "Add as entity" item${this._missing.length === 1 ? " is" : "s are"} missing on the Matter side. Their entities stay unavailable until you untick them.</div>${rows}</div>`;
  },

  async _untickMissing(key) {
    const [nid, ...rest] = key.split("|");
    try {
      await this._hass.callWS({
        type: "matter_explorer/set_exposed",
        node_id: Number(nid),
        path: rest.join("|"),
        exposed: false,
      });
      this._missing = this._missing.filter((m) => `${m.node_id}|${m.path}` !== key);
    } catch (err) {
      this._showToast(errText(err, "Could not untick the item."));
    }
    this._render();
  },

  /* "Filters restored from last visit · Clear" above the tree, until the user changes search or filters. */
  _restoredHtml() {
    if (!this._restored) return "";
    return `<div class="restored" id="restored" role="status">Filters restored from last visit · <button class="link" data-clear-restored>Clear</button></div>`;
  },

  _clearRestored() {
    this._restored = false;
    this._filter = "";
    this.shadowRoot.getElementById("search").value = "";
    this._resetFilters();
  },

  /* One reset for the panel's "Clear filters" and the restored note's "Clear". */
  _resetFilters() {
    this._restored = false;
    this._filters = { ...DEFAULT_FILTERS };
    this._filtersChanged("");
  },

  _valueHtml(a) {
    const v = a.value;
    if (isStructured(v)) {
      const n = Array.isArray(v) ? `${v.length} item${v.length === 1 ? "" : "s"}` : `${Object.keys(v).length} fields`;
      return `<details><summary>${Array.isArray(v) ? "list" : "struct"}, ${n}</summary><pre>${esc(JSON.stringify(v, null, 2))}</pre></details>`;
    }
    const raw = fmtScalar(v);
    const shown = a.display_value !== undefined && a.display_value !== null ? fmtScalar(a.display_value) : raw;
    const unit = a.unit && shown !== raw ? ` ${esc(a.unit)}` : "";
    // Known enums: the friendly label, the spec name as tooltip
    const spec = a.meta && a.meta.enum_labels && a.meta.enum_values ? a.meta.enum_values[raw] : null;
    const label = spec && spec !== shown ? `<span title="${esc(spec)}">${esc(shown)}</span>` : esc(shown);
    return shown !== raw ? `${label}${unit} <span class="raw">(${esc(raw)})</span>` : label;
  },

  _treeHtml() {
    const tokens = tokenize(this._filter);
    const res = filterNodes(this._nodes, { tokens, filters: this._filters, changed: this._changed });
    const filtering = res.narrowed;
    this._renderCount({ text: resultSummary(res.attrCount, res.deviceCount) });
    const parts = [];
    for (const { node, endpoints } of res.nodes) {
      const nodeKey = `n${node.node_id}`;
      const epHtml = [];
      for (const { ep, clusters } of endpoints) {
        const epKey = `${nodeKey}/e${ep.endpoint_id}`;
        const clHtml = clusters.map(({ cl, attrs }) => {
          const clKey = `${epKey}/c${cl.cluster_id}`;
          return this._clusterHtml(node, cl, clKey, filtering ? true : this._expanded.has(clKey), attrs);
        });
        const open = filtering ? true : this._expanded.has(epKey);
        epHtml.push(
          `<div class="endpoint"><div class="row toggle" data-toggle="${epKey}" tabindex="0" role="button" aria-expanded="${open}"><span class="twist" aria-hidden="true">${open ? "▾" : "▸"}</span>Endpoint ${ep.endpoint_id}${ep.name ? ` <span class="epname">${esc(ep.name)}</span>` : ""} <span class="badge">${ep.clusters.length} cluster${ep.clusters.length === 1 ? "" : "s"}</span>${this._identifyHtml(node, ep.endpoint_id)}</div>` +
            (open ? `<div class="children">${clHtml.join("")}</div>` : "") +
            `</div>`
        );
      }
      const open = filtering ? true : this._expanded.has(nodeKey);
      parts.push(
        `<div class="node ${node.available ? "" : "unavailable"}"><div class="row toggle" data-toggle="${nodeKey}" tabindex="0" role="button" aria-expanded="${open}"><span class="twist" aria-hidden="true">${open ? "▾" : "▸"}</span><span class="name">${esc(node.name)}</span> <span class="id">node ${node.node_id}</span>` +
          `<span class="badge ${node.available ? "" : "warn"}">${node.available ? "available" : "unavailable"}</span>` +
          (node.product ? `<span class="badge">${esc(node.product)}</span>` : "") +
          (node.is_bridge ? `<span class="badge">bridge</span>` : "") +
          this._identifyHtml(node, this._identifyEndpoint(node, { clusters: [] })) +
          this._exportButtonHtml(node.node_id) +
          `</div>` +
          (open ? `<div class="children">${epHtml.join("")}</div>` : "") +
          `</div>`
      );
    }
    if (!parts.length) {
      return `<div class="empty">${filtering ? "Nothing matches the search and filters." : "No Matter nodes."}</div>`;
    }
    return parts.join("");
  },

  _clusterHtml(node, cl, key, open, attrs) {
    const rows = open ? attrs.map((a) => this._attrRowHtml(node, cl, a)).join("") : "";
    return (
      `<div class="cluster"><div class="row toggle" data-toggle="${key}" tabindex="0" role="button" aria-expanded="${open}"><span class="twist" aria-hidden="true">${open ? "▾" : "▸"}</span>${esc(cl.name)} <span class="id">${cl.cluster_id} · ${hex(cl.cluster_id)}</span>` +
      (cl.unknown ? `<span class="badge">unknown cluster</span>` : "") +
      `<span class="badge">${attrs.length}${attrs.length !== cl.attributes.length ? "/" + cl.attributes.length : ""} attributes</span></div>` +
      (open ? `<div class="children">${rows}</div>` : "") +
      `</div>`
    );
  },

  /* Identify button: endpoint must have the Identify cluster (3). */
  _identifyEndpoint(node, ep) {
    const has = (e) => e.clusters.some((c) => c.cluster_id === 3);
    if (has(ep)) return ep.endpoint_id;
    const other = node.endpoints.find((e) => e.endpoint_id !== 0 && has(e));
    return other ? other.endpoint_id : null;
  },

  _identifyHtml(node, endpointId) {
    if (endpointId === null || endpointId === undefined) return "";
    const ep = node.endpoints.find((e) => e.endpoint_id === endpointId);
    if (!ep || !ep.clusters.some((c) => c.cluster_id === 3)) return "";
    const key = `${node.node_id}|${endpointId}`;
    const busy = this._identifyBusy && this._identifyBusy.has(key);
    const off = busy || !node.available;
    return `<button class="identify" data-identify="${key}" title="Make the device blink or beep for 15 seconds" ${off ? "disabled" : ""}>${busy ? "Identifying…" : "Identify"}</button>`;
  },

  async _identify(key) {
    const [nid, ep] = key.split("|").map(Number);
    this._identifyBusy = this._identifyBusy || new Set();
    this._identifyBusy.add(key);
    this._showToast(null);
    this._render();
    try {
      await this._hass.callWS({ type: "matter_explorer/identify", node_id: nid, endpoint_id: ep, identify_time: 15 });
      await new Promise((r) => setTimeout(r, 15000));
    } catch (err) {
      this._showToast(errText(err, "Identify failed."));
    }
    this._identifyBusy.delete(key);
    this._render();
  },

  /* "Add as entity" checkbox (+ the entity_id once the entity exists). */
  _exposeHtml(node, a) {
    const e = a.entity;
    if (!e) return "";
    const key = `${node.node_id}|${esc(a.path)}`;
    const busy = this._exposeBusy && this._exposeBusy.has(key) ? "disabled" : "";
    const title = e.platform ? `Becomes a ${e.platform} entity` : "Not available as an entity";
    return (
      `<span class="expose-wrap"><label class="expose" title="${esc(title)}"><input type="checkbox" data-expose="${key}" ${e.exposed ? "checked" : ""} ${busy}> Add as entity</label>` +
      (e.entity_id ? `<div class="entity-id">${esc(e.entity_id)}</div>` : "") +
      `</span>`
    );
  },

  async _toggleExpose(key, checked) {
    const [nid, ...rest] = key.split("|");
    const path = rest.join("|");
    this._exposeBusy = this._exposeBusy || new Set();
    this._exposeBusy.add(key);
    this._showToast(null);
    try {
      const res = await this._hass.callWS({
        type: "matter_explorer/set_exposed",
        node_id: Number(nid),
        path,
        exposed: checked,
      });
      const node = this._nodes.find((n) => n.node_id === Number(nid));
      for (const e of node ? node.endpoints : [])
        for (const c of e.clusters)
          for (const a of c.attributes)
            if (a.path === path && a.entity) {
              a.entity.exposed = res.exposed;
              a.entity.entity_id = res.entity_id;
            }
    } catch (err) {
      this._showToast(errText(err, "Could not change the entity."));
    }
    this._exposeBusy.delete(key);
    this._render();
  },

  _attrRowHtml(node, cl, a) {
    const w = this._isWritable(node, a);
    return (
      `<div class="attr"><div class="aname">${esc(a.name)} <span class="id">${a.attribute_id}</span></div>` +
      `<div class="type">${esc(a.type)}</div>` +
      `<div class="val" data-vk="${node.node_id}:${esc(a.path)}">${this._valueHtml(a)}</div>` +
      `<span class="brk b1"></span><div class="id apath">${esc(a.path)}</div>` +
      `<div class="rw ${w ? "w" : ""}" title="${w ? "Writable" : "Read-only"}"><span class="rwl">${w ? "R/W" : "R"}</span>${w && node.available ? `<button class="edit" title="Edit this value" data-edit="${node.node_id}|${esc(a.path)}">Edit</button>` : ""}</div>` +
      `<span class="brk b2"></span><button class="link" title="Same attribute across all devices" data-across="${cl.cluster_id}/${a.attribute_id}">⇄</button>` +
      `${this._exposeHtml(node, a)}</div>`
    );
  },

  _expandAll(open) {
    this._expanded.clear();
    if (open) {
      for (const n of this._nodes || []) {
        this._expanded.add(`n${n.node_id}`);
        for (const e of n.endpoints) {
          this._expanded.add(`n${n.node_id}/e${e.endpoint_id}`);
          for (const c of e.clusters) this._expanded.add(`n${n.node_id}/e${e.endpoint_id}/c${c.cluster_id}`);
        }
      }
    }
    this._renderMain();
  },
};
