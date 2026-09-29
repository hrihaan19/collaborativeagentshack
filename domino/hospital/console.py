"""Hospital LOCAL console. Binds 127.0.0.1 only. This is the human gate.

Everything on this page is private to the hospital machine (fictional names
included). The only thing that ever leaves is via the Flower ClientApp.
No AI code path calls /approve: the local model (if any) can only *suggest*
review; it cannot set AVAILABLE, clear a HOLD, or approve a plan.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from domino import BANNER, hospital_label
from domino.hospital import llm, logic
from domino.hospital.store import HospitalStore, default_state_dir
from domino.statefiles import read_jsonl

HID = os.environ.get("DOMINO_HOSPITAL_ID", "A").upper()
STORE = HospitalStore(HID, Path(os.environ.get("DOMINO_HOSPITAL_STATE_DIR") or default_state_dir(HID)))
STORE.seed()
app = FastAPI(title=f"Domino hospital console {HID} - {BANNER}")


class NoteIn(BaseModel):
    vertex: str = Field(max_length=32)
    text: str = Field(max_length=2000)


@app.get("/api/state")
def state() -> JSONResponse:
    recs = STORE.records()
    view = []
    for tok, r in sorted(recs.items()):
        view.append({
            "vertex": tok, "kind": r["kind"], "availability": STORE.availability(r), "record_version": r["record_version"],
            "hold": r["hold"], "notes": r["notes"], "reviewed_note_count": r["reviewed_note_count"], "agent_mode": r.get("agent_mode", "RULE"),
            "recipient": r.get("recipient"), "donor": r.get("donor"),
        })
    return JSONResponse({
        "banner": BANNER, "hospital_id": HID, "label": hospital_label(HID), "records": view,
        "plans": STORE.plans(), "local_search_exchanges": logic.local_search_count(STORE),
        "log": read_jsonl(STORE.log_path, last=25), "llm": llm.status(),
        "network": "outbound Flower connection to SuperLink only; ZERO inbound ports; INSECURE DEV MODE",
    })


@app.post("/api/note")
def add_note(n: NoteIn) -> JSONResponse:
    if n.vertex not in STORE.records():
        raise HTTPException(404, "unknown vertex")
    # Rule runs regardless of the model: a new note => REVIEW_REQUIRED.
    suggestion = llm.suggest_review(n.text)  # {"mode": ..., "suggest_review": bool|None, "reason_code": ...}
    mode = suggestion["mode"]
    rec = STORE.add_note(n.vertex, n.text, agent_mode=mode)
    return JSONResponse({"availability": STORE.availability(rec), "record_version": rec["record_version"], "agent": suggestion})


@app.post("/api/hold/{vertex}")
def hold(vertex: str) -> JSONResponse:
    if vertex not in STORE.records():
        raise HTTPException(404, "unknown vertex")
    rec = STORE.set_hold(vertex, True)
    return JSONResponse({"availability": STORE.availability(rec), "record_version": rec["record_version"]})


@app.post("/api/clear-hold/{vertex}")
def clear_hold(vertex: str) -> JSONResponse:
    if vertex not in STORE.records():
        raise HTTPException(404, "unknown vertex")
    rec = STORE.set_hold(vertex, False)
    return JSONResponse({"availability": STORE.availability(rec), "record_version": rec["record_version"]})


@app.post("/api/reviewed/{vertex}")
def reviewed(vertex: str) -> JSONResponse:
    if vertex not in STORE.records():
        raise HTTPException(404, "unknown vertex")
    rec = STORE.mark_reviewed(vertex)
    return JSONResponse({"availability": STORE.availability(rec), "record_version": rec["record_version"]})


@app.post("/api/approve/{plan_id}")
def approve(plan_id: str) -> JSONResponse:
    """HUMAN GATE. Signs the exact plan hash with this hospital's Ed25519 key."""
    if plan_id not in STORE.plans():
        raise HTTPException(404, "plan not known at this hospital")
    p = STORE.plans()[plan_id]
    recs = STORE.records()
    for tok, ver in p.get("record_versions", {}).items():
        if tok in recs and (recs[tok]["record_version"] != ver or STORE.availability(recs[tok]) != "AVAILABLE"):
            raise HTTPException(409, f"{tok} changed or not AVAILABLE since the plan was made; wait for a re-solve")
    sig = logic.sign_plan_locally(STORE, plan_id)
    return JSONResponse({"signed": True, "plan_hash": sig.plan_hash, "signature_hex": sig.signature_hex})


@app.post("/api/refuse/{plan_id}")
def refuse(plan_id: str) -> JSONResponse:
    if plan_id not in STORE.plans():
        raise HTTPException(404, "plan not known")
    STORE.set_approval(plan_id, False, None)
    return JSONResponse({"refused": True})


@app.post("/api/activate/{donor_token}")
def activate(donor_token: str) -> JSONResponse:
    ok, code = STORE.activate_donor(donor_token)
    return JSONResponse({"ok": ok, "code": code})


@app.post("/api/reset")
def reset() -> JSONResponse:
    STORE.reset()
    return JSONResponse({"reset": True})


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (Path(__file__).parent / "console.html").read_text(encoding="utf-8")
