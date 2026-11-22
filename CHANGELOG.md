# Changelog

## 1.0.1

- Brand icon and logo (`custom_components/matter_explorer/brand/`), so HACS shows an icon and its brands check passes;
  the icon is also in the README header.
- Fix: with the filters side panel open, the "Add as entity" label in the tree was cut off. The attribute grid now
  shrinks (names and paths wrap), and when the tree gets narrow it switches to the card layout.

## 1.0.0

First public release. No behaviour change since 0.10.0 except the version.
- Everything from the earlier versions: a sidebar panel that browses every attribute of every Matter node (device →
  endpoint → cluster → attribute) with live updates, search, filters, a *same attribute across devices* view and a
  phone card layout; friendly enum labels; export and compare; Identify; diagnostics and repairs.
- Safe writes through one gate with a spec-based table (child lock, display mode, setpoints, system mode, …),
  confirm dialog, read-back, bulk write; unknown and manufacturer clusters are never written.
- "Add as entity": switch, select, number, sensor and binary sensor entities on the existing Matter device.
- Filters moved into a side panel: one **Filters** button (with a badge of the active filters) next to the search
  box opens a panel from the right (a sheet on a phone; Esc closes it, focus stays inside, the tree updates live,
  **Clear filters** at the bottom), grouped Devices / Attributes. The result count stays in the header.
