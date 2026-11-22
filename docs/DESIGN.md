# Design

The GOAL and DESIGN sections below are the original spec of the project.

## GOAL
- A sidebar panel (admin only) that shows EVERY Matter attribute of every device paired to HA's
  Matter Server. It lists them by device → endpoint → cluster → attribute, with value, type and
  read/write flag, and has a search.
- The panel also has a "same attribute across all devices" view.
- Writable values can be edited. Each write goes through a confirm dialog and the value is read
  back afterwards.
- Each attribute has an "Add as entity" checkbox. Only ticked attributes become HA entities, so HA
  isn't flooded with entities.
- Main first use: the child lock on the IKEA LILJEBAGGE thermostats, `keypadLockout` (Thermostat
  User Interface Configuration cluster 516, attribute 1, enum levels 0–5). HA doesn't expose it today.

## DESIGN
- Reuse HA's existing Matter connection. Take the MatterClient from the loaded `matter` config entry
  (homeassistant/components/matter: entry runtime data → adapter → matter_client). Do not open a
  second Matter controller and do not expose Matter Server port 5580, which has no auth.
- Client calls to use: get_nodes(); subscribe_events(ATTRIBUTE_UPDATED), so updates are pushed, not
  polled; write_attribute(node_id, "ep/cluster/attr", value).
- Names, types and enums come from the CHIP cluster objects shipped with the client library
  (chip.clusters.Objects).
- Writability comes from a small built-in table taken from the Matter spec. It covers clusters 513
  (Thermostat), 516, 44 and 45 (localization), 47 (Power Source) and 3 (Identify).
- Unknown clusters, including IKEA's manufacturer cluster 0x117C0001, are READ-ONLY. Never write to them.
- Entities from the ticked list are stored in the config entry options and attached to the existing
  Matter device in the device registry, using the matter integration's device-id helper. Mapping:
  bool → switch; enum → select (child lock → Off / Level 1–5); number with limits → number
  (setpoints are in 0.01 °C); read-only → sensor / binary_sensor. An entity is unavailable when its
  node is unavailable.
- Config flow: single instance, no input. The manifest has dependencies: ["matter"].
- Panel: panel_custom with a plain web component and no build step, plus admin-only websocket
  commands matter_explorer/nodes, /write, /set_exposed and /identify.
- Out of scope for v1: Matter 1.4 presets/schedules (research done in `docs/PRESETS.md`: wait; show them read-only; check whether the Matter
  Server supports editing them); commands (except the Identify button: commands are allowed only
  through the command gate `commands.py`, whose allow-list is Identify only), events and commissioning; removing Node-RED.

---

# Implementation notes (agent)

