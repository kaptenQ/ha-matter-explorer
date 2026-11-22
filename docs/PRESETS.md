# Matter 1.4 presets and schedules: can the Matter Server edit them? (research)

Research only, no code. Date 2026-11-20. Sources: `matter-python-client` 1.5.5 (read in `.venv`), the matter.js cluster
model that the lab thermostat runs (`lab/thermostat/node_modules/@matter/model`, Thermostat cluster elements), the
matterjs-server docs on GitHub (`docs/websockets_api.md`, `docs/websocket-api-schema-changelog.md`, `CHANGELOG.md`,
issues), and the redacted real fixture `tests/fixtures/liljebagge-node6.json`. Anything not verified is marked **unverified**.
Nothing was written to any device, and nothing was tried against a production server.

## The spec in short (Thermostat cluster 513, Matter 1.4)
- Features: `PRES` (bit 7, 0x80) Presets and `MSCH` (bit 8, 0x100) MatterScheduleConfiguration.
- Attributes: 72 `PresetTypes`, 73 `ScheduleTypes` (read-only, fixed), 74 `NumberOfPresets`, 75 `NumberOfSchedules`,
  76 `NumberOfScheduleTransitions`, 77 `NumberOfScheduleTransitionPerDay`, 78 `ActivePresetHandle`, 79 `ActiveScheduleHandle`
  (nullable, read-only), **80 `Presets`** and **81 `Schedules`** (`RW VM`: write needs Manage privilege; quality `N T` =
  non-volatile and *atomic*), 82 `SetpointHoldExpiryTimestamp`.
- `Presets` and `Schedules` are lists of structs and are **replaced as a whole**. A device accepts a write to them
  only inside an atomic write. A preset left out of the new list is removed; built-ins and the active preset can't be removed.
- Commands: 5 `SetActiveScheduleRequest(ScheduleHandle)`, 6 `SetActivePresetRequest(PresetHandle|null)` (ordinary
  commands, can be sent through the existing command path once allow-listed), 0xFE (254) `AtomicRequest`, answered by 0xFD (253)
  `AtomicResponse`.
- `AtomicRequest` fields: `RequestType` (0 BeginWrite, 1 CommitWrite, 2 RollbackWrite), `AttributeRequests` (the attribute ids to lock,
  e.g. `[80]`), `Timeout` (ms, BeginWrite only; the device may shorten it). `AtomicResponse`: `StatusCode`, per attribute
  `AtomicAttributeStatusStruct{AttributeID, StatusCode}`, `Timeout`. (The field layout of the two commands is from the
  spec as remembered; the enum values were checked in the matter.js model, the struct fields were not.)
- `PresetStruct`: 0 PresetHandle (octstr <= 16, **null for a new preset**, the device assigns it), 1 PresetScenario
  (1 Occupied, 2 Unoccupied, 3 Sleep, 4 Wake, 5 Vacation, 6 GoingToSleep, 254 UserDefined), 2 Name (<= 64, optional),
  3 CoolingSetpoint, 4 HeatingSetpoint, 5 BuiltIn.
- `ScheduleStruct`: 0 ScheduleHandle, 1 SystemMode, 2 Name, 3 PresetHandle, 4 Transitions (list of `ScheduleTransitionStruct`:
  DayOfWeek bitmap, TransitionTime minutes 0..1439, PresetHandle, SystemMode, Cooling/HeatingSetpoint), 5 BuiltIn.
- Atomic write protocol: BeginWrite (lock) -> ordinary attribute write(s), which are staged -> CommitWrite (the device validates the
  whole result and applies it, or answers with per-attribute errors) or RollbackWrite. The lock times out by itself.
  Only one atomic write per attribute per client at a time (BUSY otherwise).

## Q1: can the Matter Server write them today?

