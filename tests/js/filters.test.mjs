import test from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_FILTERS, STORAGE_KEY, activeFilterCount, listManufacturers, UNKNOWN_VENDOR, ALIASES, acrossRows, changedKey, filterNodes, filtersChanged, filtersNarrow,
  listClusters, listDevices, hasRestored, loadPrefs, normalizeFilters, resultSummary, savePrefs, tokenize,
} from "../../custom_components/matter_explorer/frontend/filters.js";

const attr = (id, name, extra = {}) => ({
  attribute_id: id, name, path: `X/${id}`, value: 1, type: "uint", write: null, entity: null, ...extra,
});
const mk = (cid, name, attrs, extra = {}) => ({ cluster_id: cid, name, attributes: attrs, ...extra });
const NODES = [
  {
    node_id: 1, name: "Thermostat", available: true, product: "LILJEBAGGE", endpoints: [
      { endpoint_id: 0, clusters: [mk(40, "BasicInformation", [attr(5, "NodeLabel", { write: { type: "str" } }), attr(0xfffd, "ClusterRevision")])] },
      { endpoint_id: 1, clusters: [
        mk(513, "Thermostat", [attr(0, "LocalTemperature", { value: 2150 }), attr(18, "HeatSetpoint", { write: { type: "int" }, entity: { exposed: true } }), attr(0xfffc, "FeatureMap")]),
        mk(0x117c0001, "Vendor", [attr(1, "Secret")], { unknown: true }),
      ] },
    ],
  },
  { node_id: 2, name: "Lamp", available: false, endpoints: [
    { endpoint_id: 1, clusters: [mk(6, "OnOff", [attr(0, "OnOff", { write: { type: "bool" } })])] },
  ] },
];
const run = (filters = {}, extra = {}) => filterNodes(NODES, { filters: { ...DEFAULT_FILTERS, ...filters }, ...extra });
const names = (r) => r.nodes.flatMap((n) => n.endpoints.flatMap((e) => e.clusters.flatMap((c) => c.attrs.map((a) => a.name))));

test("defaults hide global attributes only", () => {
  assert.deepEqual(names(run()), ["NodeLabel", "LocalTemperature", "HeatSetpoint", "Secret", "OnOff"]);
  assert.equal(filtersChanged(DEFAULT_FILTERS), false);
  assert.equal(filtersNarrow(DEFAULT_FILTERS), false);
  assert.equal(filtersNarrow({ ...DEFAULT_FILTERS, hideGlobal: false }), false);
  assert.equal(filtersChanged({ ...DEFAULT_FILTERS, hideGlobal: false }), true);
});

test("global attributes show when the filter is off", () => {
  assert.equal(names(run({ hideGlobal: false })).length, 7);
});

test("R/W only", () => {
  assert.deepEqual(names(run({ rwOnly: true })), ["NodeLabel", "HeatSetpoint", "OnOff"]);
});

test("exposed only", () => assert.deepEqual(names(run({ exposedOnly: true })), ["HeatSetpoint"]));

test("hide unavailable devices", () => {
  const r = run({ hideUnavailable: true });
  assert.equal(r.deviceCount, 1);
  assert.ok(!names(r).includes("OnOff"));
});

test("hide endpoint 0 is gone: no such filter, dropped from stored state", () => {
  assert.ok(!("hideRoot" in DEFAULT_FILTERS));
  assert.ok(names(run({ hideRoot: true })).includes("NodeLabel"));
  assert.ok(!("hideRoot" in normalizeFilters({ hideRoot: true, rwOnly: true })));
  assert.equal(normalizeFilters({ hideRoot: true }).rwOnly, false);
});

test("manufacturer / unknown only", () => assert.deepEqual(names(run({ manufacturerOnly: true })), ["Secret"]));

test("manufacturer attribute id in a standard cluster counts", () => {
  const nodes = [{ node_id: 3, name: "N", available: true, endpoints: [{ endpoint_id: 1, clusters: [mk(6, "OnOff", [attr(0, "OnOff"), attr(0x10001, "Vendor")])] }] }];
  const r = filterNodes(nodes, { filters: { ...DEFAULT_FILTERS, manufacturerOnly: true } });
  assert.equal(r.attrCount, 1);
});

test("device and cluster selects", () => {
  assert.equal(run({ device: "2" }).deviceCount, 1);
  assert.deepEqual(names(run({ cluster: "513" })), ["LocalTemperature", "HeatSetpoint"]);
  assert.equal(run({ device: "99" }).deviceCount, 0);
});

test("changed since opened", () => {
  const changed = new Set([changedKey(1, "X/0")]);
  assert.deepEqual(names(run({ changedOnly: true }, { changed })), ["LocalTemperature"]);
  assert.equal(run({ changedOnly: true }).attrCount, 0);
});

