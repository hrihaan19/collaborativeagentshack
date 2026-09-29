"""Hospital agent logic. Runs INSIDE the Flower ClientApp on the SuperNode.

Input: a CoordinatorRequest + the private local store.
Output: exactly one HospitalEgress. Nothing else leaves.
"""
from __future__ import annotations

from domino.fixtures import toy_compatible
from domino.hospital import keys as keymod
from domino.hospital.store import HospitalStore
from domino.protocol import (
    Availability,
    CoordinatorRequest,
    DonorDescriptor,
    Evaluation,
    HospitalEgress,
    MessageType,
    PlanSignature,
    ScreenResult,
    VertexStatus,
    now_iso,
)


def _base(store: HospitalStore, req: CoordinatorRequest, mtype: MessageType) -> HospitalEgress:
    key = keymod.load_or_create(store.state_dir)
    return HospitalEgress(
        run_id=req.run_id,
        round_id=req.round_id,
        message_type=mtype,
        hospital_id=store.hospital_id,
        public_key_hex=keymod.public_hex(key),
    )


def _vertices(store: HospitalStore) -> list[VertexStatus]:
    out = []
    for tok, rec in sorted(store.records().items()):
        if rec["kind"] == "SOURCE_ONLY" and not rec["donor"]["active"]:
            continue  # inactive non-directed donor is invisible to the network
        out.append(
            VertexStatus(
                vertex_token=tok,
                hospital_id=store.hospital_id,
                kind=rec["kind"],
                availability=Availability(store.availability(rec)),
                record_version=rec["record_version"],
            )
        )
    return out


def _donors(store: HospitalStore) -> list[DonorDescriptor]:
    out = []
    for tok, rec in sorted(store.records().items()):
        d = rec.get("donor")
        if not d or not d.get("active"):
            continue
        if store.availability(rec) == "HOLD":
            continue  # a held pair offers nothing to the network
        out.append(
            DonorDescriptor(
                donor_token=d["donor_token"],
                vertex_token=tok,
                hospital_id=store.hospital_id,
                abo=d["abo"],
                marker=d["marker"],
                kind="NON_DIRECTED" if rec["kind"] == "SOURCE_ONLY" else "PAIRED",
                active=True,
            )
        )
    return out


def _agent_mode(store: HospitalStore) -> str:
    modes = {rec.get("agent_mode", "RULE") for rec in store.records().values()}
    if "LOCAL_MODEL_SUGGESTED" in modes:
        return "LOCAL_MODEL_SUGGESTED"
    if "RULE-BASED FALLBACK" in modes:
        return "RULE-BASED FALLBACK"
    return "RULE"


def handle(store: HospitalStore, req: CoordinatorRequest) -> HospitalEgress:
    t = req.message_type
    if t == MessageType.SCREEN_REQUEST:
        return screen(store, req)
    if t == MessageType.REVIEW_STATUS:
        e = _base(store, req, MessageType.REVIEW_STATUS)
        e.vertices = _vertices(store)
        e.donors = _donors(store)
        e.agent_mode = _agent_mode(store)
        return e
    if t == MessageType.PLAN_PREPARE:
        return plan_prepare(store, req)
    if t == MessageType.PLAN_APPROVAL:
        return plan_approval(store, req)
    if t == MessageType.PLAN_FINALIZE:
        e = _base(store, req, MessageType.PLAN_FINALIZE)
        e.vertices = _vertices(store)
        e.ack_plan_id = req.plan.plan_id if req.plan else None
        if req.plan:
            plans = store.plans()
            e.approval_status = plans.get(req.plan.plan_id, {}).get("approval", "PENDING")
            store.log("PLAN_FINALIZE_SEEN", {"plan_id": req.plan.plan_id})
        return e
    if t == MessageType.DONOR_ACTIVATION:
        return donor_activation(store, req)
    e = _base(store, req, MessageType.REFUSAL)
    e.refusal_code = "UNSUPPORTED_MESSAGE_TYPE"
    return e


def screen(store: HospitalStore, req: CoordinatorRequest) -> HospitalEgress:
    """Announce local donors/vertices; evaluate every offered donor against
    every local recipient. Missing data -> UNKNOWN, never positive."""
    e = _base(store, req, MessageType.SCREEN_RESPONSE)
    recs = store.records()
    e.vertices = _vertices(store)
    e.donors = _donors(store)
    e.agent_mode = _agent_mode(store)
    for d in req.donors:
        for tok, rec in sorted(recs.items()):
            if rec.get("recipient") is None:
                continue
            if d.vertex_token == tok:
                continue  # a donor never "exchanges" with their own paired recipient
            if store.availability(rec) == "HOLD":
                res = ScreenResult.UNKNOWN  # a held recipient is not screened
            else:
                res = ScreenResult(toy_compatible(d.abo, d.marker, rec["recipient"]))
            e.evaluations.append(Evaluation(donor_token=d.donor_token, recipient_vertex=tok, result=res))
    store.log("SCREENED", {"offered_donors": len(req.donors), "evaluations": len(e.evaluations), "run_id": req.run_id})
    return e


