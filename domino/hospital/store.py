"""Hospital-local record store + readiness rules + human gate.

Everything in `records.json` is PRIVATE to the hospital machine. Only the
functions in `logic.py` produce egress, and they go through HospitalEgress.

Readiness rule (rules-only baseline, always applied):
  * a HOLD set by the local clinician  -> HOLD (until that clinician clears it)
  * a note added after the last review -> REVIEW_REQUIRED
  * otherwise                           -> AVAILABLE
Any record change bumps record_version.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

from domino.fixtures import FIXTURES
from domino.statefiles import append_jsonl, read_json, write_json


def default_state_dir(hospital_id: str) -> Path:
    env = os.environ.get("DOMINO_HOSPITAL_STATE_DIR")
    if env:
        return Path(env)
    return Path.cwd() / "state" / f"hospital-{hospital_id.lower()}"


class HospitalStore:
    def __init__(self, hospital_id: str, state_dir: Path):
        self.hospital_id = hospital_id
        self.state_dir = Path(state_dir)
        self.records_path = self.state_dir / "records.json"
        self.log_path = self.state_dir / "local-log.jsonl"
        self.plans_path = self.state_dir / "plans.json"

    # ------------------------------------------------------------ seeding
    def seed(self, fixtures: dict | None = None, force: bool = False) -> None:
        fx = fixtures or FIXTURES
        if self.records_path.exists() and not force:
            return
        records = {}
        for rec in fx.get(self.hospital_id, []):
            r = copy.deepcopy(rec)
            r["record_version"] = 1
            r["hold"] = False
            r["notes"] = []  # private clinician notes (never leave the hospital)
            r["reviewed_note_count"] = 0
            r["agent_mode"] = "RULE"
            records[r["vertex_token"]] = r
        write_json(self.records_path, {"hospital_id": self.hospital_id, "records": records})
        write_json(self.plans_path, {"plans": {}})
        self.log("SEEDED", {"vertices": sorted(records)})

    def reset(self, fixtures: dict | None = None) -> None:
        self.seed(fixtures, force=True)
        self.log("RESET", {})

    # ------------------------------------------------------------ records
    def records(self) -> dict[str, dict]:
        data = read_json(self.records_path, {"records": {}})
        return data.get("records", {})

    def _save(self, records: dict[str, dict]) -> None:
        write_json(self.records_path, {"hospital_id": self.hospital_id, "records": records})

    def log(self, event: str, detail: dict) -> None:
        from domino.protocol import now_iso

        append_jsonl(self.log_path, {"at": now_iso(), "hospital_id": self.hospital_id, "event": event, **detail})

    def availability(self, rec: dict) -> str:
        if rec.get("hold"):
            return "HOLD"
        if len(rec.get("notes", [])) > rec.get("reviewed_note_count", 0):
            return "REVIEW_REQUIRED"
        return "AVAILABLE"

    # ------------------------------------------------------- human gate ops
    def add_note(self, vertex_token: str, text: str, agent_mode: str = "RULE") -> dict:
        recs = self.records()
        rec = recs[vertex_token]
        rec["notes"].append({"text": text[:2000]})
        rec["record_version"] += 1
        rec["agent_mode"] = agent_mode
        self._save(recs)
        self.log("NOTE_ADDED", {"vertex": vertex_token, "record_version": rec["record_version"], "agent_mode": agent_mode})
        self._invalidate_local_approvals(vertex_token)
        return rec

    def set_hold(self, vertex_token: str, hold: bool) -> dict:
        recs = self.records()
        rec = recs[vertex_token]
        rec["hold"] = bool(hold)
        rec["record_version"] += 1
        if not hold:
            # clearing a hold also counts as having reviewed the notes
            rec["reviewed_note_count"] = len(rec["notes"])
        self._save(recs)
        self.log("HOLD_SET" if hold else "HOLD_CLEARED", {"vertex": vertex_token, "record_version": rec["record_version"]})
        self._invalidate_local_approvals(vertex_token)
        return rec

    def mark_reviewed(self, vertex_token: str) -> dict:
        recs = self.records()
        rec = recs[vertex_token]
        rec["reviewed_note_count"] = len(rec["notes"])
        rec["record_version"] += 1
        self._save(recs)
        self.log("REVIEWED", {"vertex": vertex_token, "record_version": rec["record_version"]})
        self._invalidate_local_approvals(vertex_token)
        return rec

    def activate_donor(self, donor_token: str) -> tuple[bool, str]:
        """Only the pre-seeded inactive fixture N0 can ever be activated."""
        recs = self.records()
        for rec in recs.values():
            d = rec.get("donor")
            if d and d["donor_token"] == donor_token:
                if rec["kind"] != "SOURCE_ONLY":
                    return False, "NOT_NON_DIRECTED"
                if d["active"]:
                    return False, "ALREADY_ACTIVE"
                d["active"] = True
                rec["record_version"] += 1
                self._save(recs)
                self.log("DONOR_ACTIVATED", {"vertex": rec["vertex_token"], "record_version": rec["record_version"]})
                return True, "ACTIVATED"
        return False, "UNKNOWN_TOKEN"

    # ------------------------------------------------------------- plans
    def plans(self) -> dict:
        return read_json(self.plans_path, {"plans": {}}).get("plans", {})

    def store_plan(self, plan: dict) -> None:
        plans = self.plans()
        existing = plans.get(plan["plan_id"], {})
        plans[plan["plan_id"]] = {**plan, "approval": existing.get("approval", "PENDING"), "signature": existing.get("signature")}
        write_json(self.plans_path, {"plans": plans})

    def set_approval(self, plan_id: str, approved: bool, signature: dict | None) -> None:
        plans = self.plans()
        if plan_id not in plans:
            raise KeyError(plan_id)
        plans[plan_id]["approval"] = "APPROVED" if approved else "REFUSED"
        plans[plan_id]["signature"] = signature
        write_json(self.plans_path, {"plans": plans})
        self.log("PLAN_APPROVED" if approved else "PLAN_REFUSED", {"plan_id": plan_id})

    def _invalidate_local_approvals(self, vertex_token: str) -> None:
        plans = self.plans()
        changed = False
        for p in plans.values():
            if vertex_token in p.get("roles", {}) and p.get("approval") == "APPROVED":
                p["approval"] = "PENDING"
                p["signature"] = None
                changed = True
        if changed:
            write_json(self.plans_path, {"plans": plans})
            self.log("LOCAL_APPROVALS_INVALIDATED", {"vertex": vertex_token})
