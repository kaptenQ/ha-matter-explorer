/* Pure filter / search logic of the Matter Explorer panel. No DOM, no HA: unit-tested with `node --test`
 * (tests/js/filters.test.mjs). The panel imports this as a plain ES module. */

export const GLOBAL_ATTRIBUTE_MIN = 0xfff8; // attributeList, featureMap, clusterRevision, ...
export const MANUFACTURER_CLUSTER_MIN = 0xfc00; // manufacturer specific cluster id range
export const STORAGE_KEY = "matter_explorer.view";

export const DEFAULT_FILTERS = Object.freeze({
  rwOnly: false,
  exposedOnly: false,
  hideUnavailable: false,
  hideGlobal: true,
  manufacturerOnly: false,
  changedOnly: false,
  manufacturers: [], // selected manufacturer keys (see vendorKey), [] = all; "" is Unknown
  device: "", // node id as string, "" = all
  cluster: "", // cluster id as string, "" = all
});

/* Filters the across view understands. */
export const ACROSS_FILTER_KEYS = ["hideUnavailable", "rwOnly", "exposedOnly", "manufacturers"];

/* Number of filters that are set (the badge on the Filters button): hide-global counts only when switched off; `keys` limits it to the filters a view has. */
export function activeFilterCount(f, keys = Object.keys(DEFAULT_FILTERS)) {
  return keys.filter((k) => !sameValue(f[k], DEFAULT_FILTERS[k])).length;
}

/* ---- manufacturers ---- */
export const UNKNOWN_VENDOR = ""; // key of the "Unknown" entry

const label = (name, id) => {
  const n = typeof name === "string" ? name.trim() : "";
  if (n) return n;
  return typeof id === "number" ? `Vendor ${"0x" + id.toString(16).toUpperCase().padStart(4, "0")}` : null;
};

/* Manufacturer of a node: VendorName (0/40/1), else "Vendor 0x1234" from VendorID, else null (Unknown). */
export const nodeVendor = (node) => label(node.vendor, node.vendor_id);

/* Manufacturer of an endpoint: a bridged device's own (cluster 57), else the node's. null = Unknown. */
export function endpointVendor(node, ep) {
  return label(ep.bridged_vendor, ep.bridged_vendor_id) || nodeVendor(node);
}

const vendorKey = (v) => (v === null ? UNKNOWN_VENDOR : v);

/* Manufacturer entries with the number of devices (nodes, plus bridged devices that report their own maker):
 * [{key, label, count}] sorted by name, Unknown last (only if present). */
export function listManufacturers(nodes) {
  const counts = new Map();
  const add = (v) => counts.set(vendorKey(v), (counts.get(vendorKey(v)) || 0) + 1);
  for (const n of nodes || []) {
    add(nodeVendor(n));
    for (const e of n.endpoints || []) if (label(e.bridged_vendor, e.bridged_vendor_id)) add(endpointVendor(n, e));
  }
  const known = [...counts].filter(([k]) => k !== UNKNOWN_VENDOR).map(([key, count]) => ({ key, label: key, count }));
  known.sort((a, b) => a.label.localeCompare(b.label));
  if (counts.has(UNKNOWN_VENDOR)) known.push({ key: UNKNOWN_VENDOR, label: "Unknown", count: counts.get(UNKNOWN_VENDOR) });
  return known;
}

const vendorPasses = (f, node, ep) => !f.manufacturers.length || f.manufacturers.includes(vendorKey(endpointVendor(node, ep)));

export const hex = (n) => "0x" + Number(n).toString(16).toUpperCase().padStart(4, "0");
export const idText = (id) => `${id} ${hex(id).toLowerCase()} 0x${Number(id).toString(16)}`;

/* Everyday names people search for; the Matter name is KeypadLockout for the IKEA "child lock". */
export const ALIASES = Object.freeze({ "516/1": "child lock childlock keypad lock" });
export const aliasText = (cl, a) => ALIASES[`${cl.cluster_id}/${a.attribute_id}`] || "";

