from domino.story import data as D
from domino.story import matching as M


def test_exactly_the_eight_edges_and_none_inside_a_hospital():
    P = D.pairs()
    E = M.edges(P)
    assert E == sorted(D.VERIFIED_EDGES)
    assert all(P[u]["hospital"] != P[v]["hospital"] for u, v in E)
    for h in D.HOSPITALS:
        local = {p for p in P if P[p]["hospital"] == h}
        assert M.best_cycles(P, [e for e in E if e[0] in local and e[1] in local]) == []


def test_loop_then_swap():
    P = D.pairs()
    E = M.edges(P)
    assert M.best_cycles(P, E) == [["A1", "H1", "R1"]]
    assert M.best_cycles(P, E, excluded={"R1"}) == [["A1", "H1"]]


def test_unique_five_chain():
    P = D.pairs()
    E = M.edges(P)
    alt = M.altruist_edges("O", ["Z1", "Z2", "Z3", "Z4", "Z5", "Z6"], P)
    assert set(alt) == set(P)  # stranger compatible with everyone
    chain = M.best_chain(alt, P, E, excluded={"A1", "H1", "R1"})
    assert chain == ["H2", "A2", "R2", "H3", "R3"]


def test_timing_rule_reproduces_legs():
    T = lambda a, b: M.leg_times(a, b, D.CONSTRAINTS, D.DRIVE_H)  # noqa: E731
    assert (T("harbor", "alder")["out"], T("harbor", "alder")["arrive"]) == ("09:30", "10:30")
    assert (T("alder", "harbor")["out"], T("alder", "harbor")["arrive"]) == ("10:00", "11:00")
    t = T("alder", "riverbend")
    assert (t["out"], t["arrive"]) == ("10:00", "12:00") and M.leg_accept("riverbend", t, D.CONSTRAINTS, False) == (True, "none")
    t = T("riverbend", "harbor")
    assert (t["out"], t["arrive"]) == ("09:30", "11:00") and t["cold_h"] == 2.0
    assert M.leg_accept("harbor", t, D.CONSTRAINTS, True) == (True, "none")
    assert (T("harbor", "riverbend")["out"], T("harbor", "riverbend")["arrive"]) == ("09:30", "11:00")


def test_keyword_rules_are_measured_and_have_traps():
    ok, n, traps = D.keyword_eval()
    assert n == 12 and ok < n and {t["pair"] for t in traps} >= {"A1"}  # Maria's "No infections" is the canonical trap
    assert ok + len(traps) == n
