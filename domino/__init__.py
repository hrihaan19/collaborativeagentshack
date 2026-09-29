"""Domino - SYNTHETIC DEMO - NOT A CLINICAL MATCHING TOOL.

Cross-border kidney-exchange *discovery* prototype over Flower 1.39.0.
All data is fictional. Nothing here diagnoses, determines real suitability,
enrolls donors, collects health data, or schedules surgery.
"""

BANNER = "SYNTHETIC DEMO - NOT A CLINICAL MATCHING TOOL"
FLWR_VERSION = "1.39.0"

HOSPITALS = {
    "A": {"name": "Hospital A", "city": "Palo Alto", "country": "United States", "machine": "M1"},
    "B": {"name": "Hospital B", "city": "Tel Aviv", "country": "Israel", "machine": "M2"},
    "C": {"name": "Hospital C", "city": "Abu Dhabi", "country": "United Arab Emirates", "machine": "M3"},
}


def hospital_label(hid: str) -> str:
    h = HOSPITALS.get(hid)
    if not h:
        return f"Hospital {hid}"
    return f"{h['name']} - {h['city']}, {h['country']}"
