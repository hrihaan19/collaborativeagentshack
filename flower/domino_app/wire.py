"""The wire carries only allowlisted fields, enforced in code in both directions.

Names, notes, citations, antibody lists, cPRA, calendars and donor availability
notes never cross. Donor HLA is allowed only in coordinator -> hospital compat asks.
"""
from __future__ import annotations

import json
import re
import time

FORBIDDEN_KEY = re.compile(r"name|note|citation|antigen|cpra|calendar|availab|quote|chart", re.I)
MAX_TEXT = 80

ASK = {
    "hello": {"kind"},
    "compat": {"kind", "donors"},                      # donors: [{pair, donor_blood, donor_hla}]
    "readiness": {"kind", "date"},
    "canary": {"kind", "question"},
    "approve": {"kind", "pair", "donor_hospital", "donor_blood", "date", "plan"},
    "hold": {"kind", "plan", "hold_until", "reason", "from"},
    "windows": {"kind", "slot"},
    "leg": {"kind", "leg", "pair", "donor_hospital", "out", "arrive", "implant", "cold_h"},
}
REPLY = {
    "hello": {"kind", "hospital", "pairs"},
    "compat": {"kind", "hospital", "compatible", "readiness"},   # compatible: [{pair, donor_pair, compatible, strength}]
    "readiness": {"kind", "hospital", "readiness"},              # [{pair, readiness, reason}]
    "canary": {"kind", "hospital", "refused"},
    "approve": {"kind", "hospital", "pair", "decision", "hold_until", "reason"},
    "hold": {"kind", "hospital", "decision", "reason"},
    "windows": {"kind", "hospital", "windows", "constraints", "sources"},
    "leg": {"kind", "hospital", "leg", "accept", "reason"},
    "refused": {"kind", "hospital", "refused"},
}
DONOR_KEYS = {"pair", "donor_blood", "donor_hla"}
COMPAT_KEYS = {"pair", "donor_pair", "compatible", "strength"}
READY_KEYS = {"pair", "readiness", "reason"}


class WireError(ValueError):
    pass


def _walk(obj, path="") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if FORBIDDEN_KEY.search(k) and k != "donor_hla":
                raise WireError(f"forbidden key {path}{k}")
            _walk(v, f"{path}{k}.")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk(v, f"{path}{i}.")
    elif isinstance(obj, str) and len(obj) > MAX_TEXT:
        raise WireError(f"free text over {MAX_TEXT} chars at {path}")


def assert_outbound(reply: dict) -> dict:
    """Hospital -> coordinator. Raises WireError on any non-allowlisted field."""
    kind = reply.get("kind")
    if kind not in REPLY:
        raise WireError(f"unknown reply kind {kind!r}")
    extra = set(reply) - REPLY[kind]
    if extra:
        raise WireError(f"non-allowlisted keys {sorted(extra)}")
    if "donor_hla" in json.dumps(reply):
        raise WireError("donor_hla may not leave a hospital")
    for item in reply.get("compatible", []) or []:
        if set(item) - COMPAT_KEYS:
            raise WireError("compat item keys")
    for item in reply.get("readiness", []) or []:
        if set(item) - READY_KEYS:
            raise WireError("readiness item keys")
    _walk(reply)
    return reply


def assert_inbound(ask: dict) -> dict:
    """Coordinator -> hospital."""
    kind = ask.get("kind")
    if kind not in ASK:
        raise WireError(f"unknown ask kind {kind!r}")
    extra = set(ask) - ASK[kind]
    if extra:
        raise WireError(f"non-allowlisted keys {sorted(extra)}")
    for d in ask.get("donors", []) or []:
        if set(d) - DONOR_KEYS:
            raise WireError("donor item keys")
    _walk(ask)
    return ask


class Ledger:
    """Every accepted message: kind, fields, bytes, time. Field names only."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def record(self, direction: str, who: str, msg: dict) -> int:
        n = len(json.dumps(msg, separators=(",", ":")).encode())
        self.rows.append({"dir": direction, "who": who, "kind": msg.get("kind"), "fields": sorted(msg), "bytes": n, "t": time.time()})
        return n
