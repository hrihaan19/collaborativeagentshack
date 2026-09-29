"""Coordinator state (file-backed, shared by the ServerApp and the API).

Plan state machine:
  (none) --SCREEN--> NO_FEASIBLE_EXCHANGE | PROPOSED
  PROPOSED --all hospitals PLAN_ACK--> AWAITING_APPROVALS
  AWAITING_APPROVALS --REVIEW_REQUIRED on an involved vertex--> REVIEW_PENDING
  REVIEW_PENDING --clinician marks reviewed (vertex AVAILABLE again)--> AWAITING_APPROVALS (approvals cleared)
  any active --HOLD / record change on involved vertex / REFUSAL--> INVALIDATED --re-solve-->
  AWAITING_APPROVALS --3 verified signatures + final re-query OK--> APPROVED_FOR_SIMULATED_COORDINATION

Every graph shown on the dashboard is read from this file; nothing is scripted.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from domino.coordinator.solver import Plan
from domino.protocol import now_iso
from domino.statefiles import append_jsonl, read_json, read_jsonl, write_json

ACTIVE_STATES = {"PROPOSED", "AWAITING_APPROVALS", "REVIEW_PENDING"}


def default_state_dir() -> Path:
    env = os.environ.get("DOMINO_COORDINATOR_STATE_DIR")
    return Path(env) if env else Path.cwd() / "state" / "coordinator"


class CoordinatorState:
    def __init__(self, state_dir: Path):
        self.dir = Path(state_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "state.json"
        self.audit_path = self.dir / "audit.jsonl"
        self.jobs_dir = self.dir / "jobs"
        self.jobs_dir.mkdir(exist_ok=True)

    # ------------------------------------------------------------ load/save
    def load(self) -> dict:
        return read_json(self.path, self._empty())

    def save(self, st: dict) -> None:
        st["updated_at"] = now_iso()
        write_json(self.path, st)

    @staticmethod
    def _empty() -> dict:
        return {
            "flower": {"run_id": None, "nodes": {}, "serverapp_alive_at": None, "mode": "IMPLEMENTED-UNVERIFIED"},
            "hospitals": {},  # hospital_id -> {node_id, public_key_hex, last_seen, agent_mode}
            "graph": {"vertices": {}, "edges": [], "screened_at": None, "run_id": None},
            "plan": None,
            "plan_history": [],
            "events": [],
            "reveal": {"plan_id": None, "revealed_at": None},
            "activation": {"tokens": {}, "last_activation_at": None, "activations": []},
        }

    # --------------------------------------------------------------- events
    def event(self, st: dict, kind: str, detail: dict | None = None) -> None:
        st.setdefault("events", []).append({"at": now_iso(), "kind": kind, **(detail or {})})
        st["events"] = st["events"][-200:]

    def audit(self, record: dict) -> None:
        append_jsonl(self.audit_path, {"at": now_iso(), **record})

    def audit_tail(self, n: int = 60) -> list[dict]:
        return read_jsonl(self.audit_path, last=n)

    # ----------------------------------------------------------------- jobs
    def enqueue(self, kind: str, payload: dict | None = None) -> str:
        jid = f"{now_iso().replace(':', '')}-{uuid.uuid4().hex[:8]}"
        write_json(self.jobs_dir / f"{jid}.json", {"job_id": jid, "kind": kind, "payload": payload or {}, "created_at": now_iso()})
        return jid

    def next_job(self) -> dict | None:
        files = sorted(self.jobs_dir.glob("*.json"))
        if not files:
            return None
        job = read_json(files[0], None)
        files[0].unlink(missing_ok=True)
        return job

    # ----------------------------------------------------------------- plan
    def set_plan(self, st: dict, plan: Plan | None, run_id: str) -> None:
        if st.get("plan") and st["plan"].get("state") in ACTIVE_STATES:
            st["plan_history"].append(st["plan"])
        if plan is None:
            st["plan"] = {"plan_id": None, "state": "NO_FEASIBLE_EXCHANGE", "solved_at": now_iso(), "run_id": run_id,
                          "edges": [], "order": [], "roles": {}, "recipient_count": 0, "hospitals": [], "record_versions": {},
                          "hash": None, "kind": None, "acks": {}, "approvals": {}, "reason": None}
            self.event(st, "NO_FEASIBLE_EXCHANGE", {"run_id": run_id})
            return
        st["plan"] = {
            "plan_id": f"plan-{uuid.uuid4().hex[:10]}",
            "hash": plan.hash,
            "kind": plan.kind,
            "order": plan.order,
            "edges": [list(e) for e in plan.edges],
            "roles": plan.roles,
            "recipient_count": plan.recipient_count,
            "hospitals": plan.hospitals,
            "record_versions": plan.record_versions,
            "state": "PROPOSED",
            "solved_at": now_iso(),
            "run_id": run_id,
            "acks": {},        # hospital_id -> PLAN_ACK | REFUSAL:<code>
            "approvals": {},   # hospital_id -> {status, signature_hex, verified, signed_at}
            "reason": None,
        }
        self.event(st, "PLAN_PROPOSED", {"plan_id": st["plan"]["plan_id"], "plan_kind": plan.kind, "order": plan.order, "hash": plan.hash})

    def invalidate(self, st: dict, reason: str, detail: dict | None = None) -> None:
        p = st.get("plan")
        if not p or p.get("state") not in ACTIVE_STATES:
            return
        p["state"] = "INVALIDATED"
        p["reason"] = reason
        p["invalidated_at"] = now_iso()
        p["approvals"] = {}
        self.event(st, "PLAN_INVALIDATED", {"plan_id": p["plan_id"], "reason": reason, **(detail or {})})
