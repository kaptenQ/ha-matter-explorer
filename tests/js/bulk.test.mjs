import test from "node:test";
import assert from "node:assert/strict";
import {
  failedItems, planBulk, rowBlock, selectableKeys, valueBlock, writeItems,
} from "../../custom_components/matter_explorer/frontend/bulk.js";

const enumW = { type: "enum", values: { 0: "Off", 1: "Level 1", 2: "Level 2" } };
const intW = (min, max) => ({ type: "int", min, max, unit: "°C" });
const row = (id, over = {}, a = {}) => ({
  node: { node_id: id, name: `n${id}`, available: true, ...over },
  a: { path: "1/516/1", value: 0, write: enumW, ...a },
});

test("rowBlock gives the reason", () => {
  assert.equal(rowBlock(row(1).node, row(1).a), null);
  assert.equal(rowBlock({ available: false }, { write: enumW }), "unavailable");
  assert.equal(rowBlock({ available: true }, { write: null }), "not writable");
});

test("selectableKeys leaves out blocked rows", () => {
  const rows = [row(1), row(2, { available: false }), row(3, {}, { write: null })];
  assert.deepEqual(selectableKeys(rows), ["1:1/516/1"]);
});

test("valueBlock per attribute type and per node limits", () => {
  assert.equal(valueBlock(enumW, 2), null);
  assert.equal(valueBlock(enumW, 9), "out of range");
  assert.equal(valueBlock({ type: "bool" }, true), null);
  assert.equal(valueBlock({ type: "bool" }, 1), "out of range");
  assert.equal(valueBlock(intW(500, 3000), 2400), null);
  assert.equal(valueBlock(intW(500, 2000), 2400), "out of range");
  assert.equal(valueBlock(intW(null, null), 2400), "out of range");
  assert.equal(valueBlock(intW(0, 10), 1.5), "out of range");
});

test("planBulk: write, no change, skipped, only ticked rows", () => {
  const rows = [row(1), row(2, {}, { value: 2 }), row(3, { available: false }), row(4, {}, { write: intW(0, 1) }), row(5)];
  const sel = new Set(["1:1/516/1", "2:1/516/1", "3:1/516/1", "4:1/516/1"]);
  const plan = planBulk(rows, sel, 2);
  assert.deepEqual(plan.map((p) => [p.row.node.node_id, p.action, p.reason]), [
    [1, "write", null], [2, "no_change", null], [3, "skipped", "unavailable"], [4, "skipped", "out of range"],
  ]);
  assert.deepEqual(plan.map((p) => p.old), [0, 2, 0, 0]);
  assert.deepEqual(writeItems(plan), [{ node_id: 1, path: "1/516/1" }]);
});

test("failedItems keeps mismatch, timeout and error only", () => {
  const r = (status, node_id) => ({ node_id, path: "p", status });
  assert.deepEqual(
    failedItems([r("ok", 1), r("mismatch", 2), r("timeout", 3), r("error", 4), r("skipped", 5), r("no_change", 6)]).map((x) => x.node_id),
    [2, 3, 4]
  );
});

test("planBulk with includeBlocked lists unticked blocked rows as skipped", () => {
  const rows = [row(1), row(2, { available: false }), row(3, {}, { write: null })];
  const plan = planBulk(rows, new Set(["1:1/516/1"]), 2, true);
  assert.deepEqual(plan.map((p) => [p.row.node.node_id, p.action, p.reason]), [
    [1, "write", null], [2, "skipped", "unavailable"], [3, "skipped", "not writable"],
  ]);
  assert.equal(planBulk(rows, new Set(["1:1/516/1"]), 2).length, 1);
});

import { errText, isRunning, lostSummary } from "../../custom_components/matter_explorer/frontend/bulk.js";

test("lostSummary and errText", () => {
  assert.equal(lostSummary(3, 12), "Connection lost: 3 of 12 done, check values.");
  assert.equal(errText({ message: "Node 6 didn't answer within 30 s" }, "x"), "Node 6 didn't answer within 30 s");
  assert.match(errText({ code: 3 }, "x"), /Connection to Home Assistant lost/);
  assert.equal(errText(undefined, "fallback"), "fallback");
});

test("isRunning only for a running bulk dialog", () => {
  assert.equal(isRunning({ bulk: true, stage: "running" }), true);
  assert.equal(isRunning({ bulk: true, stage: "result" }), false);
  assert.equal(isRunning({ stage: "running" }), false);
  assert.equal(isRunning(null), false);
});
