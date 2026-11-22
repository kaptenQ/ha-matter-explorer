/* Diagnostics export and compare. Pure helpers (tested in tests/js) plus panel methods.
 * Everything runs in the browser: the export comes from the backend (matter_explorer/export), a file to compare
 * with is read with FileReader and never uploaded. */

import { errText } from "./bulk.js";
import { esc, fmtScalar } from "./util.js";

export const MAX_DIFF_ROWS = 500;

/* matter-node-6-2026-11-20.json, matter-fabric-2026-11-20.json (date of the export, UTC) */
export function exportFileName(doc) {
  const day = String(doc.exported_at || "").slice(0, 10) || "undated";
  const what = doc.scope && doc.scope !== "fabric" ? `node-${doc.nodes && doc.nodes[0] ? doc.nodes[0].node_id : "x"}` : "fabric";
  return `matter-${what}-${day}.json`;
}

/* Throws an Error with a readable message if `doc` is not an export of this integration. */
export function checkExport(doc) {
  if (!doc || typeof doc !== "object" || !Array.isArray(doc.nodes) || typeof doc.format !== "number")
    throw new Error("This is not a Matter Explorer export file.");
  for (const n of doc.nodes)
    if (!n || typeof n.node_id !== "number" || !Array.isArray(n.attributes))
      throw new Error("The export file is damaged (a node has no attributes).");
  return doc;
}

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/* Differences from `before` (the file) to `after` (now). A file with one node is compared with that node only.
 * Returns [{ node_id, name, kind: added|removed|changed, path, attr, before, after }], nodes and paths in order;
 * a node that exists on one side only gives one row per attribute (kind added / removed). */
export function diffExports(before, after) {
  const scoped = before.scope && before.scope !== "fabric";
  const ids = new Set(before.nodes.map((n) => n.node_id));
  const now = scoped ? after.nodes.filter((n) => ids.has(n.node_id)) : after.nodes;
  const oldBy = new Map(before.nodes.map((n) => [n.node_id, n]));
  const newBy = new Map(now.map((n) => [n.node_id, n]));
  const rows = [];
  for (const id of [...new Set([...oldBy.keys(), ...newBy.keys()])].sort((a, b) => a - b)) {
    const o = oldBy.get(id);
    const n = newBy.get(id);
    const name = (n || o).name;
    const oa = new Map(((o && o.attributes) || []).map((a) => [a.path, a]));
    const na = new Map(((n && n.attributes) || []).map((a) => [a.path, a]));
    const paths = [...new Set([...oa.keys(), ...na.keys()])].sort((x, y) => {
      const p = x.split("/").map(Number);
      const q = y.split("/").map(Number);
      return p[0] - q[0] || p[1] - q[1] || p[2] - q[2];
    });
    for (const path of paths) {
      const x = oa.get(path);
      const y = na.get(path);
      const attr = y || x;
      const label = `${attr.cluster_name} / ${attr.name}`;
      if (x && !y) rows.push({ node_id: id, name, kind: "removed", path, attr: label, before: x, after: null });
      else if (!x && y) rows.push({ node_id: id, name, kind: "added", path, attr: label, before: null, after: y });
      else if (!same(x.value, y.value)) rows.push({ node_id: id, name, kind: "changed", path, attr: label, before: x, after: y });
    }
  }
  return rows;
}

export function showValue(a) {
  if (!a) return "";
  if (a.value !== null && typeof a.value === "object") return JSON.stringify(a.value);
  const raw = fmtScalar(a.value);
  const shown = a.display_value !== undefined && a.display_value !== null ? fmtScalar(a.display_value) : raw;
  return shown !== raw ? `${shown} (${raw})` : raw;
}

export const exportMethods = {
  /* Fetch the export from the backend and save it as a file. nodeId null = whole fabric. */
  async _exportDownload(nodeId) {
    this._showToast(null);
    try {
      const doc = await this._hass.callWS(
        nodeId === null || nodeId === undefined ? { type: "matter_explorer/export" } : { type: "matter_explorer/export", node_id: nodeId }
      );
      const blob = new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = exportFileName(doc);
      this.shadowRoot.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      this._lastExportName = a.download;
    } catch (err) {
      this._showToast(errText(err, "Export failed."));
    }
  },

  _exportButtonHtml(nodeId, label = "Export") {
    return `<button class="export" data-export="${nodeId}" title="Download this device as a JSON file">${label}</button>`;
  },

  /* "Compare…": pick an earlier export file, diff it against a fresh export, show the result. */
  async _compareFile(file) {
    this._showToast(null);
    try {
      const before = checkExport(JSON.parse(await file.text()));
      const after = await this._hass.callWS({ type: "matter_explorer/export" });
      this._compare = { file: file.name, before, after, rows: diffExports(before, after), device: "" };
      this._view = "compare";
      this._lastCount = null;
      this._render();
    } catch (err) {
      this._showToast(err instanceof SyntaxError ? "The file is not valid JSON." : errText(err, "Could not compare."));
    }
  },

  _compareHtml() {
    const c = this._compare;
    if (!c) return `<div class="empty">Choose an export file with “Compare…”.</div>`;
    const rows = c.device ? c.rows.filter((r) => String(r.node_id) === c.device) : c.rows;
    const counts = { added: 0, removed: 0, changed: 0 };
    for (const r of rows) counts[r.kind]++;
    const devices = [...new Map(c.rows.map((r) => [r.node_id, r.name])).entries()];
    this._renderCount({ text: `${rows.length} difference${rows.length === 1 ? "" : "s"}` });
    const shown = rows.slice(0, MAX_DIFF_ROWS);
    const body = shown
      .map(
        (r) =>
          `<tr class="diff-${r.kind}"><td><span class="badge">${r.kind}</span></td><td>${esc(r.name)} <span class="id">node ${r.node_id}</span></td><td>${esc(r.attr)} <span class="id">${esc(r.path)}</span></td><td class="val">${esc(showValue(r.before))}</td><td class="val">${esc(showValue(r.after))}</td></tr>`
      )
      .join("");
    return (
      `<h2>Compare with ${esc(c.file)}</h2>` +
      `<div class="picker"><button data-compare="close">Back</button>` +
      `<span class="hint">File: ${esc(c.before.exported_at || "?")} (integration ${esc(c.before.integration_version || "?")}) · now: ${esc(c.after.exported_at)} (${esc(c.after.integration_version)})</span>` +
      `<select data-cdev aria-label="Device"><option value="">All devices</option>${devices
        .map(([id, name]) => `<option value="${id}" ${String(id) === c.device ? "selected" : ""}>${esc(name)} (node ${id})</option>`)
        .join("")}</select></div>` +
      `<div class="hint" id="compare-summary">${counts.changed} changed · ${counts.added} added · ${counts.removed} removed</div>` +
      (rows.length
        ? `<div class="tablewrap"><table><thead><tr><th></th><th>Device</th><th>Attribute</th><th>Then</th><th>Now</th></tr></thead><tbody>${body}</tbody></table></div>` +
          (rows.length > shown.length ? `<div class="hint">Showing the first ${MAX_DIFF_ROWS} of ${rows.length}. Pick a device to narrow it down.</div>` : "")
        : `<div class="empty">No differences.</div>`)
    );
  },
};
