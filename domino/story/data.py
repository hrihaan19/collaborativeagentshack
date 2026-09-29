"""Domino story data. ALL FICTIONAL. Synthetic patients, donors and hospitals.

Facts here are the verified facts from the build document (§3). If
data/domino-data.json is present it is loaded instead of the placeholder HLA
sets below (the placeholder antigens are constructed so that the compatibility
rule reproduces exactly the verified 8 edges; they are NOT the real file).
"""
from __future__ import annotations

import json
from pathlib import Path

HOSPITALS = {
    "alder": {"name": "Alder Medical Center", "city": "San Jose", "code": "AMC-KTP-04"},
    "harbor": {"name": "Harbor Point Hospital", "city": "Oakland", "code": "HPH-LD-12"},
    "riverbend": {"name": "Riverbend General", "city": "Sacramento", "code": "SW-TX-07"},
}

# pair id -> (hospital, patient name, patient blood, donor name, donor relation, donor blood)
PAIRS_RAW = [
    ("A1", "alder", "Maria", "A", "Elena", "sister", "B"),
    ("A2", "alder", "Hannah", "B", "Mark", "husband", "A"),
    ("A3", "alder", "Wei", "O", "Lin", "daughter", "AB"),
    ("A4", "alder", "Omar", "O", "Yusuf", "brother", "AB"),
    ("H1", "harbor", "James", "B", "Priya", "wife", "A"),
    ("H2", "harbor", "Kenji", "O", "Aiko", "wife", "B"),
    ("H3", "harbor", "Fatima", "B", "Samir", "brother", "A"),
    ("H4", "harbor", "Rosa", "O", "Luis", "son", "A"),
    ("R1", "riverbend", "Grace", "A", "Sam", "brother", "O"),
    ("R2", "riverbend", "David", "A", "Ruth", "mother", "B"),
    ("R3", "riverbend", "Aisha", "A", "Malik", "husband", "B"),
    ("R4", "riverbend", "Tom", "O", "Nora", "sister", "B"),
]

# Verified donor -> patient edges (donor pair id -> patient pair id)
VERIFIED_EDGES = [("A1", "H1"), ("H1", "A1"), ("H1", "R1"), ("R1", "A1"), ("H2", "A2"), ("A2", "R2"), ("R2", "H3"), ("H3", "R3")]

ALTRUIST = {"name": "the stranger", "blood": "O", "surgery_at": "alder"}

READINESS = {  # pair -> (readiness, reason)
    "R1": ("not_this_week", "infection"),
    "R4": ("not_this_week", "travel"),
    "H4": ("needs_review", "cardiac_clearance"),
}
KEYWORD_TRAPS = ["A1", "A2", "R3"]  # Maria "No infections", Hannah UTI June, Aisha abscess August
KEYWORD_SCORE = (9, 12)

CONSTRAINTS = {
    "alder": {"donor_start_not_before": "07:30", "organ_arrival_by": None, "implant_start_by": None, "max_cold_ischemia_h": 12, "sensitized_cap_h": 8, "sources": ["§3.3", "§3.2"]},
    "harbor": {"donor_start_not_before": None, "organ_arrival_by": None, "implant_start_by": "14:00", "max_cold_ischemia_h": 10, "sensitized_cap_h": 6, "sources": ["§2.3", "§2.2"]},
    "riverbend": {"donor_start_not_before": None, "organ_arrival_by": "13:00", "implant_start_by": None, "max_cold_ischemia_h": 12, "sensitized_cap_h": 12, "sources": ["§2.1", "§2.2"]},
}
DRIVE_H = {("harbor", "alder"): 1.0, ("alder", "harbor"): 1.0, ("alder", "riverbend"): 2.0, ("riverbend", "alder"): 2.0, ("riverbend", "harbor"): 1.5, ("harbor", "riverbend"): 1.5}
SENSITIZED = {"H3"}  # Fatima

EVIDENCE = {
    "R1": [
        {"doc": "protocol", "section": "SW-TX-07 §1.1", "quote": "Recipients must be afebrile and off intravenous antibiotics for 7 days before transplant."},
        {"doc": "R1_grace.md", "section": "2026-09-27", "quote": "Day 3 of IV ceftriaxone for pyelonephritis. Afebrile since this morning."},
    ],
    "R4": [{"doc": "protocol", "section": "SW-TX-07 §1.2", "quote": "Recipients travelling outside the region in the surgical week are deferred."},
           {"doc": "R4_tom.md", "section": "2026-09-22", "quote": "Confirms travel to Denver Sept 30 - Oct 4."}],
    "H4": [{"doc": "protocol", "section": "HPH-LD-12 §1.2", "quote": "Recipients aged 60 and over require cardiac clearance dated within 6 months."},
           {"doc": "H4_rosa.md", "section": "2026-01-14", "quote": "Cardiology clearance for transplant listing."}],
}

STORY_WEEK = {"date": "Fri 10/2", "hold_until": "2026-10-09"}

_BLOOD_OK = {"O": {"O", "A", "B", "AB"}, "A": {"A", "AB"}, "B": {"B", "AB"}, "AB": {"AB"}}


def pairs() -> dict[str, dict]:
    """Return the pool. Uses data/domino-data.json when present."""
    real = Path("data/domino-data.json")
    if real.exists():
        try:
            return _from_real(json.loads(real.read_text()))
        except Exception:  # noqa: BLE001 - fall back to placeholder, never crash the demo
            pass
    return _placeholder()


def _from_real(d: dict) -> dict[str, dict]:
    out = {}
    for p in d.get("pairs", []):
        out[p["id"]] = {
            "id": p["id"], "hospital": p["hospital"],
            "patient": p["patient"]["name"], "patient_blood": p["patient"]["blood"],
            "unacceptable": set(p["patient"].get("unacceptable_antigens", [])),
            "donor": p["donor"]["name"], "relation": p["donor"].get("relation", ""), "donor_blood": p["donor"]["blood"],
            "donor_hla": list(p["donor"].get("hla", [])), "source": "domino-data.json",
        }
    return out


def _placeholder() -> dict[str, dict]:
    """Construct antigen sets so the rule yields exactly VERIFIED_EDGES."""
    out = {pid: {"id": pid, "hospital": h, "patient": pn, "patient_blood": pb, "donor": dn, "relation": rel,
                 "donor_blood": db, "donor_hla": [f"X{pid}", "A2", "B7", "B44", "DR4", "DR15"], "unacceptable": set(),
                 "source": "placeholder"} for pid, h, pn, pb, dn, rel, db in PAIRS_RAW}
    allowed = set(VERIFIED_EDGES)
    for dp in out.values():
        for pp in out.values():
            if dp["id"] == pp["id"] and (dp["id"], pp["id"]) in allowed:
                continue
            blood_ok = pp["patient_blood"] in _BLOOD_OK[dp["donor_blood"]]
            if blood_ok and (dp["id"], pp["id"]) not in allowed:
                pp["unacceptable"].add(f"X{dp['id']}")  # the donor's unique antigen blocks this patient
    return out