test("filters combine with search (AND) and keep parents", () => {
  const r = run({ rwOnly: true }, { tokens: tokenize("setpoint") });
  assert.deepEqual(names(r), ["HeatSetpoint"]);
  assert.equal(r.nodes[0].endpoints[0].ep.endpoint_id, 1);
  assert.deepEqual(names(run({ rwOnly: true }, { tokens: tokenize("thermostat") })), ["NodeLabel", "HeatSetpoint"]);
  assert.deepEqual(names(run({}, { tokens: tokenize("0x117c0001") })), ["Secret"]);
  assert.deepEqual(names(run({}, { tokens: tokenize("2150") })), ["LocalTemperature"]);
});

test("counts and summary", () => {
  const r = run({ rwOnly: true });
  assert.equal(r.attrCount, 3);
  assert.equal(r.deviceCount, 2);
  assert.equal(resultSummary(1, 1), "1 attribute on 1 device");
  assert.equal(resultSummary(123, 9), "123 attributes on 9 devices");
});

test("across rows honour the row filters", () => {
  assert.equal(acrossRows(NODES, 6, 0, DEFAULT_FILTERS).length, 1);
  assert.equal(acrossRows(NODES, 6, 0, { ...DEFAULT_FILTERS, hideUnavailable: true }).length, 0);
  assert.equal(acrossRows(NODES, 513, 0, { ...DEFAULT_FILTERS, rwOnly: true }).length, 0);
  assert.equal(acrossRows(NODES, 513, 18, { ...DEFAULT_FILTERS, exposedOnly: true }).length, 1);
});

test("cluster list is distinct and sorted by name", () => {
  const l = listClusters(NODES);
  assert.deepEqual(l.map((c) => c.name), ["BasicInformation", "OnOff", "Thermostat", "Vendor"]);
});

test("prefs round trip and survive a broken or missing storage", () => {
  const mem = new Map();
  const storage = { getItem: (k) => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v) };
  assert.equal(savePrefs(storage, { filters: { ...DEFAULT_FILTERS, rwOnly: true }, search: "abc" }), true);
  assert.deepEqual(loadPrefs(storage), { filters: { ...DEFAULT_FILTERS, rwOnly: true }, search: "abc" });
  mem.set(STORAGE_KEY, "{not json");
  assert.deepEqual(loadPrefs(storage), { filters: DEFAULT_FILTERS, search: "" });
  mem.set(STORAGE_KEY, JSON.stringify({ filters: { rwOnly: "yes", device: 5, hideRoot: true, manufacturers: ["A", 3] }, search: 3 }));
  assert.deepEqual(loadPrefs(storage).filters, { ...DEFAULT_FILTERS, manufacturers: ["A"] });
  const throwing = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); } };
  assert.deepEqual(loadPrefs(throwing), { filters: DEFAULT_FILTERS, search: "" });
  assert.equal(savePrefs(throwing, { filters: DEFAULT_FILTERS, search: "" }), false);
  assert.deepEqual(loadPrefs(null), { filters: DEFAULT_FILTERS, search: "" });
  assert.equal(savePrefs(null, { filters: DEFAULT_FILTERS, search: "" }), false);
  assert.deepEqual(normalizeFilters(null), DEFAULT_FILTERS);
});

test("search finds the child lock (KeypadLockout, 516/1) by its everyday name", () => {
  const nodes = [{ node_id: 5, name: "Radiator", available: true, endpoints: [
    { endpoint_id: 1, clusters: [mk(516, "ThermostatUserInterfaceConfiguration", [attr(1, "KeypadLockout"), attr(0, "TemperatureDisplayMode")])] },
  ] }];
  const r = filterNodes(nodes, { tokens: tokenize("child lock"), filters: DEFAULT_FILTERS });
  assert.deepEqual(names(r), ["KeypadLockout"]);
  assert.ok(ALIASES["516/1"]);
  assert.deepEqual(names(filterNodes(nodes, { tokens: tokenize("childlock"), filters: DEFAULT_FILTERS })), ["KeypadLockout"]);
});

const BRIDGE = [
  { node_id: 5, name: "Bridge", available: true, endpoints: [
    { endpoint_id: 0, name: null, clusters: [mk(40, "BasicInformation", [attr(5, "NodeLabel")])] },
    { endpoint_id: 2, name: "Kitchen lamp", clusters: [mk(6, "OnOff", [attr(0, "OnOff")])] },
    { endpoint_id: 3, name: "Hall sensor", clusters: [mk(6, "OnOff", [attr(0, "OnOff")])] },
  ] },
];

test("bridged device names are searchable", () => {
  const r = filterNodes(BRIDGE, { tokens: tokenize("kitchen") });
  assert.deepEqual(r.nodes[0].endpoints.map((e) => e.ep.endpoint_id), [2]);
  assert.equal(filterNodes(BRIDGE, { tokens: tokenize("nothing") }).nodes.length, 0);
});

