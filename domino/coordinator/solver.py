"""Exchange-graph solver (plain Python, deterministic).

Vertices: PAIRED (donor+recipient), ENDPOINT_ONLY (recipient only, e.g. W4),
SOURCE_ONLY (non-directed donor, e.g. N0).
Edge (u -> v): u's donor is a TOY_CANDIDATE for v's recipient.

Candidates: simple cycles of length 2-3 over PAIRED vertices, and chains
starting at an AVAILABLE SOURCE_ONLY vertex with up to 3 recipients that end
at an ENDPOINT_ONLY recipient. Select a vertex-disjoint set maximizing the
number of distinct recipients; ties broken by token order.

SYNTHETIC DEMO - NOT A CLINICAL MATCHING TOOL.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass, field

MAX_CYCLE = 3
MAX_CHAIN_RECIPIENTS = 3


@dataclass(frozen=True)
class Candidate:
    kind: str  # CYCLE | CHAIN
    order: tuple[str, ...]  # vertex tokens in plan order

    @property
    def edges(self) -> list[tuple[str, str]]:
        if self.kind == "CYCLE":
            return [(self.order[i], self.order[(i + 1) % len(self.order)]) for i in range(len(self.order))]
        return [(self.order[i], self.order[i + 1]) for i in range(len(self.order) - 1)]

    @property
    def recipients(self) -> tuple[str, ...]:
        return self.order if self.kind == "CYCLE" else self.order[1:]

    @property
    def vertices(self) -> frozenset[str]:
        return frozenset(self.order)


@dataclass
class Plan:
    kind: str
    order: list[str]
    edges: list[tuple[str, str]]
    roles: dict[str, str]
    recipient_count: int
    hospitals: list[str] = field(default_factory=list)
    record_versions: dict[str, int] = field(default_factory=dict)

    def canonical(self) -> dict:
        return {
            "kind": self.kind,
            "edges": [list(e) for e in self.edges],
            "roles": dict(sorted(self.roles.items())),
            "record_versions": dict(sorted(self.record_versions.items())),
            "hospitals": sorted(self.hospitals),
        }

    @property
    def hash(self) -> str:
        return hashlib.sha256(json.dumps(self.canonical(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _eligible(vertices: dict[str, dict]) -> dict[str, dict]:
    return {t: v for t, v in vertices.items() if v.get("availability") == "AVAILABLE"}


def enumerate_candidates(vertices: dict[str, dict], edges: list[tuple[str, str]]) -> list[Candidate]:
    elig = _eligible(vertices)
    adj: dict[str, set[str]] = {t: set() for t in elig}
    for u, v in edges:
        if u in elig and v in elig and u != v:
            adj[u].add(v)
    paired = sorted(t for t, v in elig.items() if v["kind"] == "PAIRED")
    endpoints = {t for t, v in elig.items() if v["kind"] == "ENDPOINT_ONLY"}
    sources = sorted(t for t, v in elig.items() if v["kind"] == "SOURCE_ONLY")

    cands: set[Candidate] = set()
    # cycles of length 2..3, canonical rotation = smallest token first
    for k in range(2, MAX_CYCLE + 1):
        for combo in itertools.permutations(paired, k):
            if combo[0] != min(combo):
                continue
            if all(combo[(i + 1) % k] in adj[combo[i]] for i in range(k)):
                cands.add(Candidate("CYCLE", tuple(combo)))
    # chains: source -> paired* -> endpoint, 1..MAX_CHAIN_RECIPIENTS recipients
    def walk(path: tuple[str, ...]) -> None:
        last = path[-1]
        n_rec = len(path) - 1
        for nxt in sorted(adj[last]):
            if nxt in path:
                continue
            if nxt in endpoints:
                if n_rec + 1 <= MAX_CHAIN_RECIPIENTS:
                    cands.add(Candidate("CHAIN", path + (nxt,)))
            elif elig[nxt]["kind"] == "PAIRED" and n_rec + 1 < MAX_CHAIN_RECIPIENTS:
                walk(path + (nxt,))

    for s in sources:
        walk((s,))
    return sorted(cands, key=lambda c: (c.kind, c.order))


def select(cands: list[Candidate]) -> list[Candidate]:
    """Max distinct recipients over vertex-disjoint candidates (tiny brute force)."""
    best: list[Candidate] = []
    best_key: tuple = (0, ())
    for r in range(1, len(cands) + 1):
        for combo in itertools.combinations(cands, r):
            used: set[str] = set()
            ok = True
            for c in combo:
                if used & c.vertices:
                    ok = False
                    break
                used |= c.vertices
            if not ok:
                continue
            n = sum(len(c.recipients) for c in combo)
            key = (n, tuple(sorted(-ord(ch) for c in combo for ch in "".join(c.order))))
            # tie-break: prefer lexicographically smaller token order
            tb = tuple(c.order for c in combo)
            if n > best_key[0] or (n == best_key[0] and (not best or tb < tuple(c.order for c in best))):
                best, best_key = list(combo), (n, key)
    return best


def validate(cand: Candidate, vertices: dict[str, dict], edges: list[tuple[str, str]]) -> None:
    """Independent re-check before proposing. Raises ValueError."""
    es = set(edges)
    for u, v in cand.edges:
        if (u, v) not in es:
            raise ValueError(f"edge {u}->{v} not in graph")
    for t in cand.order:
        if vertices[t].get("availability") != "AVAILABLE":
            raise ValueError(f"{t} not AVAILABLE")
    if cand.kind == "CYCLE":
        if not (2 <= len(cand.order) <= MAX_CYCLE):
            raise ValueError("cycle length")
        if any(vertices[t]["kind"] != "PAIRED" for t in cand.order):
            raise ValueError("cycle must be PAIRED only")
    else:
        if vertices[cand.order[0]]["kind"] != "SOURCE_ONLY":
            raise ValueError("chain must start at SOURCE_ONLY")
        if vertices[cand.order[-1]]["kind"] != "ENDPOINT_ONLY":
            raise ValueError("chain must end at ENDPOINT_ONLY")
        if any(vertices[t]["kind"] != "PAIRED" for t in cand.order[1:-1]):
            raise ValueError("chain interior must be PAIRED")
        if len(cand.recipients) > MAX_CHAIN_RECIPIENTS:
            raise ValueError("chain too long")
    if len(set(cand.order)) != len(cand.order):
        raise ValueError("repeated vertex")


def solve(vertices: dict[str, dict], edges: list[tuple[str, str]]) -> Plan | None:
    """Return the single best candidate as a Plan (the demo proposes one
    exchange at a time), or None if no feasible exchange exists."""
    cands = enumerate_candidates(vertices, edges)
    chosen = select(cands)
    if not chosen:
        return None
    # one exchange per plan: the one with most recipients, then token order
    best = sorted(chosen, key=lambda c: (-len(c.recipients), c.order))[0]
    validate(best, vertices, edges)
    roles: dict[str, str] = {}
    for t in best.order:
        k = vertices[t]["kind"]
        roles[t] = {"PAIRED": "PAIR", "ENDPOINT_ONLY": "CHAIN_END", "SOURCE_ONLY": "NON_DIRECTED_DONOR"}[k]
    hospitals = sorted({vertices[t]["hospital_id"] for t in best.order})
    versions = {t: int(vertices[t].get("record_version", 0)) for t in best.order}
    return Plan(best.kind, list(best.order), best.edges, roles, len(best.recipients), hospitals, versions)
