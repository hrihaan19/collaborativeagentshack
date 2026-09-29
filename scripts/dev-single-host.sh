#!/usr/bin/env bash
# SINGLE-HOST ONLY: coordinator + three SuperNodes (ports 9094-9096) + three consoles (8010-8012) on one machine.
# Proves the Flower plumbing and the demo flow; does NOT prove cross-machine networking.
. "$(dirname "$0")/common.sh"
export COORDINATOR_HOST=127.0.0.1
banner "SINGLE-HOST ONLY dev federation on 127.0.0.1"
scripts/start-coordinator.sh
sleep 2
scripts/start-hospital.sh A 9094 8010
scripts/start-hospital.sh B 9095 8011
scripts/start-hospital.sh C 9096 8012
echo "SINGLE-HOST ONLY federation up. Dashboard http://127.0.0.1:${DASHBOARD_PORT}/  consoles 8010/8011/8012"