| | matterjs-server 1.4.0 (schema 13) | 1.5.5 (lab; schema 14) | 1.6.0 (released 2026-11-14; schema 15) |
|---|---|---|---|
| `write_attribute` of a list of structs | yes, struct members by TLV tag (1.4.0 also accepts wire field names; issue #957 fixed 2026-08) | yes, plus `timed_request_timeout_ms` and `*` endpoint | same; writes out of constraint go to the device |
| `device_command` (any cluster command by name + payload) | yes | yes (+ `batched_device_commands`) | yes |
| `write_atomic_attribute` (BeginWrite, write, CommitWrite, RollbackWrite done by the server) | **no** | **no** | **yes** (schema 15) |
| Dashboard preset editor | no | 1.5.3 added a Presets panel (mechanism **unverified**) | uses `write_atomic_attribute` (per release notes) |

- **Through `device_command` + `write_attribute` (works on 1.4.0 and 1.5.5, in principle).** The server docs say a client that
  manages atomic writes itself "keeps using `device_command` and `write_attribute`". So the client would do:
  `device_command(AtomicRequest{BeginWrite,[80]})` -> `write_attribute(node, "1/513/80", [ {tag: value}, ... ])` ->
  `device_command(AtomicRequest{CommitWrite,[80]})`, with `RollbackWrite` on any error. The `command_name` and payload keys for
  `AtomicRequest` are **not documented** (field-name keyed, probably `requestType`, `attributeRequests`, `timeout`; casing in the
  server examples is inconsistent), and a plain `write_attribute` to an atomic attribute has no documented result. That the atomic state
  survives across separate websocket messages (it is keyed by the device-side fabric/node, not by the socket) is expected, not tested.
- **Python client side.** `matter-python-client` 1.5.5 has `write_attribute(node_id, path, value, timed_request_timeout_ms)` and
  `send_device_command(node_id, endpoint_id, command: ClusterCommand, ...)`. There is **no** atomic helper and no
  `write_atomic_attribute` (schema 15 is newer than the client HA 2026.11 ships). `send_device_command` takes a CHIP
  `ClusterCommand` dataclass (`Clusters.Thermostat.Commands.AtomicRequest` exists in the real chip package; the venv has only a
  191-line stub, so this was not exercised here). A schema-15 command could still be sent with
  `client.send_command("write_atomic_attribute", require_schema=15, ...)` (`send_command` takes any string), but only against a 1.6.0 server.
- **Python-matter-server (old, schema 11)**: out of scope. The lab runs matterjs-server.
- `write_atomic_attribute` args (1.6.0 docs): `node_id`, `attribute_path`, `value` (the whole list), `data_version` (from `read`'s
  `data_versions["1/513"]`; or `skip_data_version_check`), `ignore_data_version_mismatch`, `timed_request_timeout_ms`,
  `atomic_timeout_ms` (1..65535, default 30000). Result: one write-status entry; 0 = committed, else the first failure
  (156 BUSY, 203 INVALID_IN_STATE, 146 DATA_VERSION_MISMATCH).
- Related server issues: #1200 (editing presets, closed 2026-10-23), #1284 (a reusable preset create/edit/remove API, closed 2026-11-15). The
  schedule editor in the dashboard (#962, MSCH panel) existed since 1.4.0 as a view.
- **Answer.** Yes on every version if the client drives the atomic flow itself (device commands + write_attribute); cleanly only on
  1.6.0+, and only a client that knows schema 15 can call it. A 1.4.0 server needs the manual flow, on its older schema 13.

## Q2: what a safe editor needs
1. **Gating.** Extend the command allow-list (`commands.py`, currently Identify only) with AtomicRequest (Begin/Commit/Rollback,
   attribute 80 and 81 only) and SetActivePresetRequest/SetActiveScheduleRequest, and the write gate (`writable.py`) with a
   "whole-list" write for 513/80 and 513/81, available only from inside an open atomic session. Admin only, with confirm dialogs like the
   current write dialog.
2. **Flow**: read the current list and the cluster data version -> edit a copy in the panel -> validate -> Begin(timeout 10-30 s) ->
   write -> Commit -> read back and compare -> show the diff. Any failure after Begin -> Rollback, then report. A session
   timeout, a lost connection or a dropped panel must end in Rollback or in the device's own timeout (nothing partial is applied
   by design). Never leave a lock open: one operation per request, with a hard server-side timeout.
3. **Validation before sending** (the device checks again): count <= `NumberOfPresets` (74), per scenario count <= the
   `PresetTypes` entry (72), names only when `SupportsNames`, name <= 64 bytes, handles untouched for existing items and `null` for new
   ones, built-in presets unchanged and still present, setpoints inside the Abs min/max limits and the deadband, at least one of
   heating/cooling per the features, schedules: count <= 75, transitions <= 76 and <= 77 per day, TransitionTime 0..1439,
   `SystemMode` allowed by `ScheduleTypes` (73), preset handle exists. Octet strings are base64 in the stored data (`"AQ=="`).
4. **Rollback**: RollbackWrite releases the lock and drops the staged data. After a *committed* bad change there is no undo
   in Matter: only another write. So: keep the pre-change list in the activity log (and offer "Restore previous list").
5. **Server version check** at runtime (`server_info.schema_version`): >= 15 use `write_atomic_attribute`; 13/14 the manual flow;
   or disable the editor if neither is verified.

## Q3: LILJEBAGGE risk (fixture node 6)
- 1/513 FeatureMap 385 = 0x181: Heating | PRES | MSCH. ClusterRevision 9. AcceptedCommandList `[0, 5, 6, 254]`,
  GeneratedCommandList `[253]`: the device does offer AtomicRequest, SetActivePresetRequest, SetActiveScheduleRequest.
- 513/72 PresetTypes: scenarios 1 (Occupied), 2 (Unoccupied) with 1 preset each and feature `1` = Automatic; 3 Sleep, 4 Wake, 5 Vacation and
  254 UserDefined with 1 preset each and feature `2` = SupportsNames. Their count sums to 6 but 513/74 NumberOfPresets = 5 (a small
  inconsistency in the firmware; the editor should trust the stricter number, and never be surprised by a refused commit).
- 513/80 Presets: two entries, both BuiltIn: `{handle "AQ==" (0x01), Occupied, heat 2100 (21.00 C)}` and
  `{handle "Ag==" (0x02), Unoccupied, heat 2000 (20.00 C)}`, no names. 513/78 ActivePresetHandle = null.
- 513/73 ScheduleTypes: one entry, SystemMode 4 (Heat), 1 schedule, feature `2` = SupportsSetpoints. 513/81 Schedules = `[]`.
  75 NumberOfSchedules = 1, 76 transitions = 56, 77 per day = 8. 513/79 ActiveScheduleHandle = null.
- Risk assessment:
  - Reading is free. The panel already shows these lists (raw JSON). A readable "Presets" view would be safe.
  - Writing: the two Automatic presets are managed by the device; a whole-list write that omits or alters a BuiltIn entry is
    refused (expected) or, on a quirky firmware, has unknown effect. **Unverified on this firmware**: whether it implements
    the atomic flow correctly, what handle it assigns to a new preset, and how it reacts to a lost Commit. The Matter data in
    the heating plan is non-volatile (survives reboot), so a wrong list is a lasting change, undone only by another write.
  - Impact of a wrong preset is a wrong setpoint when that preset is activated, no safety function. Schedules: the device
    starts with none; creating one changes when the radiator heats, but nothing activates it until `SetActiveScheduleRequest`.
  - Consequence for the first tests: never on a real LILJEBAGGE first. Lab: the matter.js lab thermostat
    (`lab/thermostat`, matter.js has the Thermostat Presets/Schedules features and the atomic commands) can host the
    flow; whether its model enables PRES/MSCH was not checked here.

## Recommendation: **wait**, then build small
- Not "never": the data and the dashboard path exist (server 1.5.3+ has a preset panel, 1.6.0 an API), and presets are what a heating
  user edits.
- Not "build now": (1) a 1.4.0 server and HA's bundled client (1.5.5) have no atomic helper, so we would write and
  test our own atomic flow against undocumented command payloads; (2) the project's rule is read-only by default and this is the first
  whole-structure, non-volatile write; (3) only one device is known, and its firmware is untested for atomic writes.
- Wait for: a server on >= 1.6.0 (schema 15 `write_atomic_attribute`, which also does the rollback on the server) **or** a lab
  trial showing the manual flow works on the lab thermostat. Then build.
- Size when built (rough): backend ~250 lines (write-gate extension for whole-list atomic writes, allow-list entries, validation in
  Python from 72/73/74/75/76/77, activity log, rollback on every error path) + ~250 lines of tests; panel ~350-450 lines JS (preset and schedule
  list view, a row editor, confirm dialog with diff) + JS tests; plus lab e2e. About 3 tasks: (1) read-only preset/schedule view,
  (2) atomic write gate + tests, (3) editor UI + lab e2e. Task 1 can be done any time and needs no server change.
