"""T02-T05: fixtures -> screening -> graph -> solver. No Flower involved.

Runs the exact same hospital logic (domino.hospital.logic) that executes in
the ClientApp, against three local stores, and the same solver the
coordinator uses. The Flower smoke test is scripts/flower-smoke-test.py.
"""
from __future__ import annotations

from pathlib import Path

from domino.coordinator.graph import build_graph
from domino.coordinator.solver import enumerate_candidates, solve
from domino.fixtures import FIXTURES, FIXTURES_PERTURBED_N0
from domino.hospital import logic
from domino.hospital.store import HospitalStore
from domino.protocol import CoordinatorRequest, MessageType


def _hospitals(tmp_path: Path, fixtures=FIXTURES) -> dict[str, HospitalStore]:
    stores = {}
    for hid in "ABC":
        s = HospitalStore(hid, tmp_path / f"hospital-{hid}")
        s.seed(fixtures, force=True)
        stores[hid] = s
    return stores


def _screen(stores: dict[str, HospitalStore]):
    """Two SCREEN rounds exactly like the ServerApp: catalog, then evaluate."""
    req1 = CoordinatorRequest(run_id="t", round_id="r1", message_type=MessageType.SCREEN_REQUEST)
    catalog = [logic.handle(s, req1) for s in stores.values()]
    donors = [d for e in catalog for d in e.donors]
    req2 = CoordinatorRequest(run_id="t", round_id="r2", message_type=MessageType.SCREEN_REQUEST, donors=donors)
    responses = [logic.handle(s, req2) for s in stores.values()]
    return build_graph(responses)


def test_t02_initial_edges_and_one_three_cycle(tmp_path):
    stores = _hospitals(tmp_path)
    vertices, edges = _screen(stores)
    assert set(edges) == {("P1", "P2"), ("P1", "W4"), ("P2", "P3"), ("P3", "P1")}
    cands = enumerate_candidates(vertices, edges)
    cycles = [c for c in cands if c.kind == "CYCLE"]
    assert len(cycles) == 1 and cycles[0].order == ("P1", "P2", "P3")
    plan = solve(vertices, edges)
    assert plan and plan.kind == "CYCLE" and plan.edges == [("P1", "P2"), ("P2", "P3"), ("P3", "P1")]
    assert plan.recipient_count == 3 and plan.hospitals == ["A", "B", "C"]
    # every hospital's local-only search finds nothing
    assert all(logic.local_search_count(s) == 0 for s in stores.values())


def test_t03_hold_removes_p2_no_exchange(tmp_path):
    stores = _hospitals(tmp_path)
    stores["B"].add_note("P2", "fictional new note")
    assert stores["B"].availability(stores["B"].records()["P2"]) == "REVIEW_REQUIRED"
    stores["B"].set_hold("P2", True)
    vertices, edges = _screen(stores)
    assert vertices["P2"]["availability"] == "HOLD"
    assert set(edges) == {("P3", "P1"), ("P1", "W4")}
    assert solve(vertices, edges) is None


def test_t04_n0_adds_edge_and_chain_with_p2_held(tmp_path):
    stores = _hospitals(tmp_path)
    stores["B"].set_hold("P2", True)
    ok, code = stores["C"].activate_donor("N0")
    assert ok, code
    vertices, edges = _screen(stores)
    assert ("N0", "P3") in edges
    plan = solve(vertices, edges)
    assert plan and plan.kind == "CHAIN" and plan.order == ["N0", "P3", "P1", "W4"]
    assert plan.recipient_count == 3
    assert "P2" not in plan.order


def test_t05_perturbed_n0_fails_screening_no_chain(tmp_path):
    stores = _hospitals(tmp_path, FIXTURES_PERTURBED_N0)
    stores["B"].set_hold("P2", True)
    assert stores["C"].activate_donor("N0")[0]
    vertices, edges = _screen(stores)
    assert ("N0", "P3") not in edges
    assert solve(vertices, edges) is None


def test_plan_hash_is_canonical_and_changes_with_versions(tmp_path):
    stores = _hospitals(tmp_path)
    v, e = _screen(stores)
    h1 = solve(v, e).hash
    assert len(h1) == 64
    stores["A"].mark_reviewed("P1")  # bumps record_version
    v2, e2 = _screen(stores)
    assert solve(v2, e2).hash != h1
