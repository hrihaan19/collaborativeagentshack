#!/usr/bin/env bash
# Projector + consoles + /give on one FastAPI (port 7800). Scripted mode needs no network.
. "$(dirname "$0")/common.sh"
PORT="${PROJECTOR_PORT:-7800}"
banner "Projector http://127.0.0.1:${PORT}/projector · consoles /console/{alder,harbor,riverbend} · /give"
exec uvicorn domino.projector.app:app --host 0.0.0.0 --port "$PORT"
