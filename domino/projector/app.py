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

STATE: dict = {"decisions": {}, "give": None, "hold_replies": {}, "beat": 0, "mode": "scripted", "seq": 0, "local_events": []}

# ---------------------------------------------------------------- live bridge
import re
import subprocess
import threading

FLOWER_DIR = Path(os.environ.get("DOMINO_FLOWER_DIR", str(Path(__file__).resolve().parents[2] / "flower")))
SUPERLINK = os.environ.get("DOMINO_SUPERLINK", "supergrid")
LIVE: dict = {"proc": None, "events": [], "phase": None, "run_id": None, "started_at": None, "last_event_at": None, "tail": [], "log": None}
RUNS = Path(os.environ.get("DOMINO_RUNS_DIR", "runs"))


def _reader(proc, logf):
    for raw in proc.stdout:
        line = raw.decode("utf-8", "ignore").rstrip()
        logf.write(line + "\n"); logf.flush()
        LIVE["tail"] = (LIVE["tail"] + [line])[-30:]
        m = re.search(r"run[ _]?(?:ID)?[ =:]*(\d{6,})", line, re.I)
        if m and not LIVE["run_id"]:
            LIVE["run_id"] = m.group(1)
        if "DOMINO_EVENT " in line:
            try:
                ev = json.loads(line.split("DOMINO_EVENT ", 1)[1])
            except ValueError:
                continue
            if ev.get("type") == "run.start" and LIVE["run_id"]:
                ev["run_id"] = LIVE["run_id"]
            LIVE["events"].append(ev)
            LIVE["last_event_at"] = time.time()
    LIVE["tail"].append(f"[flwr run exited {proc.wait()}]")


@app.post("/api/live/{phase}")
def live_start(phase: str) -> JSONResponse:
    """Spawn one `flwr run` for a phase inside flower/. Real Grid messages only."""
    if phase not in ("search", "approve", "chain", "schedule"):
        raise HTTPException(400, "phase")
    if LIVE["proc"] is not None and LIVE["proc"].poll() is None:
        return JSONResponse({"already": True, "phase": LIVE["phase"], "run_id": LIVE["run_id"]})
    donors = (FLOWER_DIR / "data" / "public-donors.json")
    if not donors.exists():
        subprocess.run([os.environ.get("PYTHON", "python3"), str(FLOWER_DIR / "scripts" / "split-data.py")], check=False)
    dn = json.dumps(json.loads(donors.read_text()), separators=(",", ":")) if donors.exists() else "[]"
    alt = json.dumps({"pair": "ALT", **{k: v for k, v in json.loads((DATA / "domino-data.json").read_text())["altruist"].items() if k != "name"}}, separators=(",", ":")).replace('"blood"', '"donor_blood"').replace('"hla"', '"donor_hla"')
    cfg = f"phase=\"{phase}\" donors='{dn}' altruist='{alt}' console_port={int(os.environ.get('PROJECTOR_PORT', '7800'))}"
    cmd = [os.environ.get("FLWR_BIN", "flwr"), "run", ".", SUPERLINK, "--run-config", cfg, "--stream"]
    RUNS.mkdir(exist_ok=True)
    logf = open(RUNS / f"{time.strftime('%Y%m%d-%H%M%S')}-{phase}.log", "a", encoding="utf-8")
    LIVE.update({"events": [] if phase == "search" else LIVE["events"], "phase": phase, "run_id": None, "started_at": time.time(), "last_event_at": None, "tail": []})
    LIVE["proc"] = subprocess.Popen(cmd, cwd=str(FLOWER_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    threading.Thread(target=_reader, args=(LIVE["proc"], logf), daemon=True).start()
    return JSONResponse({"started": True, "phase": phase, "cmd": " ".join(cmd[:4]) + " …"})


@app.get("/api/live/events")
def live_events(since: int = 0) -> JSONResponse:
    p = LIVE["proc"]
    return JSONResponse({"events": LIVE["events"][since:], "next": len(LIVE["events"]), "phase": LIVE["phase"], "run_id": LIVE["run_id"],
                         "alive": p is not None and p.poll() is None, "double": os.path.basename(os.environ.get("FLWR_BIN", "flwr")) != "flwr", "started_at": LIVE["started_at"], "last_event_at": LIVE["last_event_at"],
                         "tail": LIVE["tail"][-8:]})


@app.post("/events")
async def hospital_local_event(ev: dict) -> JSONResponse:
    """Hospital-only events from the agent on THIS Mac (evidence, thoughts, refusals, memory). Never via the Grid."""
    STATE["local_events"] = (STATE["local_events"] + [{**ev, "at": time.time()}])[-200:]
    return JSONResponse({"ok": True})


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
