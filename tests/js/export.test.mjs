import test from "node:test";
import assert from "node:assert/strict";
import {
  checkExport, diffExports, exportFileName, showValue,
} from "../../custom_components/matter_explorer/frontend/export.js";

const attr = (path, value, name = "A", display = value) => ({
  path, name, cluster_name: "C", value, display_value: display,
});
const doc = (nodes, over = {}) => ({ format: 1, exported_at: "2026-11-20T10:00:00+00:00", scope: "fabric", nodes, ...over });
const node = (id, attributes, name = `n${id}`) => ({ node_id: id, name, attributes });

test("file names", () => {
  assert.equal(exportFileName(doc([node(6, [])], { scope: "node 6" })), "matter-node-6-2026-11-20.json");
  assert.equal(exportFileName(doc([])), "matter-fabric-2026-11-20.json");
});

test("checkExport rejects other JSON", () => {
  assert.throws(() => checkExport({}), /not a Matter Explorer/);
  assert.throws(() => checkExport(doc([{ node_id: 1 }])), /damaged/);
  assert.ok(checkExport(doc([])));
});

test("diff: changed, added, removed, unchanged ignored", () => {
  const before = doc([node(1, [attr("1/6/0", false), attr("1/6/1", 5), attr("1/6/2", [1, 2])])]);
  const after = doc([node(1, [attr("1/6/0", true), attr("1/6/2", [1, 2]), attr("1/6/3", 9)])]);
  const rows = diffExports(before, after);
  assert.deepEqual(rows.map((r) => [r.kind, r.path]), [["changed", "1/6/0"], ["removed", "1/6/1"], ["added", "1/6/3"]]);
});

test("diff: whole nodes added/removed; a one-node file only compares that node", () => {
  const before = doc([node(1, [attr("0/1/0", 1)]), node(2, [attr("0/1/0", 1)])]);
  const after = doc([node(1, [attr("0/1/0", 1)]), node(3, [attr("0/1/0", 1)])]);
  assert.deepEqual(diffExports(before, after).map((r) => [r.node_id, r.kind]), [[2, "removed"], [3, "added"]]);
  const one = doc([node(1, [attr("0/1/0", 0)])], { scope: "node 1" });
  assert.deepEqual(diffExports(one, after).map((r) => [r.node_id, r.kind]), [[1, "changed"]]);
});

test("diff: paths sort numerically, structs compare by content", () => {
  const before = doc([node(1, [attr("1/6/10", { a: 1 }), attr("1/6/9", 1)])]);
  const after = doc([node(1, [attr("1/6/10", { a: 2 }), attr("1/6/9", 2)])]);
  assert.deepEqual(diffExports(before, after).map((r) => r.path), ["1/6/9", "1/6/10"]);
});

test("showValue", () => {
  assert.equal(showValue(attr("1/1/1", 1, "A", "Lockout1")), "Lockout1 (1)");
  assert.equal(showValue(attr("1/1/1", [1])), "[1]");
  assert.equal(showValue(null), "");
});
