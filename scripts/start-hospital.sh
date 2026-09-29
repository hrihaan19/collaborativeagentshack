#!/usr/bin/env bash
# Hospital machine: SuperNode (outbound-only to SuperLink) + local console on 127.0.0.1.
# Usage: scripts/start-hospital.sh A|B|C [supernode-port] [console-port]
. "$(dirname "$0")/common.sh"
HID="${1:?hospital id A|B|C}"; HID="${HID^^}"
SN_PORT="${2:-$SUPERNODE_PORT}"; CON_PORT="${3:-$HOSPITAL_CONSOLE_PORT}"
case "$HID" in A) PART=0;; B) PART=1;; C) PART=2;; *) echo "hospital id must be A, B or C"; exit 1;; esac
STATE_DIR="$ROOT/state/hospital-$(echo "$HID" | tr 'A-Z' 'a-z')"
mkdir -p "$STATE_DIR"
banner "Hospital $HID  ->  outbound Flower connection to SuperLink ${COORDINATOR_HOST}:${SUPERLINK_FLEET_PORT}. No inbound ports. Console 127.0.0.1:${CON_PORT}"
python -c "from domino.hospital.store import HospitalStore; from pathlib import Path; HospitalStore('$HID', Path('$STATE_DIR')).seed()"
flower-supernode --insecure \
  --superlink "${COORDINATOR_HOST}:${SUPERLINK_FLEET_PORT}" \
  --host 127.0.0.1 --port "$SN_PORT" \
  --node-config "hospital-id=\"$HID\" partition-id=$PART num-partitions=3 state-dir=\"$STATE_DIR\"" \
  > "logs/supernode-$HID.log" 2>&1 &
echo $! > "state/supernode-$HID.pid"
DOMINO_HOSPITAL_ID="$HID" DOMINO_HOSPITAL_STATE_DIR="$STATE_DIR" \
  uvicorn domino.hospital.console:app --host 127.0.0.1 --port "$CON_PORT" > "logs/console-$HID.log" 2>&1 &
echo $! > "state/console-$HID.pid"
echo "Hospital $HID console: http://127.0.0.1:${CON_PORT}/   (logs/supernode-$HID.log, logs/console-$HID.log)"
