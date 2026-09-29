#!/usr/bin/env python
"""TEST DOUBLE for `flwr run` — NOT a Flower run. Runs one coordinator phase
against the offline FakeAgent (in-process hospital handlers) and prints the
same `DOMINO_EVENT {json}` lines a real run prints, so the projector's live
pipeline can be exercised without SuperGrid. The projector labels such runs
"LIVE-DOUBLE", never "LIVE". Use: FLWR_BIN=scripts/fake-flwr.py
"""
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
cfg = " ".join(sys.argv)
phase = re.search(r'phase="(\w+)"', cfg).group(1) if re.search(r'phase="(\w+)"', cfg) else "search"
print(f"[fake-flwr] TEST DOUBLE, not a Flower run. phase={phase}", flush=True)
print("Successfully started run 000000000000000000 (DOUBLE)", flush=True)

from test_offline import DATA, Ctx, FakeAgent  # noqa: E402
from domino_app import coordinator, events  # noqa: E402

state_path = ROOT / "data" / "_double_state.json"
st = json.loads(state_path.read_text()) if state_path.exists() and phase != "search" else {}
events.local = lambda ev: None
_emit = events.emit


def slow_emit(ev):
    _emit(ev)
    time.sleep(0.35)


events.emit = slow_emit
import subprocess  # noqa: E402

subprocess.run([sys.executable, str(ROOT / "scripts" / "split-data.py")], check=True, capture_output=True)
agent = FakeAgent(decisions={("riverbend", "R1"): {"decision": "hold", "hold_until": "2026-10-09", "reason": "infection"}})
if phase == "search":
    pass
c = coordinator.Coord(agent, Ctx(phase))
c.st = st
c.state_path = state_path
getattr(c, phase)()
c.save()