- New **Manufacturer** filter: multi-select with a count per maker (VendorName 0/40/1, else `Vendor 0x1234` from
  VendorID; a bridged device uses its own maker, else the bridge's; **Unknown** last). Applies to the tree and the
  across view. The nodes payload gains `vendor_id` and per endpoint `bridged_vendor` / `bridged_vendor_id`.
- "Manufacturer / unknown only" is now **Vendor-specific clusters only** (with a hint: it is about clusters such as
  0x117C0001, not the device maker). **Hide endpoint 0** is removed (a saved setting is dropped quietly).
- Public repository: MIT license, README with screenshots, HACS metadata, `CONTRIBUTING.md`, issue templates,
  redacted test fixtures (`tests/fixtures/README.md`), lab settings through environment variables and an example
  `lab/docker-compose.example.yml`.

## 0.10.0

Playtest leftovers (#10-#15 in `docs/PLAYTEST.md`).
- Friendly enum labels from one backend table (`metadata.FRIENDLY_LABELS`, also used by the select entities):
  Child lock (516/1) reads Off / Level 1 … Level 5, Temperature display mode (516/0) Celsius / Fahrenheit,
  System mode (513/28) Off / Auto / Cool / Heat …. Shown in the tree, across view, edit, bulk and confirm dialogs and
  the exports' display value; the spec name (`Lockout1`) is the tooltip. Writes stay numeric. The 513/28 select
  entity options now use the friendly labels too ("Emergency heat" instead of "EmergencyHeat").
- Phone (below 600 px): each attribute is a card (name and value, then path/type/R/W, then Edit, ⇄ and Add as
  entity as 40 px touch targets). The desktop grid is unchanged.
- Bridge endpoints show the bridged device's name (Bridged Device Basic Information NodeLabel, else ProductName);
  it is searchable and each named endpoint is an entry in the Device filter. `endpoints[].name` in
  `matter_explorer/nodes`.
- New explorer entities are named "<attribute> (Explorer)", so their entity ids no longer collide with the matter
  integration's (`_2`). Existing entities keep their entity_id (only the name text changes).
- "Filters restored from last visit · Clear" note above the tree when saved search/filters were restored on open.
  Escape in the search box clears it.

## 0.9.0

Diagnostics export and compare (read-only).
- `matter_explorer/export` (admin only): one JSON document with export time, integration version, server info and
  per node its id, name, vendor, product, availability and every attribute (path, names, raw and display value), for
  one node or the whole fabric. Built from the same tree as `matter_explorer/nodes`.
- Panel: "Export" per device (tree and across view) and "Export fabric" download `matter-node-6-2026-11-20.json` /
  `matter-fabric-2026-11-20.json`.
- Panel: "Compare…" loads an earlier export file and lists changed, added and removed attributes against now,
  filterable by device. The file is read in the browser and never uploaded.
- `docs/PRESETS.md`: research note on Matter 1.4 presets/schedules (no code).

## 0.8.2

Internal cleanup, no behaviour change.
- The panel (1264 lines) is split into ES modules without a build step: `connection.js`, `tree.js`, `across.js`,
  `dialogs.js`, `styles.js`, `util.js` next to `filters.js` and `bulk.js`. The panel's module URL carries `?v=<version>`.
- One `run_device_call` (timeout, client errors, activity log) and one `find_node` for the write gate, the command
  gate, the entities and the exposure code.
- Stricter checks: ruff (SIM, RET, PL, RUF, N added) and mypy on `custom_components/` in `scripts/test.sh`.
- Lab scripts merged: `scripts/lab/e2e.py <scenario>` and `scripts/lab/screenshots.py <scenario>`.

## 0.8.1

Fixes from the panel playtest (`docs/PLAYTEST.md`).
- Search finds the child lock: "child lock" / "childlock" match KeypadLockout (516/1).
- Keyboard: tree rows (node, endpoint, cluster) are focusable and open with Enter or Space; dialogs take focus,
  close with Escape (not while writing), keep Tab inside and give focus back; dialogs have an accessible name.
- Identify button on the node row (no need to scroll past endpoint 0).
- Phone: long names, badges and cluster ids wrap instead of running off screen, the across table scrolls
  sideways, long attribute names fit in the dialog, the header no longer sticks and eats the screen.
- Desktop header: Reload fits on the first row. "1 cluster" singular.

## 0.8.0

- Error handling and robustness. Client errors are caught by type (`MatterError`, `MatterClientException`,
  `TimeoutError`) instead of broad `except Exception`; websocket commands answer with a clear error code
  (`matter_unavailable`, `matter_error`, `timeout`, `write_failed`, ...) and never a traceback.
- Writes and Identify to a slow or sleeping device time out after 30 s with "Node N didn't answer within 30 s";
  a late value update still reaches the panel and entities.
- Repair issue "Matter is not loaded" while HA's matter entry is missing, unloaded, retrying or disconnected from
  the Matter Server; it clears itself. Explorer entities go unavailable meanwhile and recover without a restart.
- Panel: "Reconnecting…" banner when its websocket drops (values greyed), re-subscribes and reloads on reconnect;
  a bulk write in flight shows "Connection lost: N of M done, check values"; a reconnect never repeats writes.
- Ticked items whose node or attribute is gone are listed as "missing" with an Untick button; malformed stored
  items are skipped with one warning each. Repeated warnings are rate limited (one per 5 minutes per item).
- Websocket schemas are stricter (path format, integer ranges, no booleans as numbers, string length).
- Diagnostics download (options, exposed list, server info, counts, last 20 write/command results).
- README: troubleshooting and debug logging.

## 0.7.0

- Identify button on each endpoint that has the Identify cluster (tree view) and on each row of the across view:
  makes the device blink or beep for 15 s so you can tell which physical device is which. No confirm dialog;
  the button shows "Identifying…" meanwhile and errors show as a toast.
- Backend: `matter_explorer/identify` (admin only) through the new command gate (`commands.py`), whose
  allow-list is Identify (cluster 3, command 0, identifyTime 1-60) only. Unavailable nodes are refused.

## 0.6.1

- Fix: values frozen at the connect snapshot (panel, entities, write read-back) until an HA restart. When the
  connection to the Matter Server drops, HA's matter integration reloads itself with a new `MatterClient`; the
  explorer kept listening to the old one. It now reloads its own entry when the matter entry returns with a
  different client. (Seen after commissioning a node while HA runs, because that is when the connection dropped.)

## 0.6.0

- Bulk write in the *Same attribute across devices* view: a checkbox per writable row, **Select all writable** /
  **Select none**, one editor (enum labels, number in °C, toggle) and **Set selected to…**. Rows that cannot be
  written (not writable, node unavailable) have no checkbox and say why.
- One confirm dialog lists device, endpoint and old → new value; rows already at the value are "no change" and
  not written; rows a node's own limits refuse are "skipped: out of range". The button says "Write to N devices".
- Progress "4 / 10" while it runs, then a per-device result (match / mismatch / timeout / error / skipped) and
  **Retry failed** (with a new confirm).
- New admin-only websocket command `matter_explorer/write_many` (max 50 items, one value). Sequential, 0.5 s
  between writes, never stops on a failure, every write goes through `async_write`; progress events stream back.
- Lab: a second thermostat instance (`scripts/lab-thermostat.sh 2`, code 20202025) commissioned by the bootstrap.

## 0.5.0

- Tree filters: a filter bar under the header with chips (R/W only, Exposed as entity, Hide unavailable devices,
  Hide global attributes [on by default], Hide endpoint 0, Manufacturer / unknown only, Changed since opened) and
  Device / Cluster selects. They combine with the search (AND), the tree opens fully while a filter is active,
  the bar shows "N attributes on M devices" and a "Clear filters" button.
- Bigger search box with an icon and the placeholder "Search … (name, id, value)"; press `/` to focus it.
- Filters and the last search are remembered per browser (localStorage; the panel works without it).
- The across view has the R/W only, Exposed and Hide unavailable filters.
- The filter logic lives in `frontend/filters.js` with `node --test` tests (`tests/js/`, run by `scripts/test.sh`).

## 0.4.1

- Fix: a failed "Add as entity" tick no longer replaces the tree with an error until Reload; the error shows as a
  dismissible message above the tree.

## 0.4.0

- "Add as entity": every attribute row in the panel (tree and across-devices view) has a checkbox. Ticked
  attributes become entities on the existing Matter device (switch, select, number, sensor, binary sensor; child
  lock 516/1 is a select Off / Level 1 … Level 5, setpoints are numbers in °C). Unticking removes the entity
  from the entity registry. The list is stored in the config entry options (`exposed`: node id + path).
- Entities take state from live attribute events, are unavailable with their node, and write only through the
  write gate. An item whose node or attribute disappeared stays in the options and logs one warning.
- Admin-only websocket command `matter_explorer/set_exposed`; `matter_explorer/nodes` entries carry `entity`
  (platform, exposed, entity_id).

## 0.3.0

- Writes, only through one gate (`writable.async_write`): a built-in table (Matter spec) of writable attributes in
  clusters Identify (3), Time Format Localization (44), Unit Localization (45), Thermostat (513) and Thermostat UI
  Configuration (516, incl. keypadLockout). Everything else (unknown/manufacturer clusters, lists/structs such as
  presets and schedules, global attributes) is read-only. Values are validated (type, enum, range; setpoints within
  the node's own limits), unavailable nodes are refused, and every write is read back and logged.
- Admin-only websocket command `matter_explorer/write`; `matter_explorer/nodes` entries carry a `write` description.
- Panel: R/W rows get an Edit button -> select / number (°C) / toggle -> confirm dialog (device, endpoint,
  attribute, old -> new, real-device warning) -> read-back result (match / mismatch / timeout).

## 0.2.0

- Sidebar panel "Matter Explorer" (admin only, `mdi:graph-outline`), a plain web component without build step:
  collapsible device → endpoint → cluster → attribute tree with value, display value, type and R flag,
  expand/collapse all, unavailable nodes greyed out, lists/structs (presets, schedules) shown read-only as
  expandable JSON. Search by device, cluster/attribute name or id and value keeps the tree shape.
- "Same attribute across all devices" view (preset Child lock 516/1, On/Off 6/0, or type `cluster/attr` or a name).
- Live updates: admin-only websocket subscription `matter_explorer/subscribe` forwards attribute changes and
  node availability from the shared MatterClient; changed cells flash. Unsubscribes when the panel closes.
- `matter_explorer/nodes` now returns live values (the client keeps them outside the node snapshot).
- Manifest dependencies: `http`, `panel_custom`.

## 0.1.0

First release as a Home Assistant custom integration (replaces the add-on prototype).

- Config flow: single instance, no input; depends on the `matter` integration.
- Uses HA's own Matter client (no second connection).
- Admin-only websocket command `matter_explorer/nodes`: every node, endpoint, cluster and attribute with raw
  value, display value, type and metadata. Manufacturer clusters are marked unknown and read-only.
