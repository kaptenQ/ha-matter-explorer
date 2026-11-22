#!/usr/bin/env bash
# Copy the integration into the lab HA config, restart the lab HA, wait for it and make sure
# the matter_explorer config entry exists. Lab only: never point this at another HA.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HA_URL="${HA_URL:-http://homeassistant:8123}"
LAB_HOME="${LAB_HOME:-$HOME/.matter-explorer-lab}"
LAB_CONFIG="${LAB_HA_CONFIG:-$ROOT/lab/ha-config}"
CREDS="${LAB_HA_CREDS:-$LAB_HOME/ha.json}"

case "$HA_URL" in
  http://homeassistant:*|http://localhost:*|http://127.0.0.1:*) ;;
  *) [ "${LAB_ALLOW_HA_URL:-}" = 1 ] || { echo "refusing: HA_URL=$HA_URL is not a lab Home Assistant (set LAB_ALLOW_HA_URL=1 for a lab with another host name)" >&2; exit 1; } ;;
esac

TOKEN="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["token"])' "$CREDS")"
auth=(-H "Authorization: Bearer $TOKEN")

echo "== Lab thermostat"
"$ROOT/scripts/lab-thermostat.sh" || true

echo "== Copy integration"
mkdir -p "$LAB_CONFIG/custom_components"
DEST="$LAB_CONFIG/custom_components/matter_explorer"
# HA (root) owns the __pycache__ it creates in DEST, so don't rm -rf: replace the sources only
mkdir -p "$DEST"
find "$DEST" -path '*/__pycache__' -prune -o -type f -exec rm -f {} +
(cd "$ROOT/custom_components/matter_explorer" && tar -c --exclude=__pycache__ .) | tar -x -C "$DEST"

echo "== Restart lab HA"
curl -fsS -X POST "${auth[@]}" "$HA_URL/api/services/homeassistant/restart" >/dev/null || true
sleep 5
for _ in $(seq 1 90); do
  if curl -fsS -m 5 "${auth[@]}" "$HA_URL/api/config" >/dev/null 2>&1; then up=1; break; fi
  sleep 3
done
[ "${up:-0}" = 1 ] || { echo "HA did not come back" >&2; exit 1; }

echo "== Config entry"
entries() { curl -fsS "${auth[@]}" "$HA_URL/api/config/config_entries/entry"; }
if ! entries | python3 -c 'import json,sys; sys.exit(0 if any(e["domain"]=="matter_explorer" for e in json.load(sys.stdin)) else 1)'; then
  FID="$(curl -fsS -X POST "${auth[@]}" -H "Content-Type: application/json" \
    -d '{"handler":"matter_explorer"}' "$HA_URL/api/config/config_entries/flow" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["flow_id"])')"
  curl -fsS -X POST "${auth[@]}" -H "Content-Type: application/json" -d '{}' \
    "$HA_URL/api/config/config_entries/flow/$FID" | python3 -c 'import json,sys; print(json.load(sys.stdin)["type"])'
fi
# wait until the entry is loaded
for _ in $(seq 1 30); do
  state="$(entries | python3 -c 'import json,sys; print(next((e["state"] for e in json.load(sys.stdin) if e["domain"]=="matter_explorer"), "missing"))')"
  [ "$state" = loaded ] && break
  sleep 2
done
echo "matter_explorer entry: $state"
[ "$state" = loaded ]
