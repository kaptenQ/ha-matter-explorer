# Matter Explorer – guide for AI coding agents and contributors

Home Assistant custom integration (`matter_explorer`) to explore a Matter fabric: it reuses the MatterClient of
HA's `matter` integration, exposes admin-only websocket commands, and a panel. Read-only by default.
The spec is in `docs/DESIGN.md`.

## Layout
- `custom_components/matter_explorer/` – the integration (`__init__`, `config_flow`, `client`, `metadata`,
  `nodes`, `writable`, `commands`, `errors`, `live`, entities, `websocket_api`, `frontend/` ES modules; module map in
  `docs/DESIGN.md`); `hacs.json`
- `tests/` – pytest-homeassistant-custom-component, fixtures in `tests/fixtures/`
- `scripts/test.sh` (all checks), `scripts/lab-deploy.sh`, `scripts/lab/` (`bootstrap.py`, `ha_ws.py`, `e2e.py <scenario>`, `screenshots.py <scenario>`)
- `docs/` – `DESIGN.md`, `PRESETS.md`, `images/` (README screenshots); issue templates live in `.github/ISSUE_TEMPLATE/` (owner-only); `CHANGELOG.md`,
  `CONTRIBUTING.md` at the root
- `.dev/` (git-ignored, local only) – `PROGRESS.md`, `HISTORY.md`, `PLAYTEST.md`: internal task logs; `docs/screenshots/`
  (also git-ignored) is where task screenshots go

## Commands
- `scripts/test.sh` – deps (Python 3.14 venv), ruff, mypy, pytest, JS tests. Must pass before every commit.
- `scripts/lab-deploy.sh` – copy the integration into the lab HA config, restart the lab HA, wait, make sure
  the config entry exists.
- `.venv/bin/python scripts/lab/ha_ws.py matter_explorer/nodes --summary` – query the lab HA.

## Lab
- A throw-away lab (Matter Server, Home Assistant, sample devices) is the only place to run end-to-end checks. Set it
  up with `lab/docker-compose.example.yml`; the settings are environment variables (`MATTER_SERVER_URL`, `HA_URL`,
  `LAB_HOME`, `LAB_HA_CONFIG`, see `scripts/lab/labenv.py`). Lab credentials live in `$LAB_HOME` (never print or
  commit them).
- Lab thermostat (LILJEBAGGE-like, matter.js, `lab/thermostat/`, code 20202024): `scripts/lab-thermostat.sh`
  starts it in screen session `thermostat`; deploy and bootstrap do it too. The lab Matter Server must run with
  `--enable-test-net-dcl` to commission it (see docs/DESIGN.md).
- Sample devices `dev-light`, `dev-sensor`, `dev-bridge` (matter.js). `.venv/bin/python scripts/lab/bootstrap.py`
  is idempotent. See docs/DESIGN.md.
- Never contact a Home Assistant or Matter Server that is not part of the lab. Deploys to, writes on and restarts of
  real installations are done by a human, never by an agent.

## Rules
- Commit on `dev` only, small working commits with checks passing. Never push. Do not edit `.github/` or `deploy/` unless the task says so.
- Writes go ONLY through `writable.async_write` (the one caller of `write_attribute`); extend the table there.
- Commands go ONLY through the command gate (`commands.async_command`, the one caller of
  `send_device_command`), whose allow-list is Identify (cluster 3, command 0, identifyTime 1-60) only; extend
  the allow-list there, with tests.
- Read-only by default: anything that writes to a Matter node (attribute writes, commands, commissioning,
  removal) must go only through the write gate , with tests. Unknown/manufacturer
  clusters are never writable.
- Every user-visible task bumps `version` in `manifest.json` (patch = fix, minor = feature) and adds a
  `CHANGELOG.md` entry, in the same commit. 
- Add tests for new behaviour. For UI changes take Playwright screenshots into `docs/screenshots/` and look at them.
- Append one entry per task to `.dev/HISTORY.md`; keep `.dev/PROGRESS.md` current (both are local, not published).
- Frontend URLs must be relative.