export const tokenize = (text) => String(text || "").toLowerCase().split(/\s+/).filter(Boolean);

export function normalizeFilters(raw) {
  const out = { ...DEFAULT_FILTERS };
  if (!raw || typeof raw !== "object") return out;
  for (const [k, def] of Object.entries(DEFAULT_FILTERS)) {
    if (Array.isArray(def)) {
      if (Array.isArray(raw[k])) out[k] = raw[k].filter((x) => typeof x === "string");
    } else if (typeof raw[k] === typeof def) out[k] = raw[k];
  }
  return out;
}

const sameValue = (a, b) => (Array.isArray(a) ? Array.isArray(b) && a.length === b.length && a.every((x, i) => x === b[i]) : a === b);

/* Differs from the defaults at all (shows "Clear filters"). */
export function filtersChanged(f) {
  return Object.keys(DEFAULT_FILTERS).some((k) => !sameValue(f[k], DEFAULT_FILTERS[k]));
}

/* A filter that narrows the result beyond the quiet default (the tree opens fully, empty parents drop out). */
export function filtersNarrow(f) {
  return Object.keys(DEFAULT_FILTERS).some((k) => k !== "hideGlobal" && !sameValue(f[k], DEFAULT_FILTERS[k]));
}

export const isGlobalAttribute = (a) => a.attribute_id >= GLOBAL_ATTRIBUTE_MIN && a.attribute_id <= 0xffff;
export const isManufacturerCluster = (cl) => !!cl.unknown || cl.cluster_id >= MANUFACTURER_CLUSTER_MIN;
export const isManufacturerAttribute = (a) => a.attribute_id > 0xffff; // vendor-prefixed id

export const changedKey = (nodeId, path) => `${nodeId}:${path}`;

/* Filters that only look at one attribute row; shared by tree and across view. */
export function rowPasses(f, node, a) {
  if (f.hideUnavailable && !node.available) return false;
  if (f.rwOnly && !a.write) return false;
  if (f.exposedOnly && !(a.entity && a.entity.exposed)) return false;
  return true;
}

function attrPasses(f, node, cl, a, changed) {
  if (!rowPasses(f, node, a)) return false;
  if (f.hideGlobal && isGlobalAttribute(a)) return false;
  if (f.manufacturerOnly && !isManufacturerCluster(cl) && !isManufacturerAttribute(a)) return false;
  if (f.changedOnly && !(changed && changed.has(changedKey(node.node_id, a.path)))) return false;
  return true;
}

function valueText(a) {
  return [JSON.stringify(a.value), a.display_value === undefined ? "" : String(a.display_value)].join(" ").toLowerCase();
}

/* Apply search tokens (AND) and filters (AND) to the node list.
 * Returns {nodes: [{node, endpoints: [{ep, clusters: [{cl, attrs}]}]}], attrCount, deviceCount, narrowed}. */
