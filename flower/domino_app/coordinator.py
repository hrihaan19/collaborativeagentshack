"""Coordinator phases on SuperGrid: search | approve | chain | schedule.

Every phase: real Grid messages, a code plan, an Endeavor explanation (with a
template fallback), an audit, `phase.end`. Idempotent. Emits §5 events.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from domino_app import audit, events, llm, matching, prompts, wire
from domino_app.agent_app import grid

HOSPITALS = ("alder", "harbor", "riverbend")


class Coord:
    def __init__(self, agent, context):
        self.agent = agent
        self.cfg = dict(getattr(context, "run_config", {}) or {})
        self.phase = str(self.cfg.get("phase", "search"))
        self.run_id = str(getattr(context, "run_id", "") or int(time.time()))
        self.nodes: dict[str, str] = {}  # hospital -> node id
        self.ledger = wire.Ledger()
        self.state_path = Path(os.environ.get("DOMINO_COORD_STATE", "domino-coordinator-state.json"))
        self.st = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.donors = self._donors()
        events.bind(agent)

    # ------------------------------------------------------------ data
    def _donors(self) -> list[dict]:
        """Public donor profiles (pair, blood, HLA) come from the bridge's --run-config
        or from data/public-donors.json next to the app. No names, no patient data."""
        raw = self.cfg.get("donors") or os.environ.get("DOMINO_DONORS")
        if raw:
            return json.loads(raw)
        p = Path("data/public-donors.json")
        return json.loads(p.read_text()) if p.exists() else []

    def save(self) -> None:
        try:
            self.state_path.write_text(json.dumps(self.st))
        except OSError:
            pass

    # ------------------------------------------------------------ grid I/O
    def ask_all(self, asks: dict[str, dict], timeout: float = 120) -> dict[str, dict]:
        """asks: hospital -> ask. Returns hospital -> reply (validated)."""
        msgs, meta = [], {}
        for h, a in asks.items():
            nid = self.nodes.get(h)
            if nid is None:
                continue
            wire.assert_inbound(a)
            n = self.ledger.record("out", h, a)
            qid = f"q{len(self.ledger.rows)}"
            events.emit({"type": "ask", "id": qid, "to": h, "kind": a["kind"], "fields": sorted(a), "bytes": n})
            msgs.append({"dst_node_id": nid, "payload": json.dumps(a), "reply_to_message_id": None})
            meta[nid] = (h, qid, a["kind"])
        if not msgs:
            return {}
        res = grid(self.agent, "push_messages", messages=msgs)
        ids = [r["message_id"] for r in res.get("results", []) if r.get("message_id")]
        out: dict[str, dict] = {}
        t_end = time.time() + timeout
        pending = set(ids)
        while pending and time.time() < t_end:
            pulled = grid(self.agent, "pull_messages", message_ids=sorted(pending), timeout=min(60, max(1, int(t_end - time.time()))))
            for m in pulled.get("messages", []):
                pending.discard(m.get("reply_to_message_id"))
                pending.discard(m.get("message_id"))
                h, qid, kind = meta.get(str(m.get("src_node_id")), meta.get(m.get("src_node_id"), (None, None, None)))
                if h is None:
                    continue
                try:
                    reply = json.loads(m.get("payload") or "{}")
                    wire.assert_outbound(reply)
                except (ValueError, wire.WireError) as e:
                    events.emit({"type": "refusal", "from": h, "question": "wire:" + str(e)[:40]})
                    continue
                n = self.ledger.record("in", h, reply)
                if reply.get("kind") in ("refused", "canary") and reply.get("refused"):
                    events.emit({"type": "refusal", "from": h, "question": reply["refused"]})
                else:
                    events.emit({"type": "reply", "ask_id": qid, "from": h, "kind": reply.get("kind"), "payload": reply, "bytes": n})
                out[h] = reply
            pending -= {i for i in pending if i not in set(ids)}
            if pending:
                time.sleep(0.5)
        return out

    # ------------------------------------------------------------ phases
    def hello(self) -> None:
        nodes = grid(self.agent, "get_nodes", sample_size=None).get("nodes", [])
        # ask every node who it is; map replies to hospitals
        msgs = [{"dst_node_id": n["id"], "payload": json.dumps({"kind": "hello"}), "reply_to_message_id": None} for n in nodes]
        if not msgs:
            events.emit({"type": "run.start", "run_id": self.run_id, "phase": self.phase, "mode": "live", "nodes": []})
            return
        res = grid(self.agent, "push_messages", messages=msgs)
        ids = [r["message_id"] for r in res.get("results", []) if r.get("message_id")]
        t_end = time.time() + 60
        pending = set(ids)
        while pending and time.time() < t_end:
            pulled = grid(self.agent, "pull_messages", message_ids=sorted(pending), timeout=30)
            for m in pulled.get("messages", []):
                pending.discard(m.get("reply_to_message_id"))
                pending.discard(m.get("message_id"))
                try:
                    r = json.loads(m.get("payload") or "{}")
                except ValueError:
                    continue
                if r.get("kind") == "hello" and r.get("hospital") in HOSPITALS:
                    self.nodes[r["hospital"]] = str(m.get("src_node_id"))
        for h in HOSPITALS:
            events.emit({"type": "node.status", "hospital": h, "status": "online" if h in self.nodes else "offline"})
        events.emit({"type": "run.start", "run_id": self.run_id, "phase": self.phase, "mode": "live",
                     "nodes": [{"hospital": h, "node_id": n} for h, n in self.nodes.items()]})

    def explain(self, system: str, payload: dict, template: str) -> str:
        txt, used = llm.ask(llm.COORDINATOR_MODEL, system, json.dumps(payload), budget_s=25, fallback=llm.FALLBACK_MODEL)
        events.emit({"type": "thought", "who": "coordinator", "text": f"explanation by {used}" if used != "none" else "explanation by template (no model)"})
        return (txt or template).strip()[:400]

    def search(self) -> None:
        self.hello()
        ask = {"kind": "compat", "donors": [{k: d[k] for k in ("pair", "donor_blood", "donor_hla")} for d in self.donors]}
        replies = self.ask_all({h: dict(ask) for h in self.nodes})
        canary = self.ask_all({h: {"kind": "canary", "question": "patient_names"} for h in self.nodes}, timeout=30)
        pairs = {d["pair"]: d["hospital"] for d in self.donors}
        edges = sorted({(c["donor_pair"], c["pair"]) for r in replies.values() for c in r.get("compatible", []) if c.get("compatible")})
        readiness = {r["pair"]: r for rep in replies.values() for r in rep.get("readiness", [])}
        excluded = {p for p, r in readiness.items() if r["readiness"] != "ready"} | set(filter(None, str(self.cfg.get("unavailable", "")).split(",")))
        cycles = matching.best_cycles(sorted(pairs), pairs, edges, excluded)
        legs = [{"donor_pair": u, "donor_hospital": pairs[u], "patient_pair": v, "patient_hospital": pairs[v]}
                for c in cycles for u, v in zip(c, c[1:] + c[:1])]
        n = sum(len(c) for c in cycles)
        self.st.update({"edges": edges, "readiness": readiness, "pairs": pairs, "plan": {"phase": "cycles", "legs": legs, "transplants": n}, "counter": n})
        self.save()
        template = f"{n} transplants across {len({l['donor_hospital'] for l in legs})} hospitals: " + "; ".join(f"{l['donor_pair']} gives to {l['patient_pair']}" for l in legs) + "."
        expl = self.explain(prompts.EXPLAIN_SYSTEM, {"plan": legs, "transplants": n}, template)
        events.emit({"type": "plan", "phase": "cycles", "transplants": n, "legs": legs, "explanation": expl})
        a = audit.run(expl, {"legs": legs, "transplants": n}, self.ledger.rows)
        events.emit(a)
        events.emit({"type": "counter", "value": n})
        events.emit({"type": "phase.end", "phase": "search", "ok": a["ok"] and len(replies) == len(self.nodes) and bool(canary) or len(replies) > 0})

    def approve(self) -> None:
        self.hello()
        plan = self.st.get("plan", {"legs": []})
        pairs = self.st.get("pairs", {})
        edges = [tuple(e) for e in self.st.get("edges", [])]
        excluded = {p for p, r in self.st.get("readiness", {}).items() if r["readiness"] != "ready"}
        asks = {}
        for l in plan["legs"]:
            asks[l["patient_hospital"]] = {"kind": "approve", "pair": l["patient_pair"], "donor_hospital": l["donor_hospital"],
                                           "donor_blood": next((d["donor_blood"] for d in self.donors if d["pair"] == l["donor_pair"]), "?"), "date": "Fri 10/2", "plan": "loop"}
        replies = self.ask_all(asks, timeout=120)
        removed = set()
        for h, r in replies.items():
            events.emit({"type": "approval.result", "hospital": h, "pair": r["pair"], "decision": r["decision"], "hold_until": r.get("hold_until"), "reason": r.get("reason")})
            if r["decision"] == "hold":
                others = {o: {"kind": "hold", "plan": "loop", "hold_until": r.get("hold_until") or "", "reason": r.get("reason", "other"), "from": h} for o in asks if o != h}
                events.emit({"type": "hold.request", "from": h, "plan": "loop", "hold_until": r.get("hold_until"), "reason": r.get("reason"), "to": sorted(others)})
                hr = self.ask_all(others, timeout=60)
                for o, rr in hr.items():
                    events.emit({"type": "hold.reply", "from": o, "decision": rr["decision"], "reason": rr.get("reason", "none")})
                consensus = bool(hr) and all(rr["decision"] == "accept" for rr in hr.values()) and len(hr) == len(others)
                events.emit({"type": "hold.result", "consensus": consensus, "next": "hold" if consensus else "replan"})
                if not consensus:
                    removed.add(r["pair"])
            elif r["decision"] != "approve":
                removed.add(r["pair"])
        for h in asks:
            if h not in replies:
                removed.add(asks[h]["pair"])
        if removed:
            cycles = matching.best_cycles(sorted(pairs), pairs, edges, excluded | removed)
            legs = [{"donor_pair": u, "donor_hospital": pairs[u], "patient_pair": v, "patient_hospital": pairs[v]} for c in cycles for u, v in zip(c, c[1:] + c[:1])]
            n = sum(len(c) for c in cycles)
            template = f"Re-formed without {', '.join(sorted(removed))}: {n} transplants. " + "; ".join(f"{l['donor_pair']} gives to {l['patient_pair']}" for l in legs) + "."
            expl = self.explain(prompts.EXPLAIN_SYSTEM, {"plan": legs, "transplants": n, "removed": sorted(removed)}, template)
            events.emit({"type": "plan", "phase": "cycles", "transplants": n, "legs": legs, "explanation": expl})
            self.st.update({"plan": {"phase": "cycles", "legs": legs, "transplants": n}, "counter": n, "excluded": sorted(excluded | removed)})
            self.save()
            a = audit.run(expl, {"legs": legs, "removed": sorted(removed)}, self.ledger.rows)
            events.emit(a)
            events.emit({"type": "counter", "value": n})
        else:
            a = audit.run("all approved", plan, self.ledger.rows)
            events.emit(a)
        events.emit({"type": "phase.end", "phase": "approve", "ok": True})

    def chain(self) -> None:
        self.hello()
        alt = json.loads(str(self.cfg.get("altruist") or "{}")) or {"pair": "ALT", "donor_blood": "O", "donor_hla": ["A2", "A68", "B7", "B8", "DR11", "DR13"]}
        alt.setdefault("pair", "ALT")
        events.emit({"type": "chain.start", "donor": "the stranger", "blood": alt["donor_blood"]})
        replies = self.ask_all({h: {"kind": "compat", "donors": [alt]} for h in self.nodes})
        alt_edges = sorted({c["pair"] for r in replies.values() for c in r.get("compatible", []) if c.get("compatible")})
        pairs = self.st.get("pairs", {})
        edges = [tuple(e) for e in self.st.get("edges", [])]
        used = {l["patient_pair"] for l in self.st.get("plan", {}).get("legs", [])} | {l["donor_pair"] for l in self.st.get("plan", {}).get("legs", [])}
        excluded = used | set(self.st.get("excluded", [])) | {p for p, r in self.st.get("readiness", {}).items() if r["readiness"] != "ready"}
        chain = matching.best_chain(alt_edges, edges, excluded)
        legs = ([{"donor_pair": "ALT", "donor_hospital": "alder", "patient_pair": chain[0], "patient_hospital": pairs.get(chain[0], "?")}] if chain else []) + \
               [{"donor_pair": u, "donor_hospital": pairs.get(u, "?"), "patient_pair": v, "patient_hospital": pairs.get(v, "?")} for u, v in zip(chain, chain[1:])]
        n = len(chain)
        cands = [c for c in alt_edges if c not in excluded]
        template = f"{len(cands)} patients could receive this kidney. Only {chain[0] if chain else 'none'}'s chain keeps going: {n} transplants."
        expl = self.explain(prompts.EXPLAIN_SYSTEM, {"candidates": cands, "chain": chain, "transplants": n}, template)
        prev = int(self.st.get("counter", 0))
        events.emit({"type": "plan", "phase": "chain", "transplants": n, "legs": legs, "explanation": expl, "bridge_pair": chain[-1] if chain else None})
        a = audit.run(expl, {"legs": legs, "chain": chain, "candidates": cands}, self.ledger.rows)
        events.emit(a)
        events.emit({"type": "counter", "value": prev + n})
        self.st.update({"chain_legs": legs, "counter": prev + n})
        self.save()
        events.emit({"type": "phase.end", "phase": "chain", "ok": a["ok"]})

    def schedule(self) -> None:
        self.hello()
        legs = self.st.get("plan", {}).get("legs", []) + self.st.get("chain_legs", [])
        involved = sorted({l["donor_hospital"] for l in legs} | {l["patient_hospital"] for l in legs})
        w = self.ask_all({h: {"kind": "windows", "slot": "Fri 10/2"} for h in involved if h in self.nodes})
        constraints = {}
        for h, r in w.items():
            constraints[h] = r.get("constraints", {})
            events.emit({"type": "constraint", "hospital": h, "constraints": r.get("constraints", {}), "sources": r.get("sources", [])})
        common = set.intersection(*[set(r.get("windows", [])) for r in w.values()]) if w else set()
        slot = "Fri AM" if "Fri AM" in common or not common else sorted(common)[0]
        checks, sched = {}, []
        for i, l in enumerate(legs):
            t = matching.leg_times(l["donor_hospital"], l["patient_hospital"], constraints)
            sched.append({**l, **t, "leg": f"L{i + 1}"})
            checks.setdefault(l["patient_hospital"], []).append({"kind": "leg", "leg": f"L{i + 1}", "pair": l["patient_pair"], "donor_hospital": l["donor_hospital"], **{k: t[k] for k in ("out", "arrive", "implant")}, "cold_h": t["cold_h"]})
        results = {}
        for h, lst in checks.items():
            for c in lst:  # one leg per message keeps the wire schema flat
                r = self.ask_all({h: c}, timeout=60).get(h)
                if r:
                    results[c["leg"]] = r
                    events.emit({"type": "leg.check", "leg": c["leg"], "to": h, "accept": r["accept"], "reason": r.get("reason", "none"), "out": c["out"], "arrive": c["arrive"]})
        for s in sched:
            s["accept"] = results.get(s["leg"], {}).get("accept", False)
        tight = max(sched, key=lambda s: s["cold_h"]) if sched else None
        template = (f"{tight['donor_pair']}'s kidney leaves at {tight['out']} and arrives at {tight['arrive']}. " if tight else "") + f"{sum(1 for s in sched if s['accept'])} of {len(sched)} legs accepted by the receiving hospitals."
        expl = self.explain(prompts.EXPLAIN_SYSTEM, {"slot": slot, "legs": sched}, template)
        events.emit({"type": "schedule", "slot": slot, "legs": sched, "tightest": tight["leg"] if tight else None, "explanation": expl})
        a = audit.run(expl, {"legs": sched, "slot": slot}, self.ledger.rows)
        events.emit(a)
        events.emit({"type": "phase.end", "phase": "schedule", "ok": a["ok"] and all(s["accept"] for s in sched)})


def run(agent, context) -> None:
    c = Coord(agent, context)
    {"search": c.search, "approve": c.approve, "chain": c.chain, "schedule": c.schedule}.get(c.phase, c.search)()