## Module map
`custom_components/matter_explorer/`:
- `__init__` (entry setup, panel registration with `?v=<version>`, follows the matter entry's client),
  `config_flow`, `const`, `manifest.json`, `strings.json`, `translations/en.json`.
- `client` (`get_matter_client`, `find_node`): the only place that knows HA's internals.
- `metadata` (names, types, enums from the CHIP objects), `nodes` (the `nodes` payload), `live` (live store).
- Gates: `writable` (table + `async_write`, `async_write_many`), `commands` (`async_command`, Identify only),
  `errors` (`CLIENT_ERRORS`, `run_device_call` shared by both gates, activity log, rate-limited warnings).
- Entities: `exposure` (ticked list, `ExposeSpec`, stale-entity sweep), `entity` (base `ExplorerEntity`,
  `async_setup_platform`) and the thin platforms `switch`, `select`, `number`, `sensor`, `binary_sensor`.
- `websocket_api` (admin-only commands), `diagnostics`, `export` (flat per-node attribute dump for
  `matter_explorer/export`, built from `nodes.build_nodes`).
- `frontend/`: `matter-explorer-panel.js` (the web component) with its methods mixed in from `connection.js`,
  `tree.js`, `across.js`, `dialogs.js`, `export.js` (Export / Compare, pure diff helpers); `styles.js`, `util.js`; pure logic `filters.js`, `bulk.js` (node:test in
  `tests/js/`). Plain ES modules with relative imports, no build step.
Also `hacs.json`, `tests/` (pytest-homeassistant-custom-component, fixtures in `tests/fixtures/`), `scripts/`
(`test.sh`: ruff, mypy, pytest, JS tests; `lab-deploy.sh`; `lab/`: `bootstrap.py`, `ha_ws.py`, `e2e.py <scenario>`,
`screenshots.py <scenario>`, `playtest.py`).

## Gates
- Writes: only `writable.async_write` calls `write_attribute`. Commands: only `commands.async_command` calls
  `send_device_command`, allow-list Identify. Both wrap the device call in `errors.run_device_call` (30 s timeout,
  client errors -> the gate's refusal, warning log, activity log) and look the node up with `client.find_node`.
- Nothing else writes to a node: entities, the websocket commands and bulk write all go through these two.

## Live store
`live.LiveStore` (`hass.data[STORE_KEY]`, one per config entry) subscribes once per node and attribute path and
keeps an overlay of the newest raw values, because the client's `node_data` does not follow live updates.
`nodes`, the write gate (old value, "no change") and the entities read through the overlay; the websocket
`subscribe` fans events out to panels.

## Client access: verified against HA 2026.11.2
The spec matches. `homeassistant/components/matter/helpers.py` defines `MatterEntryData(adapter, listen_task,
ble_proxy)` as the entry's `runtime_data`; `MatterAdapter.matter_client` is the `MatterClient`
(`matter_server.client`, from `matter-python-client==1.5.5`). `client.py::get_matter_client()` returns it from
`hass.config_entries.async_loaded_entries("matter")[0].runtime_data.adapter.matter_client` and raises
`MatterClientUnavailable` (a `HomeAssistantError`) if there is no loaded entry or the shape differs. The
websocket command turns that into the error code `matter_unavailable`; entry setup turns it into
`ConfigEntryNotReady` (retries until `matter` is loaded). No fallback websocket was needed.
Useful matter helpers: `get_device_id(server_info, endpoint)`, `get_node_device_identifier(...)`,
`node_from_ha_device_id`; `MatterClient.get_nodes()`, `subscribe_events(cb, EventType.ATTRIBUTE_UPDATED)`,
`write_attribute(node_id, "ep/cluster/attr", value, timed_request_timeout_ms=None)` (value is the raw
python value; the client converts it to a tag dict).

## Cluster metadata
`matter-python-client` 1.5.5 ships the `chip` package: `chip.clusters.Objects` plus
`ClusterObjects.ALL_CLUSTERS` / `ALL_ATTRIBUTES` (names, enums, bitmaps, structs). The registries are only
filled once `chip.clusters.Objects` is imported (`metadata.py` does). Types come from the Python
annotation of each attribute (`attribute_type.Type`): `Nullable | int`, enum classes (labels from the `k...`
members, `kUnknownEnumValue` dropped), `IntFlag` bitmaps, `List[...]`, dataclass structs. There are no
min/max in the objects, so `min`/`max` come from the node's own limit attributes where the spec defines
them (setpoints: `513/21..24`) and are otherwise `null`. `metadata.py` returns `AttributeMeta` and
`display_value()`.
- Manufacturer clusters (id > 0xFFFF) are always "unknown", named `0x117CFC01`-style, and read-only
  (`is_readonly_cluster`), even though `matter_server.common.custom_clusters` registers classes for some
  (IKEA's 293403649 becomes `IkeaValveCalibrationCluster` once HA's matter integration is loaded). Never write to them.
- Spec correction: IKEA's cluster 293403649 is `0x117CFC01` (vendor 0x117C, cluster 0xFC01), not `0x117C0001`
  (= 293339137). Both are tested.

## `matter_explorer/nodes`
Admin only (`@websocket_api.require_admin`). Result `{"nodes": [{node_id, name, available, is_bridge,
vendor, product, endpoints: [{endpoint_id, clusters: [{cluster_id, name, unknown, attributes: [{attribute_id,
path, name, value, display_value, unit, type, meta}]}]}]}]}`. `value` is the raw value from
`node.node_data.attributes`; `display_value` is the enum label, or °C for the 0.01 °C temperature
attributes (`metadata.CENTI_CELSIUS`, with `unit: "°C"`); otherwise `null`. `name` is NodeLabel (`0/40/5`),
else vendor + product, else `Node <id>`. The command only touches `node_id`, `available`,
`node_data.attributes` and `node_data.is_bridge`, which the test fake provides. The command reads
everything from the client's in-memory node data (no Matter Server round trip).

## Tests
`scripts/test.sh` (ruff with a wide rule set, mypy on `custom_components/`, pytest, JS tests). pytest-homeassistant-custom-component has no release for HA 2026.11 yet:
the newest, 0.13.375, pins `homeassistant==2026.10.4`. Forcing 2026.11.2 under it breaks on API drift
(`_clear_logger_overwrites`, httpx aliasing, aiohasupervisor), so tests run on 2026.10.4 and the lab (HA
2026.11.2) covers the newer version through `scripts/lab-deploy.sh`. Needs Python 3.14.
Fixtures: `liljebagge-node6.json` (a real thermostat, redacted, see `tests/fixtures/README.md`), `lab-node.json` (lab sample node 6 from matter.js server 1.5.5).

## Lab
A development lab, for contributors (an example is in `lab/docker-compose.example.yml`):
- Matter Server: matter.js server (`ghcr.io/matter-js/matterjs-server`, run with `--enable-test-net-dcl` so it
  accepts matter.js test devices) at `ws://matter-server:5580/ws` (`$MATTER_SERVER_URL`); Home Assistant at
  `http://homeassistant:8123` (`$HA_URL`); sample devices `dev-light` (20202021), `dev-sensor` (20202022) and
  `dev-bridge` (20202023) from matter.js.
- Lab state lives in `$LAB_HOME` (default `~/.matter-explorer-lab`): `ha.json` (HA credentials and a long-lived
  token, mode 600), `nodes.json` (device -> node id), `thermostat*/` (matter.js storage and logs). `$LAB_HA_CONFIG`
  (default `lab/ha-config`) is the lab HA's `/config` as seen from the dev machine. See `scripts/lab/labenv.py`.
- `scripts/lab/bootstrap.py` is idempotent: it onboards HA (user, token, Matter integration) and commissions the
  sample devices, recognising already commissioned nodes by device type. If HA's container has no IPv6 route, it
  gives HA the Matter Server's IPv4 address, because the hostname also resolves to IPv6 and HA's config flow then
  fails with `cannot_connect`.
- `scripts/lab-deploy.sh` copies the integration into the lab HA config, restarts it, waits and creates the config
  entry if missing (HA, running as root, writes `__pycache__` into the deployed dir, so files are replaced, not
  the directory). `scripts/lab/ha_ws.py <command> [--summary]` calls a websocket command on the lab HA.
- The scripts refuse an `HA_URL` that is not a lab host (`homeassistant`, `localhost`, `127.0.0.1`) unless
  `LAB_ALLOW_HA_URL=1`. Never point them at a Home Assistant you care about.
- Commissioning by `commission_with_code` (mDNS) can fail on a Docker bridge; the bootstrap falls back to
  `commission_on_network` by IPv6. Failed attempts burn node ids. Reset: remove nodes with the `remove_node`
  command (or wipe the matter-server volume) and delete `nodes.json`; to re-onboard HA wipe its config volume and
  delete `ha.json`.

## Lab thermostat
- `lab/thermostat/` is a matter.js device (Node 22, `@matter/main` 0.15.6): endpoint 1 = Thermostat (513, heating
  only; localTemperature 1950, occupiedHeatingSetpoint 2100, limits 500/3500, systemMode Heat), Thermostat UI
  Configuration (516; keypadLockout writable, starts at 1) and Identify (3). Vendor/product names and versions
  copy the LILJEBAGGE fixture, NodeLabel "Lab thermostat". Vendor id is the test vendor 0xFFF1 (not IKEA's 4476).
  There is no manufacturer cluster: matter.js 0.15 has no cheap way to add one, so IKEA's 0x117CFC01 can only be
  tested with the fixture.
- Setup code 20202024, discriminator 3844, port 5541. A second instance (`scripts/lab-thermostat.sh 2`) uses
  20202025, 3845, 5542.
- `scripts/lab-thermostat.sh` starts it in a screen session `thermostat` (idempotent; runs `npm ci` the first
  time). `scripts/lab-deploy.sh` and the bootstrap both call it. Attach with `screen -r thermostat`.
- Commissioning (bootstrap): by IP with the dev container's IPv6 address (`socket.gethostname()`), after the
  `commission_with_code` try with the 11-digit manual pairing code computed from passcode + discriminator (the
  bare 8-digit passcode is rejected: error 8). The Matter Server must run with `--enable-test-net-dcl`, otherwise it
  rejects matter.js test devices with `attestation-rejected`.

## Writes

`writable.py` holds the table `WRITABLE[(cluster, attribute)]` (type, enum values or int range) for clusters
3, 44, 45, 513 and 516 only, and the gate `async_write(hass, node_id, path, value)`. It is the only code that calls
`write_attribute`. Power Source (47) has no entry: its writable attribute was not certain enough.
Entries: 3/0; 44/0, 44/1; 45/0; 513/16 (-25..25), 513/17-20 setpoints (int16, 0.01 °C, within the node's
Min/MaxHeat|CoolSetpointLimit 21/22 or 23/24, else AbsMin/AbsMax 3/4 or 5/6; no limits -> not editable),
513/27, 513/28; 516/0-2. Enum values are checked against the CHIP enums in a test.
Never writable: unknown/manufacturer clusters (id > 0xFFFF or >= 0xFC00), lists/structs (513/72, 513/80), globals
(>= 0xFFF8), anything not in the table.
Gate order: path parse -> table -> node exists -> path exists -> node available -> validate -> log old/new at info
-> `write_attribute` (a non-zero status in the response is an error) -> read back with `read_attribute` (else the
next ATTRIBUTE_UPDATED), 10 s timeout. Result `{ok, written, read_back, matches, timeout}`. Refusals raise
`WriteRefused(code)`; the websocket maps them to error codes (`not_writable`, `invalid_value`, `node_unavailable`,
`node_not_found`, `invalid_path`, `write_failed`). Admin only. The panel's Edit dialog is a modal
(edit -> confirm -> result); `nodes` entries carry `write` ({type, min, max, unit, values}) so the table lives
only in the backend.

## Bulk write

`matter_explorer/write_many` (admin): `{items: [{node_id, path}] (1..50), value}`. The result is only an
acknowledgement; events follow on the same message id: `{event: "progress", done, total, item}` after every item
and finally `{event: "done", results}` (the panel uses `subscribeMessage`). `writable.async_write_many` handles
the items one after the other, `WRITE_SPACING` = 0.5 s pause between two real writes (Thread), and never stops on
a failure. Per item: `check_write` first (no I/O; the limits are the node's own), then "old == value" -> `no_change`
(old = live overlay value, the client's snapshot goes stale), else `async_write` (the only writer; it re-checks).
Item `status`: `ok` (read-back matches), `mismatch`, `timeout` (no read-back), `error` (`write_failed` or any
exception), `skipped` (+ `code`, `reason`: node_unavailable, not_writable, invalid_value = out of range, ...),
`no_change`. Panel: `frontend/bulk.js` (pure planning logic, `tests/js/bulk.test.mjs`) and the dialog in
`frontend/dialogs.js`; the plan is also computed client-side so the confirm dialog shows exactly what will be written.

## Panel and live updates
- `__init__.py` serves `frontend/` at `/matter_explorer_static` and registers the `panel_custom`
  `matter-explorer-panel` (`/matter-explorer`, admin only, `mdi:graph-outline`). Panel removed on unload.
- `frontend/matter-explorer-panel.js` (+ modules, see the module map): one web component, `hass.callWS` for `matter_explorer/nodes`, HA theme
  CSS variables only. Tree renders only expanded branches (a node has ~300 attributes); with a search all
  matching branches are open.
- `live.py` `LiveStore` (created per config entry, `hass.data[STORE_KEY]`): `MatterClient.subscribe_events`
  callbacks get only `(event, data)`; for ATTRIBUTE_UPDATED `data` is the new value and node/path are filter
  keys, so the store subscribes once per node and attribute path (closure knows both) plus node
  added/updated/removed and endpoint added/removed. The client does NOT update `node_data.attributes`
  on live updates, so the store keeps an overlay of newest raw values that `matter_explorer/nodes` applies; a
  NODE_UPDATED snapshot clears the node's overlay and re-subscribes its paths.
- Stale values after a node was paired while HA runs: the per-path subscriptions, the order
  NODE_ADDED then NODE_UPDATED, and the overlay were all fine (replayed in `tests/test_live.py`). The cause: HA's
  `matter` integration reloads its entry whenever the Matter Server connection drops (`_client_listen`), which
  creates a NEW `MatterClient`. `LiveStore` and the entities kept the old, dead client, and a fresh client's
  `node_data` is only the connect snapshot, so nothing updated until HA restarted. `__init__.py` now watches
  the matter entry's state (`async_on_state_change`) and reloads the explorer entry when the loaded matter
  entry carries a different client. Lab check: `scripts/lab/e2e.py new-node`.
- `matter_explorer/subscribe` (admin) adds a listener to the store and removes it on unsubscribe/disconnect;
  events: `attribute_updated {node_id, path, value, display_value}`, `node_updated {node_id, available}`,
  `node_added`/`node_removed` (panel reloads). The panel unsubscribes in `disconnectedCallback`.
- Screenshots: `scripts/lab/screenshots.py <scenario>` (Playwright in a throwaway venv, lab only).

## Entities
- Options: `{"exposed": [{"node_id": 6, "path": "1/516/1"}]}`, no values. `exposure.py` maps an attribute to
  `ExposeSpec` (platform, name, scale, unit, device class, enum options, limits) from the write gate's
  `describe_write` (writable) or the CHIP type (read-only). One generic `ExplorerEntity` (`entity.py`) plus five thin
  platform modules. Names: the CamelCase attribute name in words; 516/1 is "Child lock" with select labels
  Off / Level 1–5.
- `matter_explorer/set_exposed {node_id, path, exposed}` (admin): updates the options under a lock, unloads the
  entity platforms, removes entity registry entries that are no longer ticked, and forwards the platforms again
  (the panel and live store keep running). The same stale-entity sweep runs at every setup, so the registry
  always matches the options. The result carries the new `entity_id`.
- unique_id `matter_explorer_<compressed fabric id hex>_<node>_<ep>_<cluster>_<attr>`.
- Device: the identifier comes from the matter integration's helpers (`get_node_device_identifier`, or
  `get_device_id` for bridged endpoints). The device is looked up in the registry under the **matter** config
  entry and attached with `entity.device_entry = device` (what helper integrations do). HA 2026.10+ scopes
  identifiers to config entries, so `device_info` would create a second device. No device found: the entity is
  created without a device and a warning is logged.
- State: `ATTRIBUTE_UPDATED` per node and path, `NODE_UPDATED` / `NODE_REMOVED` for availability; initial value from
  the node snapshot overlaid with the live store. No polling.
- Lab end to end (`scripts/lab/e2e.py entities`, `screenshots.py entities`) on 2026.11.2 with the light's identifyTime.