export function filterNodes(nodes, { tokens = [], filters = DEFAULT_FILTERS, changed = null } = {}) {
  const f = filters;
  const searching = tokens.length > 0;
  const narrow = filtersNarrow(f);
  const prune = searching || narrow;
  const matchesAll = (text) => tokens.every((t) => text.includes(t));
  const out = [];
  let attrCount = 0;
  for (const node of nodes || []) {
    const [devNode, devEp] = String(f.device).split(":"); // "5" = a node, "5:2" = one bridged endpoint
    if (f.device && String(node.node_id) !== devNode) continue;
    if (f.hideUnavailable && !node.available) continue;
    if (f.manufacturers.length && node.endpoints.length && !node.endpoints.some((ep) => vendorPasses(f, node, ep))) continue;
    if (f.manufacturers.length && !node.endpoints.length && !f.manufacturers.includes(vendorKey(nodeVendor(node)))) continue;
    const nodeText = `${node.name} ${node.node_id} ${node.product || ""} ${node.vendor || ""}`.toLowerCase();
    const nodeMatch = searching && matchesAll(nodeText);
    const endpoints = [];
    for (const ep of node.endpoints) {
      if (!vendorPasses(f, node, ep)) continue;
      if (devEp !== undefined && String(ep.endpoint_id) !== devEp) continue;
      const epText = ep.name ? ` ${ep.name}` : ""; // bridged device name
      const clusters = [];
      for (const cl of ep.clusters) {
        if (f.cluster && String(cl.cluster_id) !== f.cluster) continue;
        const clText = `${cl.name} ${idText(cl.cluster_id)}${epText}`.toLowerCase();
        const clMatch = searching && matchesAll(`${nodeText} ${clText}`);
        let attrs = cl.attributes.filter((a) => attrPasses(f, node, cl, a, changed));
        if (searching && !nodeMatch && !clMatch) {
          attrs = attrs.filter((a) =>
            matchesAll(`${nodeText} ${clText} ${a.name} ${aliasText(cl, a)} ${idText(a.attribute_id)} ${a.path} ${valueText(a)}`.toLowerCase())
          );
        }
        if (prune && !attrs.length) continue;
        clusters.push({ cl, attrs });
      }
      if (prune && !clusters.length) continue;
      endpoints.push({ ep, clusters });
    }
    if (prune && !endpoints.length && !(nodeMatch && !narrow && !node.endpoints.length)) continue;
    for (const e of endpoints) for (const c of e.clusters) attrCount += c.attrs.length;
    out.push({ node, endpoints });
  }
  return { nodes: out, attrCount, deviceCount: out.length, narrowed: prune };
}

/* Rows of the across view after the row filters. */
export function acrossRows(nodes, cluster, attribute, filters) {
  const rows = [];
  for (const node of nodes || []) {
    for (const ep of node.endpoints) {
      const cl = ep.clusters.find((x) => x.cluster_id === cluster);
      const a = cl && cl.attributes.find((x) => x.attribute_id === attribute);
      if (a && rowPasses(filters, node, a) && vendorPasses(filters, node, ep)) rows.push({ node, ep, cl, a });
    }
  }
  return rows;
}

/* Device filter entries: every node, plus an indented entry per bridged endpoint that has a name.
 * [{value: "5" | "5:2", label, node: bool}] */
export function listDevices(nodes) {
  const out = [];
  for (const n of nodes || []) {
    out.push({ value: String(n.node_id), label: `${n.name} (node ${n.node_id})`, node: true });
    for (const e of n.endpoints) {
      if (e.name) out.push({ value: `${n.node_id}:${e.endpoint_id}`, label: `↳ ${e.name} (node ${n.node_id} · endpoint ${e.endpoint_id})`, node: false });
    }
  }
  return out;
}

/* Whether the saved search/filters differ from a fresh start (the "restored" note is shown). */
export const hasRestored = (prefs) => !!prefs.search || filtersChanged(prefs.filters);

/* Distinct clusters present, for the Cluster select: [{id, name}] sorted by name. */
export function listClusters(nodes) {
  const seen = new Map();
  for (const n of nodes || [])
    for (const e of n.endpoints) for (const c of e.clusters) if (!seen.has(c.cluster_id)) seen.set(c.cluster_id, c.name);
  return [...seen].map(([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name) || a.id - b.id);
}

export function resultSummary(attrCount, deviceCount) {
  return `${attrCount} attribute${attrCount === 1 ? "" : "s"} on ${deviceCount} device${deviceCount === 1 ? "" : "s"}`;
}

/* ---- persistence (localStorage may be missing or throw: the panel works without it) ---- */

export function loadPrefs(storage) {
  const prefs = { filters: { ...DEFAULT_FILTERS }, search: "" };
  try {
    const raw = JSON.parse(storage.getItem(STORAGE_KEY));
    if (raw && typeof raw === "object") {
      prefs.filters = normalizeFilters(raw.filters);
      if (typeof raw.search === "string") prefs.search = raw.search;
    }
  } catch (_e) {
    /* no storage, or garbage in it */
  }
  return prefs;
}

export function savePrefs(storage, prefs) {
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify({ filters: prefs.filters, search: prefs.search }));
    return true;
  } catch (_e) {
    return false;
  }
}
