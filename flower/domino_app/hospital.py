"""Hospital agent: runs on the hospital's Mac when a Grid message arrives.

Catalog: hello, compat, readiness, canary, approve, hold, windows, leg.
Anything else -> {"refused": "<question>"}. Policy check first; refusals happen
before any record is read. Everything that leaves goes through wire.assert_outbound.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path

from domino_app import events, llm, matching, prompts, retrieval, wire

CATALOG = {"hello", "compat", "readiness", "canary", "approve", "hold", "windows", "leg"}
READINESS_KEYWORDS = {"infection": "infection", "pneumonia": "admission", "admitted": "admission", "travel": "travel",
                      "traveling": "travel", "pending": "labs_pending", "clearance": "cardiac_clearance"}


def load_records(data_dir: str) -> dict:
    return json.loads((Path(data_dir) / "records.json").read_text())


def run(agent, context) -> None:
    h = str(context.node_config.get("hospital", "")).lower()
    data_dir = str(context.node_config.get("data_dir", ""))
    port = int(context.run_config.get("console_port", 7800)) if hasattr(context, "run_config") else 7800
    events.bind(agent, port)
    try:
        msg = json.loads(agent.prompt)
    except (TypeError, ValueError):
        msg = {"payload": agent.prompt}
    try:
        ask = json.loads(msg.get("payload", agent.prompt)) if isinstance(msg, dict) else {}
    except (TypeError, ValueError):
        ask = {}
    reply = handle(ask, h, data_dir)
    wire.assert_outbound(reply)
    from domino_app.agent_app import grid

    grid(agent, "push_reply_message", payload=json.dumps(reply))


def handle(ask: dict, h: str, data_dir: str, records: dict | None = None, index=None, console_port: int = 7800) -> dict:
    kind = ask.get("kind")
    # 1) policy: refuse before any record is read
    if kind not in CATALOG:
        events.local({"type": "refusal", "from": h, "question": str(kind)[:40]})
        return {"kind": "refused", "hospital": h, "refused": str(kind)[:40]}
    if kind == "canary":
        q = str(ask.get("question", "patient_names"))[:40]
        events.local({"type": "refusal", "from": h, "question": q})
        return {"kind": "canary", "hospital": h, "refused": q}
    try:
        wire.assert_inbound(ask)
    except wire.WireError as e:
        return {"kind": "refused", "hospital": h, "refused": "wire:" + str(e)[:60]}
    # 2) now read this Mac's records
    rec = records or load_records(data_dir)
    pairs = {p["id"]: p for p in rec["pairs"]}
    if kind == "hello":
        return {"kind": "hello", "hospital": h, "pairs": len(pairs)}
    if kind == "compat":
        idx = index or retrieval.build(Path(data_dir) / "docs") if data_dir else None
        compat = []
        for d in ask.get("donors", []):
            for pid, p in pairs.items():
                if d["pair"] == pid:
                    continue
                ok = matching.compatible(d["donor_blood"], d["donor_hla"], p["patient"]["blood"], p["patient"].get("unacceptable_antigens", []))
                if ok:
                    compat.append({"pair": pid, "donor_pair": d["pair"], "compatible": True, "strength": matching.strength(d["donor_blood"], p["patient"]["blood"])})
        ready = [readiness_for(pid, p, idx, h) for pid, p in pairs.items()]
        return {"kind": "compat", "hospital": h, "compatible": compat, "readiness": ready}
    if kind == "readiness":
        idx = index or (retrieval.build(Path(data_dir) / "docs") if data_dir else None)
        return {"kind": "readiness", "hospital": h, "readiness": [readiness_for(pid, p, idx, h) for pid, p in pairs.items()]}
    if kind == "approve":
        return approve(ask, h, console_port)
    if kind == "hold":
        return hold(ask, h, rec, console_port)
    if kind == "windows":
        c = rec.get("constraints", {})
        return {"kind": "windows", "hospital": h, "windows": rec.get("windows", ["Fri AM"]),
                "constraints": {k: c.get(k) for k in ("donor_start_not_before", "organ_arrival_by", "implant_start_by", "max_cold_ischemia_h")},
                "sources": rec.get("sources", [])}
    if kind == "leg":
        c = rec.get("constraints", {})
        p = pairs.get(ask.get("pair", ""), {})
        sens = len(p.get("patient", {}).get("unacceptable_antigens", [])) >= 8
        times = {"out": ask["out"], "arrive": ask["arrive"], "implant": ask["implant"], "cold_h": float(ask["cold_h"])}
        ok, reason = matching.leg_accept(c, times, sens)
        return {"kind": "leg", "hospital": h, "leg": ask["leg"], "accept": ok, "reason": reason}
    return {"kind": "refused", "hospital": h, "refused": str(kind)[:40]}


# ------------------------------------------------------------------ readiness
def keyword_rules(p: dict) -> dict:
    notes = (p["patient"].get("notes", "") or "").lower()
    for kw, reason in READINESS_KEYWORDS.items():
        if kw in notes:
            r = "needs_review" if reason == "cardiac_clearance" else "not_this_week"
            return {"pair": p["id"], "readiness": r, "reason": reason}
    return {"pair": p["id"], "readiness": "ready", "reason": "none"}


def readiness_for(pid: str, p: dict, index, h: str, date: str = "Fri 10/2") -> dict:
    """Retrieval + the hospital model, checked in code; keyword rules as fallback."""
    ctx = retrieval.for_pair(index, pid) if index is not None else {"notes": [], "sections": [], "decisions": [], "sections_total": 0}
    chunks = ctx["notes"] + ctx["sections"] + ctx["decisions"]
    if not chunks:
        chunks = [{"doc": f"{pid}_chart.md", "section": "notes", "text": p["patient"].get("notes", "")}]
    prompt = json.dumps({"pair": pid, "date": date, "chunks": [{"doc": c["doc"], "section": c["section"], "text": c["text"][:1500]} for c in chunks]})
    err = ""
    for attempt in range(2):
        txt, used = llm.ask(llm.HOSPITAL_MODEL, prompts.READINESS_SYSTEM, prompt + (f"\nPrevious error: {err}" if err else ""), budget_s=25)
        j = llm.extract_json(txt)
        if used == "none":
            break
        err = _validate(j, pid, chunks)
        if not err:
            events.local({"type": "evidence", "hospital": h, "pair": pid, "readiness": j["readiness"], "reason": j["reason"],
                          "citations": j["citations"], "retrieved": [s["section"] for s in ctx["sections"]], "notes_read": len(ctx["notes"]),
                          "sections_total": ctx["sections_total"], "model": used, "source": "agent"})
            return {"pair": pid, "readiness": j["readiness"], "reason": j["reason"]}
    r = keyword_rules(p)
    events.local({"type": "evidence", "hospital": h, "pair": pid, "readiness": r["readiness"], "reason": r["reason"], "citations": [],
                  "retrieved": [s["section"] for s in ctx["sections"]], "notes_read": len(ctx["notes"]), "sections_total": ctx["sections_total"],
                  "model": "none", "source": "rules"})
    return r


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _validate(j: dict | None, pid: str, chunks: list[dict]) -> str:
    if not j or j.get("pair") != pid:
        return "pair id missing"
    if j.get("readiness") not in {"ready", "not_this_week", "needs_review"}:
        return "readiness not in enum"
    if j.get("reason") not in {"none", "infection", "admission", "travel", "labs_pending", "cardiac_clearance", "other"}:
        return "reason not in enum"
    cits = j.get("citations") or []
    rule = chart = False
    for c in cits:
        src = next((k for k in chunks if k["doc"] == c.get("doc") and _norm(c.get("quote", "")) in _norm(k["text"])), None)
        if src is None:
            return f"quote not found in {c.get('doc')}"
        if str(src["section"]).startswith("§"):
            rule = True
        else:
            chart = True
    if j["readiness"] != "ready" and not (rule and chart):
        return "non-ready answer needs one rulebook and one chart citation"
    return ""


# ------------------------------------------------------------ human gate
def _console_get(port: int, path: str) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=1.0) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001
        return None


def approve(ask: dict, h: str, port: int, wait_s: int = 90) -> dict:
    pair = ask["pair"]
    events.local({"type": "approval.request", "hospital": h, "pair": pair, "donor_hospital": ask.get("donor_hospital"),
                  "donor_blood": ask.get("donor_blood"), "date": ask.get("date"), "agent_advice": "see console", "reason": "none"})
    t0 = time.time()
    while time.time() - t0 < wait_s:
        st = _console_get(port, "/api/state")
        d = (st or {}).get("decisions", {}).get(pair)
        if d:
            events.local({"type": "memory", "hospital": h, "pair": pair, "text": "decision saved to decisions.md"})
            return {"kind": "approve", "hospital": h, "pair": pair, "decision": d["decision"], "hold_until": d.get("hold_until"), "reason": d.get("reason", "none")}
        time.sleep(1)
    return {"kind": "approve", "hospital": h, "pair": pair, "decision": "not_this_week", "hold_until": None, "reason": "other"}


def hold(ask: dict, h: str, rec: dict, port: int, wait_s: int = 20) -> dict:
    """Agent drafts accept/decline from donor notes; the console human sends it."""
    notes = "\n".join(p.get("donor", {}).get("availability", "") for p in rec["pairs"])
    draft = {"decision": "accept", "reason": "none"}
    txt, used = llm.ask(llm.HOSPITAL_MODEL, prompts.HOLD_SYSTEM, json.dumps({"hold_until": ask.get("hold_until"), "donor_notes": notes[:3000]}), budget_s=15)
    j = llm.extract_json(txt)
    if j and j.get("decision") in {"accept", "decline"}:
        draft = {"decision": j["decision"], "reason": j.get("reason", "none")}
    elif "not available after" in notes.lower() or "on or before" in notes.lower():
        draft = {"decision": "decline", "reason": "donor_availability"}
    events.local({"type": "hold.request", "from": ask.get("from"), "plan": ask.get("plan"), "hold_until": ask.get("hold_until"),
                  "reason": ask.get("reason"), "to": [h], "suggestion": draft})
    t0 = time.time()
    while time.time() - t0 < wait_s:
        st = _console_get(port, "/api/state")
        r = (st or {}).get("hold_replies", {}).get(h)
        if r:
            return {"kind": "hold", "hospital": h, "decision": r["decision"], "reason": r.get("reason", "none")}
        time.sleep(1)
    return {"kind": "hold", "hospital": h, **draft}
