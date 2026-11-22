/* Pure logic of the bulk write in the across view (no DOM). Tested with node:test. */

/* Why a row cannot be ticked, or null when it can. `a.write` is the backend's writable table entry. */
export function rowBlock(node, a) {
  if (!a.write) return "not writable";
  if (!node.available) return "unavailable";
  return null;
}

/* Rows that can be ticked, as "nodeId:path" keys. */
export function selectableKeys(rows) {
  return rows.filter(({ node, a }) => !rowBlock(node, a)).map(({ node, a }) => `${node.node_id}:${a.path}`);
}

/* Why this node's own limits refuse `value`, or null. Mirrors the backend's validate_value. */
export function valueBlock(w, value) {
  if (w.type === "bool") return typeof value === "boolean" ? null : "out of range";
  if (!Number.isInteger(value)) return "out of range";
  if (w.type === "enum") return w.values && w.values[String(value)] !== undefined ? null : "out of range";
  if (w.min === null || w.min === undefined || w.max === null || w.max === undefined) return "out of range";
  return value >= w.min && value <= w.max ? null : "out of range";
}

/* Plan for ticked rows (plus, with includeBlocked, the rows that cannot be ticked, as skipped) and one value: [{row, action: "write"|"no_change"|"skipped", reason, old}] (old = value when planned) in row order. */
export function planBulk(rows, selected, value, includeBlocked = false) {
  const plan = [];
  for (const row of rows) {
    const key = `${row.node.node_id}:${row.a.path}`;
    const blocked = rowBlock(row.node, row.a);
    if (!selected.has(key) && !(includeBlocked && blocked)) continue;
    const reason = blocked || valueBlock(row.a.write, value);
    if (reason) plan.push({ row, action: "skipped", reason, old: row.a.value });
    else if (row.a.value === value) plan.push({ row, action: "no_change", reason: null, old: row.a.value });
    else plan.push({ row, action: "write", reason: null, old: row.a.value });
  }
  return plan;
}

export const writeItems = (plan) =>
  plan.filter((p) => p.action === "write").map((p) => ({ node_id: p.row.node.node_id, path: p.row.a.path }));

/* Outcome label of one result: ok -> "match", mismatch, timeout, error, skipped, no_change -> "no change". */
export const OUTCOME_LABEL = {
  ok: "match", mismatch: "mismatch", timeout: "timeout", error: "error", skipped: "skipped", no_change: "no change",
};

/* Results that "Retry failed" writes again: mismatch, timeout and error. */
export const failedItems = (results) =>
  results.filter((r) => ["mismatch", "timeout", "error"].includes(r.status)).map((r) => ({ node_id: r.node_id, path: r.path }));

/* Text of a failed websocket call. home-assistant-js-websocket rejects with {code: 3} (ERR_CONNECTION_LOST) and no message when the socket drops. */
export function errText(err, fallback) {
  if (err && err.message) return err.message;
  if (err && err.code === 3) return "Connection to Home Assistant lost. Check the value, then try again.";
  return fallback;
}

/* Banner/dialog text for a bulk write that lost its connection: `done` of `total` writes were reported before the drop. */
export const lostSummary = (done, total) => `Connection lost: ${done} of ${total} done, check values.`;

/* Whether a bulk dialog stage is still waiting for the backend. */
export const isRunning = (dlg) => !!(dlg && dlg.bulk && dlg.stage === "running");
