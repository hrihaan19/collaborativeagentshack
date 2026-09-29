#!/usr/bin/env bash
# Shared by all start scripts. Sourced, not executed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [ -f .env ]; then set -a; . ./.env; set +a; fi
: "${COORDINATOR_HOST:=127.0.0.1}"
: "${SUPERLINK_FLEET_PORT:=9092}"
: "${SUPERLINK_CONTROL_PORT:=9093}"
: "${COORDINATOR_API_PORT:=8001}"
: "${DASHBOARD_PORT:=8501}"
: "${QR_PORT:=8020}"
: "${HOSPITAL_CONSOLE_PORT:=8010}"
: "${SUPERNODE_PORT:=9094}"
: "${POLL_SECONDS:=5}"
: "${ROUND_TIMEOUT:=60}"
: "${PUBLIC_URL:=http://${COORDINATOR_HOST}:${QR_PORT}}"
export COORDINATOR_HOST SUPERLINK_FLEET_PORT SUPERLINK_CONTROL_PORT COORDINATOR_API_PORT DASHBOARD_PORT QR_PORT \
       HOSPITAL_CONSOLE_PORT SUPERNODE_PORT POLL_SECONDS ROUND_TIMEOUT PUBLIC_URL
if [ -f .venv/bin/activate ]; then . .venv/bin/activate; fi
export FLWR_HOME="${FLWR_HOME:-$ROOT/state/flwr-home}"
mkdir -p "$FLWR_HOME" state logs
PINNED="1.39.0"
INSTALLED="$(python -c 'import flwr;print(flwr.__version__)' 2>/dev/null || echo none)"
if [ "$INSTALLED" != "$PINNED" ]; then
  echo "!! flwr $INSTALLED installed, pinned $PINNED. Run: pip install -e ." >&2; exit 1
fi
# flwr 1.39 reads SuperLink connections from $FLWR_HOME/config.toml
write_flwr_config() {
  cat > "$FLWR_HOME/config.toml" <<TOML
[superlink]
default = "domino"

[superlink.domino]
address = "${COORDINATOR_HOST}:${SUPERLINK_CONTROL_PORT}"
insecure = true
TOML
}
banner() { echo "=================================================================="; echo "  DOMINO  |  SYNTHETIC DEMO - NOT A CLINICAL MATCHING TOOL  |  INSECURE DEV MODE (--insecure)"; echo "  $*"; echo "=================================================================="; }
