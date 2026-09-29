#!/usr/bin/env python
"""Real Flower smoke test: with the federation running (start-coordinator + 3 hospitals,
or dev-single-host.sh), enqueue one SCREEN and assert three schema-valid replies from
three distinct node ids carrying hospital ids A, B, C (from node config). Prints evidence.
Usage: python scripts/flower-smoke-test.py [state/coordinator] [timeout_s]
"""
import json, sys, time
from pathlib import Path
from domino.coordinator.state import CoordinatorState

sd = Path(sys.argv[1] if len(sys.argv) > 1 else "state/coordinator")
timeout = float(sys.argv[2]) if len(sys.argv) > 2 else 120
cs = CoordinatorState(sd)
before = len(cs.audit_tail(100000))
jid = cs.enqueue("SCREEN", {"reason": "flower-smoke-test"})
print("queued", jid, "waiting for a SCREEN round with 3 replies ...")
t0 = time.time()
while time.time() - t0 < timeout:
    st = cs.load()
    lr = st["flower"].get("last_round") or {}
    aud = cs.audit_tail(100000)[before:]
    replies = [a for a in aud if a.get("direction") == "hospital->coordinator" and a.get("message_type") == "SCREEN_REQUEST" and a.get("status") == "OK"]
    by_h = {}
    for a in replies:
        by_h.setdefault(a["hospital_id"], set()).add(a["src_node_id"])
    if set(by_h) == {"A", "B", "C"} and st["graph"].get("screened_at"):
        nodes = {h: sorted(v) for h, v in by_h.items()}
        assert all(len(v) == 1 for v in nodes.values()), nodes
        assert len({v[0] for v in nodes.values()}) == 3, "node ids must be distinct"
        ev = {"label": "VERIFIED", "flower_run_id": st["flower"]["run_id"], "hospital_to_node": nodes,
              "sample_message_ids": [a["flower_message_id"] for a in replies[:3]],
              "edges": st["graph"]["edges"], "plan": st["plan"] and {k: st["plan"].get(k) for k in ("state", "kind", "order")}}
        print(json.dumps(ev, indent=1))
        Path("evidence").mkdir(exist_ok=True)
        Path("evidence/flower-smoke-latest.json").write_text(json.dumps(ev, indent=1))
        print("SMOKE TEST PASSED: three replies through Flower from three node identities")
        sys.exit(0)
    time.sleep(1)
print("SMOKE TEST FAILED (timeout). last_round:", st["flower"].get("last_round"))
sys.exit(1)
