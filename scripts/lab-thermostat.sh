#!/usr/bin/env bash
# Start the lab thermostat (lab/thermostat, matter.js) in a screen session named "thermostat".
# Usage: lab-thermostat.sh [N]  (N=2: second instance, code 20202025, discriminator 3845, port 5542).
# Idempotent: does nothing if the session is already running. Lab only.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$ROOT/lab/thermostat"
N="${1:-1}"
if [ "$N" = 1 ]; then SESSION=thermostat SUFFIX=""; else SESSION="thermostat$N" SUFFIX="-$N"; fi
LAB_HOME="${LAB_HOME:-$HOME/.matter-explorer-lab}"
LOG="${LAB_THERMOSTAT_LOG:-$LAB_HOME/thermostat$SUFFIX.log}"

if screen -ls 2>/dev/null | grep -q "\.$SESSION[[:space:]]"; then
  echo "lab thermostat: screen session already running"
  exit 0
fi
screen -wipe >/dev/null 2>&1 || true
[ -d "$DIR/node_modules/@matter/main" ] || (cd "$DIR" && npm ci --no-audit --no-fund)
mkdir -p "$LAB_HOME/thermostat$SUFFIX"
screen -dmS "$SESSION" bash -c "cd '$DIR' && LAB_THERMOSTAT_N=$N exec node thermostat.mjs >>'$LOG' 2>&1"
# wait for it to announce itself
for _ in $(seq 1 30); do
  grep -q 'Lab thermostat starting' "$LOG" 2>/dev/null && { sleep 3; break; }
  sleep 1
done
screen -ls | grep -q "\.$SESSION[[:space:]]" && echo "lab thermostat: started (log $LOG)" \
  || { echo "lab thermostat: failed to start, see $LOG" >&2; exit 1; }