def plan_prepare(store: HospitalStore, req: CoordinatorRequest) -> HospitalEgress:
    if not req.plan:
        e = _base(store, req, MessageType.REFUSAL)
        e.refusal_code = "PLAN_MISSING"
        return e
    recs = store.records()
    # Refuse if the plan's record versions for OUR vertices do not match reality.
    for tok, ver in req.plan.record_versions.items():
        if tok in recs and recs[tok]["record_version"] != ver:
            e = _base(store, req, MessageType.REFUSAL)
            e.ack_plan_id = req.plan.plan_id
            e.refusal_code = "RECORD_VERSION_MISMATCH"
            e.vertices = _vertices(store)
            store.log("PLAN_REFUSED_VERSION", {"plan_id": req.plan.plan_id, "vertex": tok})
            return e
        if tok in recs and store.availability(recs[tok]) != "AVAILABLE":
            e = _base(store, req, MessageType.REFUSAL)
            e.ack_plan_id = req.plan.plan_id
            e.refusal_code = "VERTEX_NOT_AVAILABLE"
            e.vertices = _vertices(store)
            return e
    store.store_plan(req.plan.model_dump())
    store.log("PLAN_RECEIVED", {"plan_id": req.plan.plan_id, "hash": req.plan.plan_hash})
    e = _base(store, req, MessageType.PLAN_ACK)
    e.ack_plan_id = req.plan.plan_id
    e.approval_status = "PENDING"
    e.vertices = _vertices(store)
    return e


def plan_approval(store: HospitalStore, req: CoordinatorRequest) -> HospitalEgress:
    """Report the local clinician's decision. The coordinator cannot approve;
    only the console (a human) sets approval. The signature is over the exact
    plan hash and was produced by the console at click time."""
    e = _base(store, req, MessageType.PLAN_APPROVAL)
    e.vertices = _vertices(store)
    if not req.plan:
        e.approval_status = "N/A"
        return e
    p = store.plans().get(req.plan.plan_id)
    e.ack_plan_id = req.plan.plan_id
    if not p or p.get("plan_hash") != req.plan.plan_hash:
        e.approval_status = "N/A"
        e.refusal_code = "PLAN_UNKNOWN"
        return e
    e.approval_status = p.get("approval", "PENDING")
    if e.approval_status == "APPROVED" and p.get("signature"):
        e.signatures = [PlanSignature(**p["signature"])]
    return e


def donor_activation(store: HospitalStore, req: CoordinatorRequest) -> HospitalEgress:
    ok, code = store.activate_donor(req.activate_token or "")
    if ok:
        e = _base(store, req, MessageType.SCREEN_RESPONSE)
        e.vertices = _vertices(store)
        e.donors = _donors(store)
        return e
    e = _base(store, req, MessageType.REFUSAL)
    e.refusal_code = code
    e.vertices = _vertices(store)
    return e


def sign_plan_locally(store: HospitalStore, plan_id: str) -> PlanSignature:
    """Called by the LOCAL CONSOLE when the clinician clicks APPROVE."""
    p = store.plans()[plan_id]
    key = keymod.load_or_create(store.state_dir)
    sig = PlanSignature(
        plan_id=plan_id,
        plan_hash=p["plan_hash"],
        hospital_id=store.hospital_id,
        signature_hex=keymod.sign_hex(key, p["plan_hash"]),
        record_versions={t: v for t, v in p.get("record_versions", {}).items() if t in store.records()},
        signed_at=now_iso(),
    )
    store.set_approval(plan_id, True, sig.model_dump())
    return sig


def local_search_count(store: HospitalStore) -> int:
    """Local-only search: exchanges using only this hospital's own vertices."""
    from domino.coordinator.solver import solve

    recs = store.records()
    verts, edges = {}, []
    donors = _donors(store)
    for v in _vertices(store):
        verts[v.vertex_token] = {"kind": v.kind, "availability": v.availability.value, "hospital_id": store.hospital_id}
    for d in donors:
        for tok, rec in recs.items():
            if rec.get("recipient") is None or d.vertex_token == tok:
                continue
            if toy_compatible(d.abo, d.marker, rec["recipient"]) == "TOY_CANDIDATE":
                edges.append((d.vertex_token, tok))
    plan = solve(verts, edges)
    return 0 if plan is None else 1
