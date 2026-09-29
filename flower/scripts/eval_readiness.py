#!/usr/bin/env python
"""Measure readiness accuracy on all 12 pairs: keyword rules vs the agent
(retrieval + hospital model), three runs, write the WORST run to
docs/evidence/readiness-eval.json. The projector shows only this number.

Run on a hospital Mac with the model endpoint configured:
  FLWR_RUNTIME_BASE_URL=http://127.0.0.1:11434/v1 FLWR_RUNTIME_API_KEY=ollama uv run python scripts/eval_readiness.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domino_app import hospital, retrieval  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
data = ROOT / "data"
if not (data / "public-donors.json").exists():
    import subprocess

    subprocess.run([sys.executable, str(ROOT / "scripts" / "split-data.py")], check=True)

expected = {}
for h in ("alder", "harbor", "riverbend"):
    for p in json.loads((data / h / "records.json").read_text())["pairs"]:
        expected[p["id"]] = (h, p, p["patient"].get("expected_readiness", "ready"))

kw_ok = sum(1 for pid, (h, p, exp) in expected.items() if hospital.keyword_rules(p)["readiness"] == exp)
runs = []
for r in range(3):
    ok = 0
    for pid, (h, p, exp) in expected.items():
        idx = retrieval.build(data / h / "docs")
        got = hospital.readiness_for(pid, p, idx, h)
        ok += got["readiness"] == exp
    runs.append(ok)
    print(f"run {r + 1}: agent {ok}/12")
worst = min(runs)
out = {"keyword": {"correct": kw_ok, "total": 12}, "agent_runs": runs, "correct": worst, "total": 12,
       "model": hospital.llm.HOSPITAL_MODEL, "note": "worst of 3 runs; measured, never hardcoded"}
ev = ROOT.parent / "docs" / "evidence"
ev.mkdir(parents=True, exist_ok=True)
(ev / "readiness-eval.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out))
