#!/usr/bin/env bash
# Reset to the pre-demo state: hospitals re-seed (locally), coordinator clears plan/graph (via a job to the ServerApp).
. "$(dirname "$0")/common.sh"
scripts/seed-demo.sh "$@"
if [ -d state/coordinator ]; then
  python -c "from domino.coordinator.state import CoordinatorState; from pathlib import Path; CoordinatorState(Path('state/coordinator')).enqueue('RESET'); print('coordinator RESET job queued')"
fi
