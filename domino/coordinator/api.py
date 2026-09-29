"""Coordinator public API + dashboard + QR page (FastAPI, binds 0.0.0.0).

The same app is started three times by start-coordinator.sh (API 8001,
dashboard 8501, QR 8020) - all three read/write the same state dir, so any
port serves any route. The API never talks to a hospital: it only drops jobs
for the Flower ServerApp and reads the state the ServerApp wrote.
"""
from __future__ import annotations

import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from domino import BANNER, FLWR_VERSION, HOSPITALS, hospital_label
from domino.coordinator.state import ACTIVE_STATES, CoordinatorState, default_state_dir

STATE = CoordinatorState(Path(os.environ.get("DOMINO_COORDINATOR_STATE_DIR") or default_state_dir()))
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://127.0.0.1:8020").rstrip("/")
STATIC = Path(__file__).parent / "static"
app = FastAPI(title=f"Domino coordinator - {BANNER}")

TOKEN_TTL_S = 600
ACTIVATION_MIN_GAP_S = float(os.environ.get("ACTIVATION_MIN_GAP_S", "10"))


def _alive(st: dict) -> bool:
    t = st["flower"].get("serverapp_alive_at")
    if not t:
        return False
    return (datetime.now(timezone.utc) - datetime.fromisoformat(t)).total_seconds() < 5


@app.get("/api/state")
def state() -> JSONResponse:
    st = STATE.load()
    ui = STATE.load_ui()
    alive = _alive(st)
    return JSONResponse({
        "banner": BANNER,
        "header": "Three hospitals, three countries, NO SHARED REGISTRY. Coordinator = neutral third party. INSECURE DEV MODE.",
        "flwr_version": FLWR_VERSION,
        "flower": {**st["flower"], "serverapp_alive": alive,
                    "label": ("VERIFIED - Flower ServerApp heartbeat live" if alive else "NOT LIVE - Flower ServerApp heartbeat stale")},
        "hospitals": {h: {**HOSPITALS[h], "label": hospital_label(h), **st["hospitals"].get(h, {}), "connected": h in st["hospitals"]} for h in HOSPITALS},
        "graph": st["graph"],
        "plan": st["plan"],
        "plan_history": st["plan_history"][-5:],
        "reveal": ui["reveal"],
        "events": st["events"][-40:],
        "audit": STATE.audit_tail(40),
        "activation": {"last_activation_at": st["activation"]["last_activation_at"], "activations": st["activation"]["activations"][-5:]},
        "jobs_pending": len(list(STATE.jobs_dir.glob("*.json"))),
    })


@app.post("/api/screen")
def screen() -> JSONResponse:
    return JSONResponse({"job_id": STATE.enqueue("SCREEN", {"reason": "dashboard button", "source": "dashboard"})})


@app.post("/api/poll")
def poll() -> JSONResponse:
    return JSONResponse({"job_id": STATE.enqueue("POLL", {"source": "dashboard"})})


@app.post("/api/reset")
def reset() -> JSONResponse:
    STATE.save_ui(STATE._empty_ui())
    return JSONResponse({"job_id": STATE.enqueue("RESET", {})})


@app.post("/api/reveal")
def reveal() -> JSONResponse:
    """The one clean moment. Marks the current plan as revealed exactly once;
    every open dashboard animates the plan's edges in plan order from plan data."""
    st = STATE.load()
    ui = STATE.load_ui()
    p = st.get("plan")
    if not p or not p.get("plan_id") or p.get("state") not in ACTIVE_STATES | {"APPROVED_FOR_SIMULATED_COORDINATION"}:
        raise HTTPException(409, "no active plan to reveal")
    if ui["reveal"].get("plan_id") == p["plan_id"]:
        return JSONResponse({"already": True, **ui["reveal"]})
    ui["reveal"] = {"plan_id": p["plan_id"], "revealed_at": datetime.now(timezone.utc).isoformat(), "order": p["order"], "edges": p["edges"]}
    STATE.save_ui(ui)
    STATE.audit({"direction": "ui", "message_type": "PLAN_REVEALED", "plan_id": p["plan_id"]})
    return JSONResponse(ui["reveal"])


def _activate(source: str) -> dict:
    ui = STATE.load_ui()
    if time.time() - ui.get("last_request_at", 0) < ACTIVATION_MIN_GAP_S:
        raise HTTPException(429, "rate limited")
    ui["last_request_at"] = time.time()
    STATE.save_ui(ui)
    jid = STATE.enqueue("ACTIVATE", {"donor_token": "N0", "hospital_id": "C", "source": source, "nonce": secrets.token_hex(8)})
    return {"job_id": jid, "queued": "DONOR_ACTIVATION for fixture N0 at Hospital C via Flower; a fresh screening follows"}


@app.post("/api/activate")
def activate_presenter() -> JSONResponse:
    """Presenter button: identical effect to the QR page."""
    return JSONResponse(_activate("presenter-button"))


@app.get("/api/qr-token")
def qr_token() -> JSONResponse:
    """Single-use, short-lived token for the QR page. No personal data."""
    ui = STATE.load_ui()
    now = time.time()
    toks = {t: exp for t, exp in ui["tokens"].items() if exp > now}
    tok = secrets.token_urlsafe(12)
    toks[tok] = now + TOKEN_TTL_S
    ui["tokens"] = toks
    STATE.save_ui(ui)
    return JSONResponse({"token": tok, "url": f"{PUBLIC_URL}/add?token={tok}", "expires_in_s": TOKEN_TTL_S})


@app.post("/api/activate/qr")
def activate_qr(token: str) -> JSONResponse:
    ui = STATE.load_ui()
    exp = ui["tokens"].pop(token, None)  # single use
    STATE.save_ui(ui)
    if not exp or exp < time.time():
        raise HTTPException(403, "token invalid or expired - ask the presenter for a fresh QR")
    return JSONResponse(_activate("qr-page"))


# ------------------------------------------------------------------ pages
@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return (STATIC / "dashboard.html").read_text(encoding="utf-8")


@app.get("/qr", response_class=HTMLResponse)
def qr_page() -> str:
    import segno

    t = qr_token().body.decode()
    import json

    info = json.loads(t)
    svg = segno.make(info["url"], error="m").svg_inline(scale=8, dark="#111", light="#fff")
    html = (STATIC / "qr.html").read_text(encoding="utf-8")
    return html.replace("{{SVG}}", svg).replace("{{URL}}", info["url"]).replace("{{TTL}}", str(TOKEN_TTL_S // 60))


@app.get("/add", response_class=HTMLResponse)
def add_page(token: str = "") -> str:
    html = (STATIC / "add.html").read_text(encoding="utf-8")
    return html.replace("{{TOKEN}}", token)


@app.get("/favicon.ico")
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/healthz")
def healthz(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "role": os.environ.get("DOMINO_ROLE", "api")})
