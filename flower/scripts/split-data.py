#!/usr/bin/env python
"""Split data/domino-data.json (repo root) into per-hospital private record sets
plus the public donor catalog the coordinator is allowed to hold.

  flower/data/<hospital>/records.json     private: names, notes, antibodies, calendar, constraints
  flower/data/<hospital>/docs/*.md        chart notes per pair + rulebook + donor availability (for BM25)
  flower/data/public-donors.json          public: pair, hospital, donor_blood, donor_hla (no names)

Each hospital Mac copies ONLY its own folder to ~/domino-data/<hospital>/.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "domino-data.json"
OUT = Path(__file__).resolve().parents[1] / "data"
d = json.loads(SRC.read_text())

CONSTRAINTS = {
    "alder": {"donor_start_not_before": "07:30", "organ_arrival_by": None, "implant_start_by": None, "max_cold_ischemia_h": 12, "sensitized_cap_h": 8},
    "harbor": {"donor_start_not_before": None, "organ_arrival_by": None, "implant_start_by": "14:00", "max_cold_ischemia_h": 10, "sensitized_cap_h": 6},
    "riverbend": {"donor_start_not_before": None, "organ_arrival_by": "13:00", "implant_start_by": None, "max_cold_ischemia_h": 12, "sensitized_cap_h": 12},
}
SOURCES = {"alder": ["§3.3", "§3.2"], "harbor": ["§2.3", "§2.2"], "riverbend": ["§2.1", "§2.2"]}
CODES = {"alder": "AMC-KTP-04", "harbor": "HPH-LD-12", "riverbend": "SW-TX-07"}
RULEBOOK = {
    "alder": ["### §1.1 Infection\nRecipients must be afebrile and off intravenous antibiotics for 7 days before transplant. A resolved past infection does not defer.",
              "### §1.2 Travel\nRecipients travelling outside the region in the surgical week are deferred.",
              "### §3.2 Cold ischemia\nCold ischemia max 12 h; 8 h if cPRA >= 80%.",
              "### §3.3 Donor start\nDonor surgeries start no earlier than 07:30."],
    "harbor": ["### §1.1 Infection\nActive infection on intravenous antibiotics defers transplant until 7 days afebrile.",
               "### §1.2 Cardiac clearance\nRecipients aged 60 and over require cardiac clearance dated within 6 months.",
               "### §2.2 Cold ischemia\nCold ischemia max 10 h; 6 h if cPRA >= 80%.",
               "### §2.3 Implant\nImplant must begin by 14:00."],
    "riverbend": ["### §1.1 Infection\nRecipients must be afebrile and off intravenous antibiotics for 7 days before transplant.",
                  "### §1.2 Travel\nRecipients travelling outside the region in the surgical week are deferred.",
                  "### §2.1 Arrival\nOrgans must arrive by 13:00 for same-day implant.",
                  "### §2.2 Cold ischemia\nCold ischemia max 12 h."],
}
AVAIL = {"A1": "Elena is flexible through 10/31.", "H1": "Priya's leave covers surgery only on or before 10/02. Not available after 10/02."}

public = []
for h in d["hospitals"]:
    pairs = [p for p in d["pairs"] if p["hospital"] == h]
    for p in pairs:
        p.setdefault("donor", {})["availability"] = AVAIL.get(p["id"], "Available the surgical week.")
        public.append({"pair": p["id"], "hospital": h, "donor_blood": p["donor"]["blood"], "donor_hla": p["donor"]["hla"]})
    rec = {"hospital": h, "pairs": pairs, "calendar": d["calendars"][h], "windows": d["expected_windows"][h],
           "constraints": CONSTRAINTS[h], "sources": SOURCES[h], "code": CODES[h]}
    hd = OUT / h
    (hd / "docs").mkdir(parents=True, exist_ok=True)
    (hd / "records.json").write_text(json.dumps(rec, indent=1))
    (hd / "docs" / f"{CODES[h]}-rulebook.md").write_text(f"# {CODES[h]} rulebook\n\n" + "\n\n".join(RULEBOOK[h]) + "\n")
    for p in pairs:
        (hd / "docs" / f"{p['id']}_{p['patient']['name'].lower()}.md").write_text(
            f"# {p['id']} chart\n\n## 2026-09-22 · note\n{p['patient']['notes']}\n\n## 2026-09-27 · donor\n{p['donor']['availability']}\n")
    (hd / "docs" / "decisions.md").write_text("# decisions\n")
(OUT / "public-donors.json").write_text(json.dumps(public, indent=1))
print("wrote", OUT, "hospitals:", list(d["hospitals"]), "public donors:", len(public))
