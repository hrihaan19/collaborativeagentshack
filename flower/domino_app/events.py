"""Event contract plumbing. One JSON object per event.

Coordinator: one stdout line `DOMINO_EVENT {json}` (the bridge parses it) plus
agent.events.emit inside try/except. Hospital-only events: POST to the local
console at 127.0.0.1:<port> with a 0.5 s timeout; never through the Grid.
"""
from __future__ import annotations

import json
import sys
import urllib.request

_agent = None
_console_port = 7800


def bind(agent, console_port: int = 7800) -> None:
    global _agent, _console_port
    _agent, _console_port = agent, int(console_port)


def emit(ev: dict) -> None:
    line = "DOMINO_EVENT " + json.dumps(ev, separators=(",", ":"))
    print(line, flush=True)
    sys.stdout.flush()
    if _agent is not None:
        try:
            _agent.events.emit(ev)
        except Exception:  # noqa: BLE001
            pass


def local(ev: dict) -> None:
    """Hospital-only event (thoughts, evidence, memory). Never crosses the Grid."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{_console_port}/events", data=json.dumps(ev).encode(),
                                     headers={"content-type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=0.5).read()
    except Exception:  # noqa: BLE001
        pass
