"""Pure matching code. Code decides; models only explain."""
from __future__ import annotations

import itertools

BLOOD_OK = {"O": {"O", "A", "B", "AB"}, "A": {"A", "AB"}, "B": {"B", "AB"}, "AB": {"AB"}}


def compatible(donor_blood: str, donor_hla: list[str], patient_blood: str, unacceptable: set[str]) -> bool:
    return patient_blood in BLOOD_OK[donor_blood] and not (set(donor_hla) & set(unacceptable))


def strength(donor_blood: str, patient_blood: str) -> str:
    return "high" if donor_blood == patient_blood else "medium"


def edges(pairs: dict[str, dict]) -> list[tuple[str, str]]:
    out = []
    for d in pairs.values():
        for p in pairs.values():
            if d["id"] == p["id"]:
                continue
            if compatible(d["donor_blood"], d["donor_hla"], p["patient_blood"], p["unacceptable"]):
                out.append((d["id"], p["id"]))
    return sorted(out)


def altruist_edges(blood: str, hla: list[str], pairs: dict[str, dict]) -> list[str]:
    return sorted(p["id"] for p in pairs.values() if compatible(blood, hla, p["patient_blood"], p["unacceptable"]))


def best_cycles(pairs: dict[str, dict], es: list[tuple[str, str]], excluded: set[str] | None = None) -> list[list[str]]:
    """Disjoint 2- and 3-cycles maximizing transplants; tie-break more hospitals, then lexicographic."""
    ex = excluded or set()
    adj = {}
    for u, v in es:
        if u not in ex and v not in ex:
            adj.setdefault(u, set()).add(v)
    cycles: list[tuple[str, ...]] = []
    ids = sorted(p for p in pairs if p not in ex)
    for k in (2, 3):
        for combo in itertools.permutations(ids, k):
            if combo[0] != min(combo):
                continue
            if all(combo[(i + 1) % k] in adj.get(combo[i], ()) for i in range(k)):
                cycles.append(combo)
    cycles = sorted(set(cycles))
    best, best_key = [], (0, 0, ())
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
            n = sum(len(c) for c in sel)
            hosp = len({pairs[p]["hospital"] for c in sel for p in c})
            key = (n, hosp, tuple(-ord(ch) for c in sel for ch in "".join(c)))
            if key[:2] > best_key[:2] or (key[:2] == best_key[:2] and tuple(c for c in sel) < tuple(best)):
                best, best_key = list(sel), key
    return [list(c) for c in best]


def best_chain(alt_edges: list[str], pairs: dict[str, dict], es: list[tuple[str, str]], excluded: set[str]) -> list[str]:
    """Longest simple path starting from a pair the altruist can give to."""
    adj = {}
    for u, v in es:
        if u not in excluded and v not in excluded:
            adj.setdefault(u, set()).add(v)
    best: list[str] = []

    def walk(path: list[str]) -> None:
        nonlocal best
        if len(path) > len(best) or (len(path) == len(best) and path < best):
            best = list(path)
        for nxt in sorted(adj.get(path[-1], ())):
            if nxt not in path:
                walk(path + [nxt])

    for start in sorted(alt_edges):
        if start not in excluded:
            walk([start])
    return best


# ------------------------------------------------------------------ timing
def _t(h: str) -> float:
    hh, mm = h.split(":")
    return int(hh) + int(mm) / 60


def _s(x: float) -> str:
    return f"{int(x):02d}:{int(round((x - int(x)) * 60)):02d}"


def leg_times(donor_hospital: str, patient_hospital: str, constraints: dict, drive: dict) -> dict:
    c = constraints[donor_hospital]
    start = max(7.0, _t(c["donor_start_not_before"]) if c.get("donor_start_not_before") else 0.0)
    out = start + 2.5
    arrive = out + drive[(donor_hospital, patient_hospital)]
    implant = arrive + 0.5
    return {"start": _s(start), "out": _s(out), "arrive": _s(arrive), "implant": _s(implant), "cold_h": round(implant - out, 2)}


def leg_accept(patient_hospital: str, times: dict, constraints: dict, sensitized: bool) -> tuple[bool, str]:
    c = constraints[patient_hospital]
    if c.get("organ_arrival_by") and _t(times["arrive"]) > _t(c["organ_arrival_by"]):
        return False, "arrival_cutoff"
    if c.get("implant_start_by") and _t(times["implant"]) > _t(c["implant_start_by"]):
        return False, "implant_cutoff"
    cap = c["sensitized_cap_h"] if sensitized else c["max_cold_ischemia_h"]
    if times["cold_h"] > cap:
        return False, "cold_ischemia"
    return True, "none"
