"""Exact demo fixtures. ALL FICTIONAL. Names stay inside the hospital.

K0-K3 are software fixture ids. They are NOT HLA, NOT crossmatch, not anything
clinical. ABO letters are used only for the toy compatibility table.
"""
from __future__ import annotations

ABO_ALLOWED = {
    "O": {"O", "A", "B", "AB"},
    "A": {"A", "AB"},
    "B": {"B", "AB"},
    "AB": {"AB"},
}

# Local (private) record shape. Only tokens/ABO-of-donor/marker ever leave.
# vertex kinds: PAIRED (donor+recipient), ENDPOINT_ONLY (recipient, no donor),
# SOURCE_ONLY (non-directed donor).
FIXTURES: dict[str, list[dict]] = {
    "A": [
        {
            "vertex_token": "P1",
            "kind": "PAIRED",
            "recipient": {"name": "Maria", "abo": "A", "blocked": ["K0", "K2"]},
            "donor": {"donor_token": "P1.D", "abo": "B", "marker": "K1", "active": True},
        },
    ],
    "B": [
        {
            "vertex_token": "P2",
            "kind": "PAIRED",
            "recipient": {"name": "James", "abo": "B", "blocked": []},
            "donor": {"donor_token": "P2.D", "abo": "A", "marker": "K2", "active": True},
        },
        {
            "vertex_token": "W4",
            "kind": "ENDPOINT_ONLY",
            "recipient": {"name": "Noah", "abo": "B", "blocked": []},
            "donor": None,
        },
    ],
    "C": [
        {
            "vertex_token": "P3",
            "kind": "PAIRED",
            "recipient": {"name": "Elena", "abo": "A", "blocked": ["K3"]},
            "donor": {"donor_token": "P3.D", "abo": "A", "marker": "K3", "active": True},
        },
        {
            "vertex_token": "N0",
            "kind": "SOURCE_ONLY",
            "recipient": None,
            # inactive until activation (presenter button / QR page)
            "donor": {"donor_token": "N0", "abo": "A", "marker": "K0", "active": False},
        },
    ],
}

# T05: perturbed fixture where N0 fails screening everywhere: an ABO-AB donor
# is only allowed for AB recipients, and there are none. (K3 alone would still
# reach P1, so the perturbation is on ABO, not the marker.)
FIXTURES_PERTURBED_N0 = {
    **FIXTURES,
    "C": [
        FIXTURES["C"][0],
        {**FIXTURES["C"][1], "donor": {"donor_token": "N0", "abo": "AB", "marker": "K0", "active": False}},
    ],
}


def toy_compatible(donor_abo: str, donor_marker: str, recipient: dict | None) -> str:
    """Toy rule. Missing data -> UNKNOWN, never positive."""
    if recipient is None or donor_abo not in ABO_ALLOWED or not donor_marker:
        return "UNKNOWN"
    r_abo = recipient.get("abo")
    blocked = recipient.get("blocked")
    if r_abo is None or blocked is None:
        return "UNKNOWN"
    if r_abo in ABO_ALLOWED[donor_abo] and donor_marker not in set(blocked):
        return "TOY_CANDIDATE"
    return "NOT_CANDIDATE"
