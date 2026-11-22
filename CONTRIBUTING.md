# Contributing

Thanks for helping. Bug reports and feature requests are welcome as issues; for a larger change please open an
issue first.

## Setup and checks
- `scripts/test.sh` creates a Python 3.14 venv and runs ruff, mypy, pytest (with
  `pytest-homeassistant-custom-component`) and the JS tests. It must pass before every commit.
- Tests use the redacted node dumps in `tests/fixtures/` (see its README). Add a test for every new behaviour.

## Lab
End-to-end checks run against a throw-away lab, never against your real Home Assistant or Matter Server.
`lab/docker-compose.example.yml` starts a matter.js Matter Server, a Home Assistant and sample devices;
`scripts/lab/bootstrap.py` onboards them, `scripts/lab-deploy.sh` deploys the integration into the lab HA,
`scripts/lab/e2e.py <scenario>` and `scripts/lab/screenshots.py <scenario>` drive it. Settings are environment
variables (`scripts/lab/labenv.py`). See `docs/DESIGN.md`, section Lab.

## The rules that matter
- **Read-only by default.** Anything that changes a Matter node goes through a gate, with tests:
  - attribute writes only through `writable.async_write`, the one caller of `write_attribute`. To make another
    attribute writable, add it to the table there (spec-based, with its limits) and test it;
  - commands only through `commands.async_command`, the one caller of `send_device_command`. Its allow-list is
    Identify (cluster 3, command 0, `identifyTime` 1-60) only;
  - unknown and manufacturer clusters are never writable.
- Frontend URLs must be relative.
- A user-visible change bumps `version` in `manifest.json` (patch = fix, minor = feature) and adds a
  `CHANGELOG.md` entry. UI changes come with a screenshot in the pull request.
- Do not commit credentials, tokens, host names or data from your own installation; redact fixtures.