test("device filter: node, or one bridged endpoint", () => {
  assert.deepEqual(listDevices(BRIDGE).map((d) => d.value), ["5", "5:2", "5:3"]);
  assert.match(listDevices(BRIDGE)[1].label, /Kitchen lamp/);
  const one = filterNodes(BRIDGE, { filters: { ...DEFAULT_FILTERS, device: "5:3" } });
  assert.deepEqual(one.nodes[0].endpoints.map((e) => e.ep.endpoint_id), [3]);
  assert.equal(filterNodes(BRIDGE, { filters: { ...DEFAULT_FILTERS, device: "5" } }).nodes[0].endpoints.length, 3);
  assert.equal(filterNodes(BRIDGE, { filters: { ...DEFAULT_FILTERS, device: "6:2" } }).nodes.length, 0);
});

test("hasRestored: only when search or filters differ from a fresh start", () => {
  assert.equal(hasRestored({ search: "", filters: { ...DEFAULT_FILTERS } }), false);
  assert.equal(hasRestored({ search: "lock", filters: { ...DEFAULT_FILTERS } }), true);
  assert.equal(hasRestored({ search: "", filters: { ...DEFAULT_FILTERS, rwOnly: true } }), true);
});

const MK = (id, name, vendor, vendor_id, eps = []) => ({
  node_id: id, name, available: true, vendor, vendor_id,
  endpoints: [{ endpoint_id: 0, clusters: [mk(40, "BasicInformation", [attr(1, "VendorName")])] }, ...eps],
});
const bridged = (id, name, extra = {}) => ({ endpoint_id: id, name, clusters: [mk(6, "OnOff", [attr(0, "OnOff")])], ...extra });
const FLEET = [
  MK(1, "Radiator", "IKEA of Sweden", 4476),
  MK(2, "Light", "IKEA of Sweden", 4476),
  MK(3, "Plug", null, 4999),
  MK(4, "Mystery", null, undefined),
  MK(5, "Bridge", "Bridge Co", 1, [
    bridged(1, "Lamp", { bridged_vendor: "Lamp Maker" }),
    bridged(2, "Sensor", { bridged_vendor_id: 0x1234 }),
    bridged(3, "Plain"),
  ]),
];
const owners = (r) => r.nodes.map((n) => `${n.node.node_id}:${n.endpoints.map((e) => e.ep.endpoint_id).join(",")}`);
const byMfr = (manufacturers) => filterNodes(FLEET, { filters: { ...DEFAULT_FILTERS, manufacturers } });

test("manufacturer list: counts, id fallback, bridged makers, Unknown last", () => {
  assert.deepEqual(listManufacturers(FLEET).map((m) => [m.label, m.count]), [
    ["Bridge Co", 1], ["IKEA of Sweden", 2], ["Lamp Maker", 1], ["Vendor 0x1234", 1], ["Vendor 0x1387", 1], ["Unknown", 1],
  ]);
  assert.equal(listManufacturers(FLEET).at(-1).key, UNKNOWN_VENDOR);
  assert.deepEqual(listManufacturers([]), []);
  assert.ok(!listManufacturers([FLEET[0]]).some((m) => m.label === "Unknown"));
});

test("manufacturer filter: nothing selected means all", () => {
  assert.equal(byMfr([]).deviceCount, 5);
});

test("manufacturer filter: one maker, multi-select, Unknown", () => {
  assert.deepEqual(owners(byMfr(["IKEA of Sweden"])), ["1:0", "2:0"]);
  assert.deepEqual(owners(byMfr(["IKEA of Sweden", "Vendor 0x1387"])), ["1:0", "2:0", "3:0"]);
  assert.deepEqual(owners(byMfr([UNKNOWN_VENDOR])), ["4:0"]);
  assert.deepEqual(owners(byMfr(["Nobody"])), []);
});

test("manufacturer filter: bridged device uses its own maker, else the bridge's", () => {
  assert.deepEqual(owners(byMfr(["Lamp Maker"])), ["5:1"]);
  assert.deepEqual(owners(byMfr(["Vendor 0x1234"])), ["5:2"]);
  assert.deepEqual(owners(byMfr(["Bridge Co"])), ["5:0,3"]); // root and the bridged device without a maker
});

test("manufacturer filter applies to the across view", () => {
  const rows = (m) => acrossRows(FLEET, 6, 0, { ...DEFAULT_FILTERS, manufacturers: m });
  assert.equal(rows([]).length, 3);
  assert.deepEqual(rows(["Lamp Maker"]).map((r) => r.ep.endpoint_id), [1]);
  assert.equal(rows(["IKEA of Sweden"]).length, 0);
});

test("manufacturer selection counts as one active filter and clears by default compare", () => {
  const f = { ...DEFAULT_FILTERS, manufacturers: ["A", "B"] };
  assert.equal(activeFilterCount(DEFAULT_FILTERS), 0);
  assert.equal(activeFilterCount(f), 1);
  assert.equal(activeFilterCount({ ...f, rwOnly: true, hideGlobal: false }), 3);
  assert.equal(activeFilterCount({ ...f, changedOnly: true }, ["manufacturers", "rwOnly"]), 1);
  assert.equal(filtersChanged(f), true);
  assert.equal(filtersNarrow(f), true);
  assert.equal(filtersChanged({ ...DEFAULT_FILTERS, manufacturers: [] }), false);
});
