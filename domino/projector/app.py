"""Domino projector / console / give server (FastAPI). Port 7800.

Scripted mode runs entirely in the browser from /api/story; this server only
holds the surgeon decisions (console -> projector), the /give press, and the
map + data files. No CDN, no tiles, no runtime fonts.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from domino.story import data as D
from domino.story.script import build

STATIC = Path(__file__).parent / "static"
DATA = Path(os.environ.get("DOMINO_DATA_DIR", "data"))
app = FastAPI(title="Domino projector - synthetic data, fictional hospitals")

STATE: dict = {"decisions": {}, "give": None, "hold_replies": {}, "beat": 0, "mode": "scripted", "seq": 0}


class Decision(BaseModel):
    hospital: str = Field(max_length=16)
    pair: str = Field(max_length=8)
    decision: str = Field(pattern="^(approve|not_this_week|decline|hold)$")
    hold_until: str | None = Field(default=None, max_length=10)
    reason: str = Field(default="none", max_length=32)


class HoldReply(BaseModel):
    hospital: str = Field(max_length=16)
    decision: str = Field(pattern="^(accept|decline)$")
    reason: str = Field(default="none", max_length=32)


@app.get("/api/story")
def story(mode: str = "scripted") -> JSONResponse:
    return JSONResponse(build(mode))


@app.get("/api/map")
def norcal_map() -> JSONResponse:
    p = DATA / "norcal-map.json"
    if not p.exists():
        raise HTTPException(404, "norcal-map.json missing")
    return JSONResponse(json.loads(p.read_text()))


@app.get("/api/state")
def state() -> JSONResponse:
    return JSONResponse(STATE)


@app.post("/api/beat")
def set_beat(beat: int, mode: str = "scripted") -> JSONResponse:
    STATE["beat"], STATE["mode"], STATE["seq"] = beat, mode, STATE["seq"] + 1
    if beat < 6:  # a fresh run of the story clears the human inputs
        STATE["decisions"], STATE["give"], STATE["hold_replies"] = {}, None, {}
    return JSONResponse(STATE)


@app.post("/api/decision")
def decision(d: Decision) -> JSONResponse:
    STATE["decisions"][d.pair] = {**d.model_dump(), "at": time.time()}
    _remember(d)
    return JSONResponse(STATE["decisions"][d.pair])


@app.post("/api/hold-reply")
def hold_reply(r: HoldReply) -> JSONResponse:
    STATE["hold_replies"][r.hospital] = {**r.model_dump(), "at": time.time()}
    return JSONResponse(STATE["hold_replies"][r.hospital])


@app.post("/api/give")
def give() -> JSONResponse:
    STATE["give"] = time.time()
    return JSONResponse({"ok": True})


@app.post("/api/reset")
def reset() -> JSONResponse:
    STATE.update({"decisions": {}, "give": None, "hold_replies": {}, "beat": 0, "seq": STATE["seq"] + 1})
    return JSONResponse(STATE)


def _remember(d: Decision) -> None:
    """Memory loop: append the surgeon's decision to that hospital's decisions.md."""
    p = Path(os.environ.get("DOMINO_DOCS_DIR", "state/docs")) / d.hospital / "decisions.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"\n## {time.strftime('%Y-%m-%d')} · {d.pair} · {d.decision}" + (f" until {d.hold_until}" if d.hold_until else "") + f" · reason: {d.reason}\n")


@app.get("/api/console/{hospital}")
def console_data(hospital: str) -> JSONResponse:
    if hospital not in D.HOSPITALS:
        raise HTTPException(404)
    s = build()
    pairs = [dict(id=pid, **v) for pid, v in s["names"].items() if v["hospital"] == hospital]
    for p in pairs:
        p["readiness"] = s["readiness"][p["id"]]
        p["evidence"] = D.EVIDENCE.get(p["id"], [])
    return JSONResponse({"hospital": hospital, **D.HOSPITALS[hospital], "pairs": pairs, "state": STATE,
                         "pending_approval": STATE["beat"] == 6 and hospital == "riverbend" and "R1" not in STATE["decisions"],
                         "pending_hold": STATE["beat"] == 6 and hospital != "riverbend" and STATE["decisions"].get("R1", {}).get("decision") == "hold" and hospital not in STATE["hold_replies"],
                         "hold_suggestion": {"alder": {"decision": "accept", "reason": "none", "private": "Elena is flexible through 10/31"},
                                             "harbor": {"decision": "decline", "reason": "donor_availability", "private": "Priya's leave covers surgery only on or before 10/02"}}.get(hospital)})


@app.get("/", response_class=HTMLResponse)
@app.get("/projector", response_class=HTMLResponse)
def projector() -> str:
    return (STATIC / "projector.html").read_text(encoding="utf-8")


@app.get("/console/{hospital}", response_class=HTMLResponse)
def console(hospital: str) -> str:
    if hospital not in D.HOSPITALS:
        raise HTTPException(404)
    return (STATIC / "console.html").read_text(encoding="utf-8").replace("{{HOSPITAL}}", hospital)


@app.get("/give", response_class=HTMLResponse)
def give_page() -> str:
    return (STATIC / "give.html").read_text(encoding="utf-8")


@app.get("/api/qr")
def qr_svg() -> HTMLResponse:
    """QR for /give, rendered locally (segno). PUBLIC_URL or GIVE_URL from .env."""
    import segno

    url = os.environ.get("GIVE_URL") or (os.environ.get("PUBLIC_URL", "http://127.0.0.1:7800").rstrip("/") + "/give")
    return HTMLResponse(segno.make(url, error="m").svg_inline(scale=6, dark="#111", light="#fff"), media_type="image/svg+xml")


@app.get("/api/eval")
def readiness_eval() -> JSONResponse:
    """Measured agent score; never hardcoded. 404 until scripts/eval_readiness.py has run."""
    p = Path("docs/evidence/readiness-eval.json")
    if not p.exists():
        raise HTTPException(404, "not measured yet")
    return JSONResponse(json.loads(p.read_text()))


@app.get("/favicon.ico")
def favicon() -> JSONResponse:
    return JSONResponse({}, status_code=204)
