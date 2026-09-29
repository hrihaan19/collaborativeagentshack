"""Flower ServerApp = the neutral coordinator. Runs on the Nebius VM
(fallback: M1) inside the SuperLink's ServerApp runtime.

It is a long-lived job loop: the coordinator API drops job files into
<state-dir>/jobs, this app turns each into Flower rounds over the Grid and
writes results into <state-dir>/state.json + audit.jsonl. Everything the
dashboard shows derives from those files.

The coordinator never reaches a hospital except through Flower messages.
"""
from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

from flwr.app import ConfigRecord, Context, Message, RecordDict
from flwr.serverapp import Grid, ServerApp

from domino import FLWR_VERSION
from domino.coordinator.graph import build_graph
from domino.coordinator.solver import Plan, solve
from domino.coordinator.state import ACTIVE_STATES, CoordinatorState
from domino.hospital import keys as keymod
from domino.protocol import (
    PAYLOAD_KEY,
    RECORD_KEY,
    CoordinatorRequest,
    HospitalEgress,
    MessageType,
    PlanEdge,
    PlanSummary,
    dumps,
    now_iso,
    safe_parse_egress,
)

log = logging.getLogger("domino.coordinator")
app = ServerApp()


class Coordinator:
    def __init__(self, grid: Grid, context: Context):
        self.grid = grid
        self.context = context
        cfg = context.run_config
        self.state = CoordinatorState(Path(str(cfg.get("state-dir", "./state/coordinator"))))
        self.poll_s = float(cfg.get("poll-seconds", 5))
        self.timeout = float(cfg.get("round-timeout", 60))
        self.num_hospitals = int(cfg.get("num-hospitals", 3))
        self.run_id = str(context.run_id)
        self.last_poll = 0.0

    # ------------------------------------------------------------ flower I/O
    def _nodes(self) -> list[int]:
        return sorted(self.grid.get_node_ids())

    def _hospital_node(self, st: dict, hid: str) -> int | None:
        h = st["hospitals"].get(hid)
        return int(h["node_id"]) if h and h.get("node_id") is not None else None

    def round(self, st: dict, mtype: MessageType, req_for_node, node_ids: list[int] | None = None) -> dict[str, HospitalEgress]:
        """One Flower round: one message per node, wait for replies, audit both."""
        round_id = f"{mtype.value.lower()}-{uuid.uuid4().hex[:8]}"
        nodes = node_ids if node_ids is not None else self._nodes()
        msgs: list[Message] = []
        sent: dict[str, dict] = {}
        for nid in nodes:
            req: CoordinatorRequest = req_for_node(nid)
            req.run_id, req.round_id, req.message_type = self.run_id, round_id, mtype
            content = RecordDict({RECORD_KEY: ConfigRecord({PAYLOAD_KEY: dumps(req)})})
            m = self.grid.create_message(content=content, message_type="query", dst_node_id=nid, group_id=round_id, ttl=self.timeout)
            msgs.append(m)
            sent[m.metadata.message_id] = {"domino_message_id": req.message_id, "dst_node_id": nid}
            self.state.audit({
                "direction": "coordinator->hospital", "message_type": mtype.value, "round_id": round_id,
                "flower_run_id": m.metadata.run_id, "flower_message_id": m.metadata.message_id,
                "src_node_id": m.metadata.src_node_id, "dst_node_id": nid, "domino_message_id": req.message_id,
                "payload": req.model_dump(mode="json", exclude_none=True),
            })
        t0 = time.time()
        replies = list(self.grid.send_and_receive(msgs, timeout=self.timeout))
        out: dict[str, HospitalEgress] = {}
        for r in replies:
            md = r.metadata
            base = {"direction": "hospital->coordinator", "message_type": mtype.value, "round_id": round_id,
                    "flower_run_id": md.run_id, "flower_message_id": md.message_id, "reply_to": md.reply_to_message_id,
                    "src_node_id": md.src_node_id, "dst_node_id": md.dst_node_id, "elapsed_s": round(time.time() - t0, 2)}
            if r.has_error():
                self.state.audit({**base, "status": "FLOWER_ERROR", "error_code": r.error.code})
                continue
            try:
                raw = bytes(r.content[RECORD_KEY][PAYLOAD_KEY])  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001
                self.state.audit({**base, "status": "PAYLOAD_MISSING"})
                continue
            egress, code = safe_parse_egress(raw)
            if egress is None:
                self.state.audit({**base, "status": code})
                continue
            hid = egress.hospital_id
            known = st["hospitals"].get(hid)
            if known and known.get("node_id") not in (None, md.src_node_id):
                self.state.audit({**base, "status": "HOSPITAL_ID_CLAIMED_BY_OTHER_NODE", "hospital_id": hid})
                continue
            entry = st["hospitals"].setdefault(hid, {"node_id": md.src_node_id, "public_key_hex": None, "first_seen": now_iso()})
            entry["node_id"] = md.src_node_id
            entry["last_seen"] = now_iso()
            entry["agent_mode"] = egress.agent_mode or entry.get("agent_mode")
            if egress.public_key_hex:
                if entry["public_key_hex"] is None:
                    entry["public_key_hex"] = egress.public_key_hex  # pinned on first sight (TOFU)
                elif entry["public_key_hex"] != egress.public_key_hex:
                    entry["key_mismatch"] = True
            out[hid] = egress
            self.state.audit({**base, "status": "OK", "hospital_id": hid, "domino_message_id": egress.message_id,
                              "payload": egress.model_dump(mode="json", exclude_none=True)})
        missing = [n for n in nodes if n not in {r.metadata.src_node_id for r in replies}]
        st["flower"]["last_round"] = {"round_id": round_id, "type": mtype.value, "sent": len(msgs), "replied": len(out),
                                      "missing_nodes": missing, "at": now_iso(), "elapsed_s": round(time.time() - t0, 2)}
        self.state.event(st, "FLOWER_ROUND", st["flower"]["last_round"])
        return out

    # -------------------------------------------------------------- actions
    def screen(self, st: dict) -> None:
        st["graph"]["screening"] = True
        self.state.save(st)
        cat = self.round(st, MessageType.SCREEN_REQUEST, lambda nid: CoordinatorRequest(run_id="", round_id="", message_type=MessageType.SCREEN_REQUEST))
        donors = [d for e in cat.values() for d in e.donors]
        res = self.round(st, MessageType.SCREEN_REQUEST, lambda nid: CoordinatorRequest(run_id="", round_id="", message_type=MessageType.SCREEN_REQUEST, donors=donors))
        vertices, edges = build_graph(list(res.values()))
        st["graph"] = {"vertices": vertices, "edges": [list(e) for e in edges], "screened_at": now_iso(), "run_id": self.run_id,
                       "hospitals_replied": sorted(res), "screening": False}
        self.state.event(st, "GRAPH_BUILT", {"vertices": sorted(vertices), "edges": [list(e) for e in edges]})
        plan = solve(vertices, edges)
        self.state.set_plan(st, plan, self.run_id)
        self.state.save(st)
        if plan is not None:
            self.prepare(st)

    def _summary(self, p: dict) -> PlanSummary:
        return PlanSummary(plan_id=p["plan_id"], plan_hash=p["hash"], kind=p["kind"],
                           edges=[PlanEdge(donor_vertex=u, recipient_vertex=v) for u, v in p["edges"]],
                           roles=p["roles"], hospitals=p["hospitals"], record_versions=p["record_versions"],
                           recipient_count=p["recipient_count"])

    def _involved_nodes(self, st: dict, p: dict) -> list[int]:
        return [n for n in (self._hospital_node(st, h) for h in p["hospitals"]) if n is not None]

    def prepare(self, st: dict) -> None:
        p = st["plan"]
        summary = self._summary(p)
        acks = self.round(st, MessageType.PLAN_PREPARE, lambda nid: CoordinatorRequest(run_id="", round_id="", message_type=MessageType.PLAN_PREPARE, plan=summary), self._involved_nodes(st, p))
        for hid, e in acks.items():
            p["acks"][hid] = "PLAN_ACK" if e.message_type == MessageType.PLAN_ACK else f"REFUSAL:{e.refusal_code}"
            self._apply_vertices(st, e)
        refused = [h for h, a in p["acks"].items() if a.startswith("REFUSAL")]
        if refused:
            self.state.invalidate(st, "PLAN_REFUSED_BY_HOSPITAL", {"hospitals": refused})
            self.state.save(st)
            self.state.enqueue("SCREEN", {"reason": "re-solve after refusal"})
            return
        if all(h in p["acks"] for h in p["hospitals"]):
            p["state"] = "AWAITING_APPROVALS"
            self.state.event(st, "PLAN_ACKED_BY_ALL", {"plan_id": p["plan_id"]})
        self.state.save(st)

    def _apply_vertices(self, st: dict, e: HospitalEgress) -> None:
        for v in e.vertices:
            cur = st["graph"]["vertices"].setdefault(v.vertex_token, {"kind": v.kind, "hospital_id": e.hospital_id})
            cur["availability"] = v.availability.value
            cur["record_version"] = v.record_version
            cur["hospital_id"] = e.hospital_id

    def poll(self, st: dict) -> None:
        """Re-query readiness of every hospital; enforce the human gate."""
        res = self.round(st, MessageType.REVIEW_STATUS, lambda nid: CoordinatorRequest(run_id="", round_id="", message_type=MessageType.REVIEW_STATUS))
        for e in res.values():
            self._apply_vertices(st, e)
        p = st.get("plan")
        if not p or p["state"] not in ACTIVE_STATES:
            self.state.save(st)
            return
        verts = st["graph"]["vertices"]
        for tok in p["order"]:
            v = verts.get(tok, {})
            if v.get("availability") == "HOLD":
                self.state.invalidate(st, "CLINICIAN_HOLD", {"vertex": tok, "hospital_id": v.get("hospital_id")})
                self.state.save(st)
                self.state.enqueue("SCREEN", {"reason": f"re-solve after HOLD on {tok}"})
                return
            if v.get("record_version") != p["record_versions"].get(tok):
                self.state.invalidate(st, "RECORD_CHANGED", {"vertex": tok, "hospital_id": v.get("hospital_id")})
                self.state.save(st)
                self.state.enqueue("SCREEN", {"reason": f"re-solve after record change on {tok}"})
                return
        review = [t for t in p["order"] if verts.get(t, {}).get("availability") == "REVIEW_REQUIRED"]
        if review:
            if p["state"] != "REVIEW_PENDING":
                p["state"] = "REVIEW_PENDING"
                p["approvals"] = {}
                self.state.event(st, "PLAN_REVIEW_PENDING", {"plan_id": p["plan_id"], "vertices": review})
            self.state.save(st)
            return
        if p["state"] == "REVIEW_PENDING":
            p["state"] = "AWAITING_APPROVALS"
            self.state.event(st, "PLAN_REVIEW_CLEARED", {"plan_id": p["plan_id"]})
        if p["state"] == "AWAITING_APPROVALS":
            self.collect_approvals(st)
        self.state.save(st)

    def collect_approvals(self, st: dict) -> None:
        p = st["plan"]
        summary = self._summary(p)
        res = self.round(st, MessageType.PLAN_APPROVAL, lambda nid: CoordinatorRequest(run_id="", round_id="", message_type=MessageType.PLAN_APPROVAL, plan=summary), self._involved_nodes(st, p))
        for hid, e in res.items():
            self._apply_vertices(st, e)
            entry = {"status": e.approval_status, "verified": False, "signature_hex": None, "signed_at": None}
            pub = st["hospitals"].get(hid, {}).get("public_key_hex")
            for s in e.signatures:
                if s.plan_id != p["plan_id"] or s.plan_hash != p["hash"] or s.hospital_id != hid:
                    entry["status"] = "SIGNATURE_MISMATCH"
                    continue
                if st["hospitals"].get(hid, {}).get("key_mismatch"):
                    entry["status"] = "KEY_MISMATCH"
                    continue
                entry["verified"] = bool(pub) and keymod.verify_hex(pub, p["hash"], s.signature_hex)
                entry["signature_hex"] = s.signature_hex
                entry["signed_at"] = s.signed_at
                entry["record_versions"] = s.record_versions
            p["approvals"][hid] = entry
        good = [h for h in p["hospitals"] if p["approvals"].get(h, {}).get("verified")]
        if set(good) == set(p["hospitals"]):
            self.state.event(st, "ALL_SIGNATURES_VERIFIED", {"plan_id": p["plan_id"], "hospitals": good})
            self.finalize(st)

    def finalize(self, st: dict) -> None:
        """Before finalization, re-query every involved hospital exactly once."""
        p = st["plan"]
        summary = self._summary(p)
        res = self.round(st, MessageType.PLAN_FINALIZE, lambda nid: CoordinatorRequest(run_id="", round_id="", message_type=MessageType.PLAN_FINALIZE, plan=summary), self._involved_nodes(st, p))
        for e in res.values():
            self._apply_vertices(st, e)
        verts = st["graph"]["vertices"]
        ok = set(res) == set(p["hospitals"]) and all(
            verts.get(t, {}).get("availability") == "AVAILABLE" and verts.get(t, {}).get("record_version") == p["record_versions"].get(t)
            for t in p["order"]) and all(e.approval_status == "APPROVED" for e in res.values())
        if ok:
            p["state"] = "APPROVED_FOR_SIMULATED_COORDINATION"
            p["finalized_at"] = now_iso()
            self.state.event(st, "APPROVED_FOR_SIMULATED_COORDINATION", {"plan_id": p["plan_id"]})
        else:
            self.state.invalidate(st, "FINAL_RECHECK_FAILED", {"replied": sorted(res)})
            self.state.enqueue("SCREEN", {"reason": "re-solve after failed final re-check"})

    def activate(self, st: dict, payload: dict) -> None:
        token = payload.get("donor_token", "N0")
        nid = self._hospital_node(st, payload.get("hospital_id", "C"))
        nodes = [nid] if nid is not None else self._nodes()
        res = self.round(st, MessageType.DONOR_ACTIVATION, lambda nid: CoordinatorRequest(run_id="", round_id="", message_type=MessageType.DONOR_ACTIVATION, activate_token=token, activation_nonce=payload.get("nonce")), nodes)
        outcome = {h: (e.refusal_code or "ACTIVATED") for h, e in res.items()}
        st["activation"]["activations"].append({"at": now_iso(), "source": payload.get("source"), "outcome": outcome})
        st["activation"]["last_activation_at"] = now_iso()
        self.state.event(st, "DONOR_ACTIVATION", {"outcome": outcome, "source": payload.get("source")})
        self.state.save(st)
        if any(v == "ACTIVATED" for v in outcome.values()):
            self.screen(st)

    # ----------------------------------------------------------------- loop
    def run(self) -> None:
        st = self.state.load()
        st["flower"].update({"run_id": self.run_id, "flwr_version": FLWR_VERSION, "mode": "VERIFIED-LIVE",
                             "started_at": now_iso(), "node_ids": self._nodes(), "serverapp_alive_at": now_iso()})
        self.state.event(st, "SERVERAPP_STARTED", {"run_id": self.run_id, "node_ids": self._nodes()})
        self.state.save(st)
        log.info("Domino coordinator ServerApp started run_id=%s nodes=%s", self.run_id, self._nodes())
        last_beat = 0.0
        while True:
            job = self.state.next_job()
            st = self.state.load()
            if job:
                kind, payload = job["kind"], job.get("payload", {})
                self.state.event(st, "JOB", {"job_kind": kind, "job_id": job["job_id"], **{k: v for k, v in payload.items() if k != "nonce"}})
                try:
                    if kind == "SCREEN":
                        self.screen(st)
                    elif kind == "POLL":
                        self.poll(st)
                    elif kind == "ACTIVATE":
                        self.activate(st, payload)
                    elif kind == "RESET":
                        fl = st["flower"]
                        st = self.state._empty()
                        st["flower"] = fl
                        self.state.event(st, "COORDINATOR_RESET", {})
                        self.state.save(st)
                    else:
                        self.state.event(st, "JOB_UNKNOWN", {"job_kind": kind})
                except Exception as exc:  # noqa: BLE001 - keep the loop alive; log class only
                    log.exception("job failed")
                    st = self.state.load()
                    st["graph"]["screening"] = False
                    self.state.event(st, "JOB_FAILED", {"job_kind": kind, "error_class": type(exc).__name__})
                    self.state.save(st)
                continue
            now = time.time()
            p = st.get("plan")
            if p and p.get("state") in ACTIVE_STATES and now - self.last_poll >= self.poll_s:
                self.last_poll = now
                try:
                    self.poll(st)
                except Exception as exc:  # noqa: BLE001
                    log.exception("poll failed")
                    self.state.event(st, "POLL_FAILED", {"error_class": type(exc).__name__})
                    self.state.save(st)
                continue
            if now - last_beat >= 1.0:
                last_beat = now
                st["flower"]["serverapp_alive_at"] = now_iso()
                st["flower"]["node_ids"] = self._nodes()
                self.state.save(st)
            time.sleep(0.3)


@app.main()
def main(grid: Grid, context: Context) -> None:
    Coordinator(grid, context).run()
