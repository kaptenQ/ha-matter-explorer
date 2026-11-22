/* Dialogs: the single-attribute edit dialog and the bulk write dialog (with keyboard handling).
 * Methods of <matter-explorer-panel>, mixed into its prototype by matter-explorer-panel.js (`this` is the panel). */

import { acrossRows } from "./filters.js";
import { planBulk, writeItems, OUTCOME_LABEL, failedItems, errText } from "./bulk.js";
import { esc, fmtScalar } from "./util.js";

export const dialogsMethods = {
  _startBulkDialog(value, spec, selected, includeBlocked = false) {
    const plan = planBulk(this._rows, selected, value, includeBlocked);
    this._dlg = { bulk: true, stage: "confirm", value, spec, plan, progress: null, results: null, error: null, busy: false };
    this._renderDialog();
  },

  _bulkFmt(d, v) {
    return this._fmtWrite({ write: d.spec.write }, v);
  },

  _bulkTable(d, outcome) {
    const body = d.plan
      .map((p) => {
        const { node, ep, a } = p.row;
        let change = `${esc(this._bulkFmt(d, p.old))} → <b>${esc(this._bulkFmt(d, d.value))}</b>`;
        let cls = "";
        let text = "";
        if (p.action === "skipped") [cls, text] = ["o-skip", `skipped: ${p.reason}`];
        else if (p.action === "no_change") [cls, text] = ["o-skip", "no change"];
        if (outcome) {
          const r = outcome.get(`${node.node_id}:${a.path}`);
          if (r) {
            const rb = r.timeout ? "no read-back" : this._bulkFmt(d, r.read_back);
            [cls, text] = [r.status === "ok" ? "o-ok" : "o-bad", `${OUTCOME_LABEL[r.status]}${r.status === "ok" ? "" : r.error ? `: ${r.error}` : ""} (device: ${rb})`];
          }
        }
        if (p.action !== "write") change = `${esc(this._bulkFmt(d, p.old))}`;
        return `<tr><td>${esc(node.name)} <span class="id">node ${node.node_id}</span></td><td>${ep.endpoint_id}</td><td class="val">${change}</td><td class="${cls}">${esc(text)}</td></tr>`;
      })
      .join("");
    return `<table><thead><tr><th>Device</th><th>Endpoint</th><th>Old → new</th><th>${outcome ? "Outcome" : "Note"}</th></tr></thead><tbody>${body}</tbody></table>`;
  },

  _bulkDialogHtml() {
    const d = this._dlg;
    const name = d.spec.name;
    const nWrite = writeItems(d.plan).length;
    const err = d.error ? `<div class="result bad">${esc(d.error)}</div>` : "";
    if (d.stage === "confirm") {
      return `<h3>Confirm: set ${esc(name)} to ${esc(this._bulkFmt(d, d.value))}</h3>${this._bulkTable(d, null)}
        <div class="warn">This writes to ${nWrite} real device${nWrite === 1 ? "" : "s"}, one after the other. It changes their behaviour immediately.</div>${err}
        <div class="actions"><button data-dlg="cancel">Cancel</button>
        <button class="danger" data-dlg="bulk-confirm" ${nWrite ? "" : "disabled"}>${nWrite ? `Write to ${nWrite} device${nWrite === 1 ? "" : "s"}` : "Nothing to write"}</button></div>`;
    }
    if (d.stage === "running") {
      const pr = d.progress || { done: 0, total: nWrite };
      return `<h3>Writing ${esc(name)}…</h3><div class="result ok" id="progress">${pr.done} / ${pr.total}</div>
        <div class="hint">Writes are sent one by one with a short pause between them.</div>`;
    }
    if (d.stage === "lost") {
      return `<h3>Writing ${esc(name)}</h3><div class="result bad" id="lost">${esc(d.lost)}</div>
        <div class="hint">${this._disconnected ? "Reconnecting…" : "Reconnected, the rows were refreshed."} Some writes may have reached devices; compare the values before writing again.</div>
        <div class="actions"><button class="active" data-dlg="close">Close</button></div>`;
    }
    const outcome = new Map(d.results.map((r) => [`${r.node_id}:${r.path}`, r]));
    const counts = {};
    for (const r of d.results) counts[r.status] = (counts[r.status] || 0) + 1;
    const summary = Object.entries(counts).map(([k, n]) => `${n} ${OUTCOME_LABEL[k]}`).join(", ");
    const failed = failedItems(d.results).length;
    return `<h3>Write result: ${esc(name)} = ${esc(this._bulkFmt(d, d.value))}</h3>
      <div class="result ${failed ? "bad" : "ok"}" id="result">${esc(summary || "Nothing was written")}</div>${this._bulkTable(d, outcome)}
      <div class="actions">${failed ? `<button data-dlg="bulk-retry">Retry failed (${failed})</button>` : ""}<button class="active" data-dlg="close">Close</button></div>`;
  },

  async _bulkRun() {
    const d = this._dlg;
    const items = writeItems(d.plan);
    d.stage = "running";
    d.busy = true;
    d.error = null;
    d.progress = { done: 0, total: items.length };
    this._renderDialog();
    let unsub = null;
    const finish = (results) => {
      if (unsub) unsub();
      d.results = results;
      d.busy = false;
      d.stage = "result";
      this._renderDialog();
    };
    try {
      unsub = await this._hass.connection.subscribeMessage(
        (ev) => {
          if (this._dlg !== d) return;
          if (ev.event === "progress") {
            d.progress = { done: ev.done, total: ev.total };
            const el = this.shadowRoot.getElementById("progress");
            if (el) el.textContent = `${ev.done} / ${ev.total}`;
          } else if (ev.event === "done") finish(ev.results);
        },
        { type: "matter_explorer/write_many", items, value: d.value },
        { resubscribe: false } // a reconnect must never repeat the writes
      );
      d.unsub = unsub;
      if (d.stage === "result") unsub();
    } catch (err) {
      d.busy = false;
      d.stage = "confirm";
      d.error = errText(err, "Bulk write refused.");
      this._renderDialog();
    }
  },

  _bulkRetry() {
    const d = this._dlg;
    const failed = new Set(failedItems(d.results).map((r) => `${r.node_id}:${r.path}`));
    this._rows = acrossRows(this._nodes, this._across.cluster, this._across.attribute, {});
    this._startBulkDialog(d.value, d.spec, failed);
  },

  _openEdit(nodeId, path) {
    const node = this._node(nodeId);
    const entry = node && this._attrByPath(node, path);
    if (!entry || !entry.write) return;
    const [ep, cl] = path.split("/").map(Number);
    const cluster = node.endpoints.find((e) => e.endpoint_id === ep).clusters.find((c) => c.cluster_id === cl);
    this._dlg = { node, entry, ep, cluster, stage: "edit", value: entry.value, newValue: null, result: null, error: null };
    this._renderDialog();
  },

  _closeDialog() {
    this._dlg = null;
    this._renderDialog();
  },

  _fmtWrite(entry, v) {
    const w = entry.write;
    if (v === null || v === undefined) return "null";
    const label = (w.labels && w.labels[String(v)]) || (w.values && w.values[String(v)]);
    if (label) return `${label} (${v})`;
    if (w.unit === "°C" && typeof v === "number") return `${(v / 100).toFixed(2)} °C (${v})`;
    return fmtScalar(v);
  },

  _controlHtml(d, id = "ctl") {
    const w = d.entry.write;
    if (w.type === "enum") {
      return `<select id="${id}">${Object.entries(w.values)
        .map(([k, label]) => `<option value="${esc(k)}" title="${esc(label)}" ${Number(k) === d.value ? "selected" : ""}>${esc((w.labels && w.labels[k]) || label)} (${esc(k)})</option>`)
        .join("")}</select>`;
    }
    if (w.type === "bool") {
      return `<label><input id="${id}" type="checkbox" ${d.value ? "checked" : ""}> ${esc(d.entry.name)}</label>`;
    }
    if (w.unit === "°C") {
      return `<input id="${id}" type="number" step="0.01" min="${w.min / 100}" max="${w.max / 100}" value="${d.value / 100}"> °C
        <span class="hint">allowed ${w.min / 100} – ${w.max / 100} °C</span>`;
    }
    return `<input id="${id}" type="number" step="1" min="${w.min}" max="${w.max}" value="${esc(d.value)}">
      <span class="hint">allowed ${w.min} – ${w.max}</span>`;
  },

  _readControl(d, id = "ctl") {
    const w = d.entry.write;
    const el = this.shadowRoot.getElementById(id);
    if (w.type === "bool") return el.checked;
    if (w.type === "enum") return Number(el.value);
    if (el.value.trim() === "" || !Number.isFinite(Number(el.value))) return NaN;
    const n = Number(el.value);
    return w.unit === "°C" ? Math.round(n * 100) : n;
  },

  _dialogHtml() {
    if (this._dlg.bulk) return this._bulkDialogHtml();
    const d = this._dlg;
    const w = d.entry.write;
    const head = `<dl><dt>Device</dt><dd>${esc(d.node.name)} (node ${d.node.node_id})</dd>
      <dt>Endpoint</dt><dd>${d.ep}</dd>
      <dt>Attribute</dt><dd>${esc(d.cluster.name)} / ${esc(d.entry.name)} (${esc(d.entry.path)})</dd></dl>`;
    const err = d.error ? `<div class="result bad">${esc(d.error)}</div>` : "";
    if (d.stage === "edit") {
      return `<h3>Edit ${esc(d.entry.name)}</h3>${head}
        <div class="ctl">${this._controlHtml(d)}</div>${err}
        <div class="hint">Current value: ${esc(this._fmtWrite(d.entry, d.entry.value))}</div>
        <div class="actions"><button data-dlg="cancel">Cancel</button><button class="active" data-dlg="save">Save…</button></div>`;
    }
    if (d.stage === "confirm") {
      return `<h3>Confirm write</h3>${head}
        <dl><dt>Change</dt><dd>${esc(this._fmtWrite(d.entry, d.entry.value))} → <b>${esc(this._fmtWrite(d.entry, d.newValue))}</b></dd></dl>
        <div class="warn">This writes to the real device. It changes the device's behaviour immediately.</div>${err}
        <div class="actions"><button data-dlg="back" ${d.busy ? "disabled" : ""}>Back</button>
        <button class="danger" data-dlg="confirm" ${d.busy ? "disabled" : ""}>${d.busy ? "Writing…" : "Write to device"}</button></div>`;
    }
    const r = d.result;
    const [cls, text] = r.timeout
      ? ["bad", "Written, but the read-back timed out: the value was not confirmed."]
      : r.matches
        ? ["ok", `Match: the device reports ${this._fmtWrite(d.entry, r.read_back)}.`]
        : ["bad", `Mismatch: wrote ${this._fmtWrite(d.entry, r.written)}, the device reports ${this._fmtWrite(d.entry, r.read_back)}.`];
    return `<h3>Write result</h3>${head}<div class="result ${cls}" id="result">${esc(text)}</div>
      <div class="actions"><button class="active" data-dlg="close">Close</button></div>`;
    void w;
  },

  _renderDialog() {
    let host = this.shadowRoot.getElementById("dlg");
    if (!this._dlg) {
      if (host) host.remove();
      const back = this._returnFocus;
      this._returnFocus = null;
      if (host && back && back.isConnected) back.focus();
      return;
    }
    if (!host) {
      host = document.createElement("div");
      host.id = "dlg";
      host.className = "overlay";
      host.addEventListener("click", (e) => {
        const b = e.composedPath().find((el) => el.dataset && el.dataset.dlg);
        if (b) this._onDialogClick(b.dataset.dlg);
      });
      host.addEventListener("keydown", (e) => this._onDialogKey(e, host));
      this.shadowRoot.appendChild(host);
      this._returnFocus = this.shadowRoot.activeElement;
    }
    host.innerHTML = `<div class="dialog${this._dlg.bulk ? " wide" : ""}" role="dialog" aria-modal="true" aria-labelledby="dlg-title">${this._dialogHtml()}</div>`;
    const title = host.querySelector("h3");
    if (title) title.id = "dlg-title";
    if (!host.contains(this.shadowRoot.activeElement)) {
      const first = host.querySelector("#ctl, #bulk-ctl") || host.querySelector("button.danger:not([disabled]), button.active") || host.querySelector("button");
      if (first) first.focus();
    }
  },

  /* Escape closes (not while a write is in flight), Tab stays inside the dialog. */
  _onDialogKey(e, host) {
    const d = this._dlg;
    if (!d) return;
    if (e.key === "Escape") {
      if (d.busy || d.stage === "running") return;
      e.preventDefault();
      e.stopPropagation();
      this._closeDialog();
    } else if (e.key === "Tab") {
      const items = [...host.querySelectorAll("button:not([disabled]), input, select")];
      if (!items.length) return;
      const at = items.indexOf(this.shadowRoot.activeElement);
      const next = e.shiftKey ? (at <= 0 ? items.length - 1 : at - 1) : at === items.length - 1 ? 0 : at + 1;
      e.preventDefault();
      items[next].focus();
    }
  },

  async _onDialogClick(action) {
    const d = this._dlg;
    if (!d || d.busy) return;
    if (action === "cancel" || action === "close") return this._closeDialog();
    if (action === "bulk-confirm") return this._bulkRun();
    if (action === "bulk-retry") return this._bulkRetry();
    if (action === "back") {
      d.stage = "edit";
      d.error = null;
      d.value = d.newValue;
      return this._renderDialog();
    }
    if (action === "save") {
      const v = this._readControl(d);
      const w = d.entry.write;
      d.error = null;
      if (typeof v === "number" && (!Number.isFinite(v) || (w.type === "int" && (v < w.min || v > w.max)))) {
        d.error = "Value is outside the allowed range.";
        d.value = d.entry.value;
      } else if (v === d.entry.value) {
        d.error = "The value is unchanged.";
      } else {
        d.newValue = v;
        d.stage = "confirm";
      }
      return this._renderDialog();
    }
    if (action === "confirm") {
      d.busy = true;
      d.error = null;
      this._renderDialog();
      try {
        d.result = await this._hass.callWS({
          type: "matter_explorer/write",
          node_id: d.node.node_id,
          path: d.entry.path,
          value: d.newValue,
        });
        d.stage = "result";
      } catch (err) {
        d.error = errText(err, "Write refused.");
      }
      d.busy = false;
      this._renderDialog();
    }
  },
};
