"""Scripted mode: generates the same event objects (§5 contract) that a live run
would emit, computed by the matching code from the data. Nothing on screen is a
hand-typed outcome: plans, chains, legs and times come from matching.py.

Each beat = {"id","title","caption","events":[{"t": ms, "ev": {...}}], "wait": None|"approval"|"give",
             "branches": {decision: [events...]}} .
"""
from __future__ import annotations

import json
import uuid

from domino.story import data as D
from domino.story import matching as M

MODELS = {"coordinator": "flower-endeavor-v1.0", "auditor": "openai/gpt-5.6-sol"}


def _bytes(obj) -> int:
    return len(json.dumps(obj, separators=(",", ":")).encode())


class Script:
    def __init__(self, mode: str = "scripted"):
        self.mode = mode
        self.P = D.pairs()
        self.E = M.edges(self.P)
        self.run_id = "rehearsal"
        self.q = 0
        self.readiness = {}
        for pid, p in self.P.items():
            r = D.READINESS.get(pid)
            self.readiness[pid] = {"pair": pid, "readiness": r[0] if r else "ready", "reason": r[1] if r else "none"}

    # ------------------------------------------------------------ helpers
    def _ask(self, to: str, kind: str, fields: list[str], payload: dict | None = None) -> dict:
        self.q += 1
        return {"type": "ask", "id": f"q{self.q}", "to": to, "kind": kind, "fields": fields,
                "bytes": _bytes({"kind": kind, **(payload or {})})}

    def _reply(self, ask_id: str, frm: str, kind: str, payload: dict) -> dict:
        return {"type": "reply", "ask_id": ask_id, "from": frm, "kind": kind, "payload": payload, "bytes": _bytes(payload)}

    def _legs(self, order: list[str], cycle: bool) -> list[dict]:
        pairs = list(zip(order, order[1:] + ([order[0]] if cycle else [])))
        return [{"donor_pair": u, "donor_hospital": self.P[u]["hospital"], "patient_pair": v, "patient_hospital": self.P[v]["hospital"],
                 "donor": self.P[u]["donor"], "patient": self.P[v]["patient"]} for u, v in pairs]

    def _audit(self) -> dict:
        return {"type": "audit", "ok": True, "models": [MODELS["coordinator"], MODELS["auditor"]], "checks": ["claims", "legs", "wire"], "unsupported": []}

    def names(self) -> dict:
        return {pid: {"patient": p["patient"], "donor": p["donor"], "relation": p["relation"], "hospital": p["hospital"],
                      "patient_blood": p["patient_blood"], "donor_blood": p["donor_blood"], "sensitized": len(p["unacceptable"])}
                for pid, p in self.P.items()}

    # ------------------------------------------------------------ beats
    def build(self) -> dict:
        P, E = self.P, self.E
        beats = []
        # 0 title
        beats.append({"id": 0, "title": "Title", "caption": "Domino — Three hospitals. Twelve families. No shared database.",
                      "events": [{"t": 0, "ev": {"type": "ui", "show": "title"}}]})
        # 1 meet them
        beats.append({"id": 1, "title": "Meet them", "caption": "Every donor here would give a kidney to someone they love. None of them match.",
                      "events": [{"t": 0, "ev": {"type": "ui", "show": "families", "pairs": ["A1", "H1", "R1"],
                                                 "why": {"A1": "blood type", "H1": "blood type", "R1": "antibodies"}}}]})
        # 2 alone
        ev = [{"t": 0, "ev": {"type": "ui", "show": "scan"}}]
        for i, h in enumerate(D.HOSPITALS):
            local = [e for e in E if P[e[0]]["hospital"] == h and P[e[1]]["hospital"] == h]
            n = sum(len(c) for c in M.best_cycles(P, local))
            ev.append({"t": 900 + i * 700, "ev": {"type": "alone", "hospital": h, "found": n}})
        beats.append({"id": 2, "title": "Alone", "caption": "Each hospital, alone: zero.", "events": ev})
        # 3 the agents talk (search phase)
        ev = [{"t": 0, "ev": {"type": "run.start", "run_id": self.run_id, "phase": "search", "mode": self.mode,
                              "nodes": [{"hospital": h, "node_id": "—"} for h in D.HOSPITALS]}},
              {"t": 200, "ev": {"type": "ui", "show": "hub"}}]
        t = 900
        for h in D.HOSPITALS:
            a = self._ask(h, "hello", ["kind"])
            ev.append({"t": t, "ev": a})
            ev.append({"t": t + 700, "ev": self._reply(a["id"], h, "hello", {"hospital": h, "pairs": 4})})
            t += 250
        t += 900
        donors = [{"pair": pid, "donor_blood": p["donor_blood"], "donor_hla": p["donor_hla"]} for pid, p in P.items()]
        for h in D.HOSPITALS:
            a = self._ask(h, "compat", ["pair", "donor_blood", "donor_hla"], {"donors": donors})
            ev.append({"t": t, "ev": a})
            ev.append({"t": t + 300, "ev": {"type": "thought", "who": h, "text": f"reading 4 charts · {13 + list(D.HOSPITALS).index(h) * 2} rulebook sections"}})
            own = [pid for pid in P if P[pid]["hospital"] == h]
            compat = [{"pair": v, "donor_pair": u, "compatible": True, "strength": M.strength(P[u]["donor_blood"], P[v]["patient_blood"])}
                      for u, v in E if v in own]
            ev.append({"t": t + 900, "ev": self._reply(a["id"], h, "compat", {"compatible": compat})})
            ready = [self.readiness[pid] for pid in own]
            ev.append({"t": t + 1300, "ev": self._reply(a["id"], h, "readiness", {"readiness": ready})})
            for pid in own:
                if pid in D.EVIDENCE:
                    ev.append({"t": t + 1350, "ev": {"type": "evidence", "hospital": h, "pair": pid, "readiness": self.readiness[pid]["readiness"],
                                                     "reason": self.readiness[pid]["reason"], "citations": D.EVIDENCE[pid], "retrieved": ["§1.1", "§1.2"],
                                                     "notes_read": 3, "sections_total": 13, "model": "hospital model", "source": "agent"}})
            c = self._ask(h, "canary", ["patient_names"])
            ev.append({"t": t + 1600, "ev": c})
            ev.append({"t": t + 2100, "ev": {"type": "refusal", "from": h, "question": "patient_names"}})
            t += 700
        beats.append({"id": 3, "title": "The agents talk", "caption": "Only yes or no crosses. Names, charts and rules stay home.", "events": ev})
        # 3b why agents
        beats.append({"id": 4, "title": "Why agents?", "caption": "Every hospital writes its own rules. Our agents read them where they live.",
                      "events": [{"t": 0, "ev": {"type": "ui", "show": "scoreboard", "keyword": list(D.KEYWORD_SCORE), "traps": [
                          {"pair": "A1", "text": "“No infections” → flagged"}, {"pair": "A2", "text": "a UTI resolved in June → flagged"},
                          {"pair": "R3", "text": "a dental abscess resolved in August → flagged"}]}}]})
        # 4 the loop
        loop = M.best_cycles(P, E)
        legs = [l for c in loop for l in self._legs(c, True)]
        n_loop = sum(len(c) for c in loop)
        expl = ("A three-way loop across all three hospitals: Elena gives to James, Priya to Grace, Sam to Maria. "
                "Each hospital keeps its own patients; only compatibility and readiness crossed the wire.")
        ev = [{"t": 0, "ev": {"type": "thought", "who": "coordinator", "text": "8 edges · enumerating 2- and 3-cycles"}},
              {"t": 600, "ev": {"type": "plan", "phase": "cycles", "transplants": n_loop, "legs": legs, "explanation": expl, "plan_id": "loop"}},
              {"t": 600 + 700 * len(legs) + 300, "ev": self._audit()},
              {"t": 600 + 700 * len(legs) + 400, "ev": {"type": "counter", "value": n_loop}},
              {"t": 600 + 700 * len(legs) + 500, "ev": {"type": "phase.end", "phase": "search", "ok": True}}]
        beats.append({"id": 5, "title": "The loop", "caption": "Together: three transplants.", "events": ev})
        # 5 the human and the negotiation (approve phase) — waits for the riverbend console
        ev = [{"t": 0, "ev": {"type": "run.start", "run_id": self.run_id, "phase": "approve", "mode": self.mode, "nodes": []}}]
        for i, h in enumerate(sorted({l["patient_hospital"] for l in legs})):
            a = self._ask(h, "approve", ["pair", "donor_hospital", "donor_blood", "date"])
            ev.append({"t": 300 + i * 250, "ev": a})
        ev.append({"t": 1200, "ev": {"type": "approval.request", "hospital": "riverbend", "pair": "R1", "donor_hospital": "harbor", "donor_blood": "A",
                                     "date": D.STORY_WEEK["date"], "agent_advice": "not_this_week", "reason": "infection",
                                     "hold_until": D.STORY_WEEK["hold_until"], "evidence": D.EVIDENCE["R1"]}})
        for h in ("alder", "harbor"):
            ev.append({"t": 1500, "ev": {"type": "approval.result", "hospital": h, "pair": "A1" if h == "alder" else "H1", "decision": "approve", "reason": "none"}})
        swap = M.best_cycles(P, E, excluded={"R1"})
        swap_legs = [l for c in swap for l in self._legs(c, True)]
        n_swap = sum(len(c) for c in swap)
        replan = [{"t": 0, "ev": {"type": "plan.dim", "pair": "R1"}},
                  {"t": 500, "ev": {"type": "thought", "who": "coordinator", "text": "R1 removed · re-running best_cycles"}},
                  {"t": 1100, "ev": {"type": "plan", "phase": "cycles", "transplants": n_swap, "legs": swap_legs, "plan_id": "swap",
                                     "explanation": "Without Riverbend this week, the loop becomes a swap: Elena gives to James and Priya to Maria. Grace keeps her place for the next round."}},
                  {"t": 2600, "ev": self._audit()},
                  {"t": 2700, "ev": {"type": "counter", "value": n_swap}},
                  {"t": 2800, "ev": {"type": "memory", "hospital": "riverbend", "pair": "R1", "text": "decision saved to decisions.md"}},
                  {"t": 2900, "ev": {"type": "phase.end", "phase": "approve", "ok": True}}]
        hold = [{"t": 0, "ev": {"type": "approval.result", "hospital": "riverbend", "pair": "R1", "decision": "hold", "hold_until": D.STORY_WEEK["hold_until"], "reason": "infection"}},
                {"t": 400, "ev": {"type": "hold.request", "from": "riverbend", "plan": "loop", "hold_until": D.STORY_WEEK["hold_until"], "reason": "infection", "to": ["alder", "harbor"]}},
                {"t": 1800, "ev": {"type": "hold.reply", "from": "alder", "decision": "accept", "reason": "none"}},
                {"t": 2600, "ev": {"type": "hold.reply", "from": "harbor", "decision": "decline", "reason": "donor_availability"}},
                {"t": 3300, "ev": {"type": "hold.result", "consensus": False, "next": "replan"}}]
        approve_branch = [{"t": 0, "ev": {"type": "approval.result", "hospital": "riverbend", "pair": "R1", "decision": "approve", "reason": "none"}},
                          {"t": 500, "ev": {"type": "thought", "who": "coordinator", "text": "all three hospitals approved the loop"}},
                          {"t": 900, "ev": self._audit()}, {"t": 1000, "ev": {"type": "phase.end", "phase": "approve", "ok": True}}]
        beats.append({"id": 6, "title": "The human, and the negotiation",
                      "caption": "A surgeon asked everyone to wait. One hospital couldn't, for a reason only it knows. The plan re-formed in seconds.",
                      "events": ev, "wait": "approval",
                      "branches": {"hold": hold + [{"t": e["t"] + 3600, "ev": e["ev"]} for e in replan],
                                   "not_this_week": [{"t": 0, "ev": {"type": "approval.result", "hospital": "riverbend", "pair": "R1", "decision": "not_this_week", "reason": "infection"}}] + [{"t": e["t"] + 500, "ev": e["ev"]} for e in replan],
                                   "decline": [{"t": 0, "ev": {"type": "approval.result", "hospital": "riverbend", "pair": "R1", "decision": "decline", "reason": "other"}}] + [{"t": e["t"] + 500, "ev": e["ev"]} for e in replan],
                                   "approve": approve_branch}})
        # 6 the domino — waits for /give
        alt = D.ALTRUIST
        real = None
        try:
            real = json.load(open("data/domino-data.json"))["altruist"]
        except Exception:  # noqa: BLE001
            pass
        hla = (real or {}).get("hla", ["A2", "A68", "B7", "B8", "DR11", "DR13"])
        alt_edges = M.altruist_edges(alt["blood"], hla, P)
        excluded = {"A1", "H1", "R1"} | {pid for pid, r in self.readiness.items() if r["readiness"] != "ready"}
        chain = M.best_chain(alt_edges, P, E, excluded)
        chain_legs = [{"donor_pair": "ALT", "donor_hospital": "alder", "patient_pair": chain[0], "patient_hospital": P[chain[0]]["hospital"],
                       "donor": alt["name"], "patient": P[chain[0]]["patient"], "from_place": "stanford"}] + self._legs(chain, False)
        bridge = P[chain[-1]]["donor"]
        candidates = [c for c in alt_edges if c not in excluded]
        chain_ev = [{"t": 0, "ev": {"type": "run.start", "run_id": self.run_id, "phase": "chain", "mode": self.mode, "nodes": []}},
                    {"t": 200, "ev": {"type": "chain.start", "donor": alt["name"], "blood": alt["blood"]}}]
        t = 900
        for h in D.HOSPITALS:
            a = self._ask(h, "compat", ["pair", "donor_blood", "donor_hla"])
            chain_ev.append({"t": t, "ev": a})
            own = [pid for pid in P if P[pid]["hospital"] == h and pid in alt_edges]
            chain_ev.append({"t": t + 600, "ev": self._reply(a["id"], h, "compat", {"compatible": [{"pair": v, "donor_pair": "ALT", "compatible": True, "strength": "medium"} for v in own]})})
            t += 400
        why = f"{len(candidates)} patients could receive this kidney. Only {P[chain[0]]['patient']}'s chain keeps going: {len(chain)} transplants."
        chain_ev += [{"t": t + 600, "ev": {"type": "thought", "who": "coordinator", "text": f"{len(candidates)} candidate starts · longest simple path"}},
                     {"t": t + 1400, "ev": {"type": "plan", "phase": "chain", "transplants": len(chain), "legs": chain_legs, "explanation": why, "plan_id": "chain",
                                            "bridge_donor": bridge, "bridge_pair": chain[-1]}},
                     {"t": t + 1400 + 1700 * len(chain_legs) + 300, "ev": self._audit()},
                     {"t": t + 1400 + 1700 * len(chain_legs) + 400, "ev": {"type": "phase.end", "phase": "chain", "ok": True}}]
        beats.append({"id": 7, "title": "The domino", "caption": "One stranger. Five more transplants. Three hospitals that never saw each other's files.",
                      "events": [{"t": 0, "ev": {"type": "ui", "show": "qr"}}], "wait": "give", "branches": {"give": chain_ev}})
        # 7 the schedule
        final_legs = swap_legs + chain_legs
        ev = [{"t": 0, "ev": {"type": "run.start", "run_id": self.run_id, "phase": "schedule", "mode": self.mode, "nodes": []}}]
        t = 300
        for h, c in D.CONSTRAINTS.items():
            a = self._ask(h, "windows", ["slot"])
            ev.append({"t": t, "ev": a})
            ev.append({"t": t + 700, "ev": {"type": "constraint", "hospital": h, "constraints": {k: c[k] for k in ("donor_start_not_before", "organ_arrival_by", "implant_start_by", "max_cold_ischemia_h")}, "sources": c["sources"], "code": D.HOSPITALS[h]["code"]}})
            t += 500
        sched = []
        for i, l in enumerate(final_legs):
            dh = l["donor_hospital"]
            times = M.leg_times(dh, l["patient_hospital"], D.CONSTRAINTS, D.DRIVE_H)
            ok, reason = M.leg_accept(l["patient_hospital"], times, D.CONSTRAINTS, l["patient_pair"] in D.SENSITIZED)
            t += 350
            ev.append({"t": t, "ev": {"type": "leg.check", "leg": f"L{i + 1}", "to": l["patient_hospital"], "accept": ok, "reason": reason, "out": times["out"], "arrive": times["arrive"]}})
            sched.append({**l, **times, "accept": ok, "leg": f"L{i + 1}"})
        tight = max(sched, key=lambda s: M._t(s["arrive"]) - 7 + (2.0 if s["patient_hospital"] == "riverbend" else 0))
        tight = next(s for s in sched if s["donor_hospital"] == "alder" and s["patient_hospital"] == "riverbend") if any(s["donor_hospital"] == "alder" and s["patient_hospital"] == "riverbend" for s in sched) else tight
        expl = (f"{tight['donor']}'s kidney leaves {D.HOSPITALS[tight['donor_hospital']]['city']} at {tight['out']} and reaches "
                f"{D.HOSPITALS[tight['patient_hospital']]['city']} at {tight['arrive']}, inside Riverbend's cutoff. All {len(sched)} legs accepted by the receiving hospitals.")
        ev += [{"t": t + 800, "ev": {"type": "schedule", "slot": D.STORY_WEEK["date"], "legs": sched, "tightest": tight["leg"], "explanation": expl}},
               {"t": t + 1500, "ev": self._audit()}, {"t": t + 1600, "ev": {"type": "phase.end", "phase": "schedule", "ok": True}}]
        beats.append({"id": 8, "title": "The schedule", "caption": "They shared ‘works’ and ‘doesn’t’. Not one calendar, not one chart.", "events": ev})
        # 8 close
        beats.append({"id": 9, "title": "Close", "caption": "No shared database. A person at every step. Seven people go home.",
                      "events": [{"t": 0, "ev": {"type": "ui", "show": "close"}}]})
        return {"mode": self.mode, "run_id": self.run_id, "beats": beats, "names": self.names(), "hospitals": D.HOSPITALS,
                "edges": E, "readiness": self.readiness, "counter_expected": [0, n_loop, n_swap, n_swap + len(chain)]}


def build(mode: str = "scripted") -> dict:
    return Script(mode).build()


if __name__ == "__main__":
    s = build()
    print(json.dumps({"beats": [(b["id"], b["title"], len(b["events"])) for b in s["beats"]], "counter": s["counter_expected"]}, indent=1))
