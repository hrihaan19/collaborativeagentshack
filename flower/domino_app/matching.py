"""Pure matching code (self-contained copy for the FAB). Code decides; models explain."""
from __future__ import annotations

import itertools

BLOOD_OK = {"O": {"O", "A", "B", "AB"}, "A": {"A", "AB"}, "B": {"B", "AB"}, "AB": {"AB"}}


def compatible(donor_blood: str, donor_hla: list[str], patient_blood: str, unacceptable) -> bool:
    return patient_blood in BLOOD_OK.get(donor_blood, set()) and not (set(donor_hla) & set(unacceptable))


def strength(donor_blood: str, patient_blood: str) -> str:
    return "high" if donor_blood == patient_blood else "medium"


def best_cycles(pair_ids: list[str], hospital_of: dict[str, str], es: list[tuple[str, str]], excluded=None) -> list[list[str]]:
    ex = set(excluded or ())
    adj: dict[str, set[str]] = {}
    for u, v in es:
        if u not in ex and v not in ex:
            adj.setdefault(u, set()).add(v)
    ids = sorted(p for p in pair_ids if p not in ex)
    cycles = set()
    for k in (2, 3):
        for combo in itertools.permutations(ids, k):
            if combo[0] != min(combo):
                continue
            if all(combo[(i + 1) % k] in adj.get(combo[i], ()) for i in range(k)):
                cycles.add(combo)
    cycles = sorted(cycles)
    best, best_key = [], (0, 0)
    for r in range(1, len(cycles) + 1):
        for sel in itertools.combinations(cycles, r):
            used: set[str] = set()
            ok = True
            for c in sel:
                if used & set(c):
                    ok = False
                    break
                used |= set(c)
            if not ok:
                continue
            key = (sum(len(c) for c in sel), len({hospital_of[p] for c in sel for p in c}))
            if key > best_key or (key == best_key and list(sel) < best):
                best, best_key = list(sel), key
    return [list(c) for c in best]


def best_chain(alt_edges: list[str], es: list[tuple[str, str]], excluded) -> list[str]:
    ex = set(excluded)
    adj: dict[str, set[str]] = {}
    for u, v in es:
        if u not in ex and v not in ex:
            adj.setdefault(u, set()).add(v)
    best: list[str] = []

    def walk(path):
        nonlocal best
        if len(path) > len(best) or (len(path) == len(best) and path < best):
            best = list(path)
        for nxt in sorted(adj.get(path[-1], ())):
            if nxt not in path:
                walk(path + [nxt])

    for s in sorted(alt_edges):
        if s not in ex:
            walk([s])
    return best


def _t(h: str) -> float:
    hh, mm = h.split(":")
    return int(hh) + int(mm) / 60


def _s(x: float) -> str:
    return f"{int(x):02d}:{int(round((x - int(x)) * 60)):02d}"


DRIVE = {("harbor", "alder"): 1.0, ("alder", "harbor"): 1.0, ("alder", "riverbend"): 2.0, ("riverbend", "alder"): 2.0,
         ("riverbend", "harbor"): 1.5, ("harbor", "riverbend"): 1.5}


def leg_times(donor_hospital: str, patient_hospital: str, constraints: dict) -> dict:
    c = constraints.get(donor_hospital, {})
    start = max(7.0, _t(c["donor_start_not_before"]) if c.get("donor_start_not_before") else 0.0)
    out = start + 2.5
    arrive = out + DRIVE.get((donor_hospital, patient_hospital), 1.5)
    implant = arrive + 0.5
    return {"start": _s(start), "out": _s(out), "arrive": _s(arrive), "implant": _s(implant), "cold_h": round(implant - out, 2)}


def leg_accept(c: dict, times: dict, sensitized: bool) -> tuple[bool, str]:
    if c.get("organ_arrival_by") and _t(times["arrive"]) > _t(c["organ_arrival_by"]):
        return False, "arrival_cutoff"
    if c.get("implant_start_by") and _t(times["implant"]) > _t(c["implant_start_by"]):
        return False, "implant_cutoff"
    cap = c.get("sensitized_cap_h", c.get("max_cold_ischemia_h", 12)) if sensitized else c.get("max_cold_ischemia_h", 12)
    if times["cold_h"] > cap:
        return False, "cold_ischemia"
    return True, "none"
