#!/usr/bin/env bash
# Neutral coordinator (Nebius VM, fallback M1): SuperLink + ServerApp + API + dashboard + QR page.
. "$(dirname "$0")/common.sh"
banner "Coordinator on $(hostname): SuperLink Fleet gRPC 0.0.0.0:${SUPERLINK_FLEET_PORT}, Control HTTP 0.0.0.0:${SUPERLINK_CONTROL_PORT}, API ${COORDINATOR_API_PORT}, dashboard ${DASHBOARD_PORT}, QR ${QR_PORT}"
export DOMINO_COORDINATOR_STATE_DIR="$ROOT/state/coordinator"
mkdir -p "$DOMINO_COORDINATOR_STATE_DIR"
COORDINATOR_HOST=127.0.0.1 write_flwr_config   # flwr run talks to the local SuperLink
flower-superlink --insecure \
  --fleet-api-address "0.0.0.0:${SUPERLINK_FLEET_PORT}" \
  --host 0.0.0.0 --port "${SUPERLINK_CONTROL_PORT}" \
  --database "$ROOT/state/superlink.db" --disable-runtime-dependency-installation > logs/superlink.log 2>&1 &
echo $! > state/superlink.pid
sleep 3
for port_role in "${COORDINATOR_API_PORT}:api" "${DASHBOARD_PORT}:dashboard" "${QR_PORT}:qr"; do
  port="${port_role%%:*}"; role="${port_role##*:}"
  DOMINO_ROLE="$role" uvicorn domino.coordinator.api:app --host 0.0.0.0 --port "$port" > "logs/${role}.log" 2>&1 &
  echo $! > "state/${role}.pid"
done
echo "Submitting Domino ServerApp run to local SuperLink ..."
flwr run . domino -c "state-dir=\"$DOMINO_COORDINATOR_STATE_DIR\" poll-seconds=${POLL_SECONDS} round-timeout=${ROUND_TIMEOUT}" | tee logs/flwr-run.log
echo "Dashboard: http://${COORDINATOR_HOST}:${DASHBOARD_PORT}/   QR page: ${PUBLIC_URL}/qr   API: http://${COORDINATOR_HOST}:${COORDINATOR_API_PORT}/api/state"
echo "Logs in logs/. Stop with scripts/stop-all.sh"
