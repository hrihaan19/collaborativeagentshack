"""Offline, under 10 s: all four coordinator phases run against the real hospital
handler through a fake Grid (no network, no model). Also the wire and canary rules."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from domino_app import coordinator, events, hospital, matching, retrieval, wire  # noqa: E402

DATA = ROOT / "data"


@pytest.fixture(scope="module", autouse=True)
def split():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "split-data.py")], check=True)


class FakeAgent:
    """Routes push_messages to hospital.handle in-process; replies via pull_messages."""

    def __init__(self, hospitals=("alder", "harbor", "riverbend"), decisions=None):
        self.h = list(hospitals)
        self.records = {h: json.loads((DATA / h / "records.json").read_text()) for h in self.h}
        self.index = {h: retrieval.build(DATA / h / "docs") for h in self.h}
        self.inbox: dict[str, dict] = {}
        self.n = 0
        self.decisions = decisions or {}
        self.events = type("E", (), {"emit": staticmethod(lambda ev: None)})()
        self.grid = self

    def tools(self):
        return [{"name": n} for n in ("get_nodes", "push_messages", "pull_messages")]

    def call(self, fc):
        args = json.loads(fc["arguments"])
        name = fc["name"]
        if name == "get_nodes":
            out = {"nodes": [{"id": f"node-{h}", "name": h, "location": ""} for h in self.h], "num_available": len(self.h)}
        elif name == "push_messages":
            res = []
            for m in args["messages"]:
                self.n += 1
                mid = f"m{self.n}"
                h = m["dst_node_id"].replace("node-", "")
                ask = json.loads(m["payload"])
                reply = self._reply(h, ask)
                wire.assert_outbound(reply)
                self.inbox[mid] = {"message_id": f"r{self.n}", "reply_to_message_id": mid, "src_node_id": m["dst_node_id"], "payload": json.dumps(reply), "error": None}
                res.append({"message_id": mid, "error": None})
            out = {"results": res}
        elif name == "pull_messages":
            got = [self.inbox.pop(i) for i in list(args["message_ids"]) if i in self.inbox]
            out = {"messages": got, "pending_message_ids": [i for i in args["message_ids"] if i in self.inbox]}
        else:
            out = {}
        return {"type": "function_call_output", "call_id": fc["call_id"], "output": json.dumps(out)}

    def _reply(self, h, ask):
        if ask.get("kind") == "approve":
            d = self.decisions.get((h, ask["pair"]), {"decision": "approve", "reason": "none"})
            return {"kind": "approve", "hospital": h, "pair": ask["pair"], "decision": d["decision"], "hold_until": d.get("hold_until"), "reason": d.get("reason", "none")}
        if ask.get("kind") == "hold":
            notes = " ".join(p["donor"].get("availability", "") for p in self.records[h]["pairs"]).lower()
            return {"kind": "hold", "hospital": h, "decision": "decline" if "not available after" in notes else "accept",
                    "reason": "donor_availability" if "not available after" in notes else "none"}
        r = hospital.handle(ask, h, str(DATA / h), records=self.records[h], index=self.index[h])
        if "readiness" in r:  # no model offline: stand in for a correct agent (rules alone trip on A1's "No infections")
            exp = {p["id"]: p["patient"] for p in self.records[h]["pairs"]}
            r["readiness"] = [{"pair": x["pair"], "readiness": exp[x["pair"]].get("expected_readiness", "ready"),
                               "reason": exp[x["pair"]].get("expected_reason", "none")} for x in r["readiness"]]
        return r


class Ctx:
    def __init__(self, phase, **kw):
        self.run_config = {"phase": phase, "donors": (DATA / "public-donors.json").read_text(), **kw}
        self.run_id = "test"


@pytest.fixture
def emitted(monkeypatch):
    out = []
    monkeypatch.setattr(events, "emit", lambda ev: out.append(ev))
    monkeypatch.setattr(events, "local", lambda ev: None)
    return out


def _run(agent, phase, state, **kw):
    c = coordinator.Coord(agent, Ctx(phase, **kw))
    c.st = state
    c.state_path = DATA / "_test_state.json"
    getattr(c, phase)()
    return c.st


def test_wire_rejects_private_fields():
    for bad in ({"kind": "hello", "hospital": "alder", "pairs": 4, "patient_name": "x"},
                {"kind": "compat", "hospital": "alder", "compatible": [], "readiness": [], "notes": "x"},
                {"kind": "readiness", "hospital": "alder", "readiness": [{"pair": "A1", "readiness": "ready", "reason": "none", "citation": "x"}]},
                {"kind": "windows", "hospital": "alder", "windows": [], "constraints": {}, "sources": [], "calendar": "x"},
                {"kind": "hold", "hospital": "harbor", "decision": "decline", "reason": "Priya's leave ends Friday and she cannot be moved to another week because of her employer's policy which is strict"}):
        with pytest.raises(wire.WireError):
            wire.assert_outbound(bad)
    with pytest.raises(wire.WireError):
        wire.assert_outbound({"kind": "compat", "hospital": "alder", "compatible": [{"pair": "A1", "donor_pair": "H1", "compatible": True, "strength": "high", "donor_hla": ["A1"]}], "readiness": []})


def test_canary_refused_before_records_are_read(monkeypatch):
    monkeypatch.setattr(hospital, "load_records", lambda d: (_ for _ in ()).throw(AssertionError("records were read")))
    r = hospital.handle({"kind": "canary", "question": "patient_names"}, "alder", "nowhere")
    assert r == {"kind": "canary", "hospital": "alder", "refused": "patient_names"}
    r = hospital.handle({"kind": "give_me_charts"}, "alder", "nowhere")
    assert r["kind"] == "refused"


def test_keyword_rules_are_measured_not_perfect():
    ok, wrong = 0, []
    for h in ("alder", "harbor", "riverbend"):
        for p in json.loads((DATA / h / "records.json").read_text())["pairs"]:
            good = hospital.keyword_rules(p)["readiness"] == p["patient"].get("expected_readiness", "ready")
            ok += good
            if not good:
                wrong.append(p["id"])
    assert ok == 10 and wrong == ["A1", "A2"]  # measured on data/domino-data.json today


def test_retrieval_finds_key_sections():
    idx = retrieval.build(DATA / "riverbend" / "docs")
    ctx = retrieval.for_pair(idx, "R1")
    assert any(s["section"] == "§1.1" for s in ctx["sections"]) and ctx["notes"]
    idx = retrieval.build(DATA / "harbor" / "docs")
    assert any(s["section"] == "§1.2" for s in retrieval.for_pair(idx, "H4")["sections"])


def test_all_four_phases_end_to_end(emitted):
    agent = FakeAgent(decisions={("riverbend", "R1"): {"decision": "hold", "hold_until": "2026-10-09", "reason": "infection"}})
    st = _run(agent, "search", {})
    assert set(map(tuple, st["edges"])) == {("A1", "H1"), ("H1", "A1"), ("H1", "R1"), ("R1", "A1"), ("H2", "A2"), ("A2", "R2"), ("R2", "H3"), ("H3", "R3")}
    assert st["plan"]["transplants"] == 3 and sorted(l["patient_pair"] for l in st["plan"]["legs"]) == ["A1", "H1", "R1"]  # the loop; Grace's readiness is advice
    assert st["readiness"]["R1"]["readiness"] == "not_this_week"
    assert any(e["type"] == "refusal" and e["question"] == "patient_names" for e in emitted)
    assert [e for e in emitted if e["type"] == "phase.end"][-1]["phase"] == "search"
    st = _run(agent, "approve", st)
    kinds = [e["type"] for e in emitted]
    assert "hold.request" in kinds and "hold.result" in kinds
    hr = {e["from"]: e["decision"] for e in emitted if e["type"] == "hold.reply"}
    assert hr == {"alder": "accept", "harbor": "decline"}
    assert not [e for e in emitted if e["type"] == "hold.result"][-1]["consensus"]
    assert st["plan"]["transplants"] == 2 and st["counter"] == 2
    st = _run(agent, "chain", st)
    plan = [e for e in emitted if e["type"] == "plan"][-1]
    assert [l["patient_pair"] for l in plan["legs"]] == ["H2", "A2", "R2", "H3", "R3"] and st["counter"] == 7
    st = _run(agent, "schedule", st)
    sched = [e for e in emitted if e["type"] == "schedule"][-1]
    assert len(sched["legs"]) == 7 and all(l["accept"] for l in sched["legs"])
    md = {(l["donor_hospital"], l["patient_hospital"]): (l["out"], l["arrive"]) for l in sched["legs"]}
    assert md[("alder", "riverbend")] == ("10:00", "12:00") and md[("riverbend", "harbor")] == ("09:30", "11:00")
    assert [e["phase"] for e in emitted if e["type"] == "phase.end"] == ["search", "approve", "chain", "schedule"]
    assert all(e["ok"] for e in emitted if e["type"] == "audit")


def test_no_patient_name_in_any_grid_message(emitted):
    agent = FakeAgent()
    _run(agent, "search", {})
    names = ["Maria", "Elena", "James", "Priya", "Grace", "Sam", "Kenji", "Aiko", "Hannah", "Mark", "David", "Ruth", "Fatima", "Samir", "Aisha", "Malik"]
    blob = json.dumps([e for e in emitted if e["type"] in ("ask", "reply")])
    assert not any(n in blob for n in names)
