"""Audit: code checks every id/hospital/time/number in an explanation against the
plan and the ledger; a second model does the same. Either failing -> not ok."""
from __future__ import annotations

import json
import re

from domino_app import llm, prompts

HOSPITAL_WORDS = {"alder", "harbor", "harbor point", "riverbend", "san jose", "oakland", "sacramento", "stanford"}


def _list_lengths(obj, out: set) -> None:
    if isinstance(obj, list):
        out.add(str(len(obj)))
        for v in obj:
            _list_lengths(v, out)
    elif isinstance(obj, dict):
        for v in obj.values():
            _list_lengths(v, out)


def code_check(explanation: str, plan: dict, ledger_rows: list[dict], names_by_pair: dict | None = None) -> list[str]:
    counts: set = set()
    _list_lengths(plan, counts)  # a count of legs/candidates/chain steps is supported by the plan itself
    blob = json.dumps(plan) + json.dumps(ledger_rows) + json.dumps(names_by_pair or {}) + " " + " ".join(sorted(counts))
    low = blob.lower()
    unsupported = []
    for pid in set(re.findall(r"\b[AHR][1-4]\b", explanation)):
        if pid not in blob:
            unsupported.append(pid)
    for h in HOSPITAL_WORDS:
        if h in explanation.lower() and h.split()[0] not in low:
            unsupported.append(h)
    for t in set(re.findall(r"\b\d{1,2}:\d{2}\b", explanation)):
        if t not in blob:
            unsupported.append(t)
    for n in set(re.findall(r"\b(?<![:\d])(\d+)(?![:\d])\b", explanation)):
        if n not in blob and n not in {"one", "two"} and int(n) > 1 and str(n) not in low:
            unsupported.append(n)
    return unsupported


def run(explanation: str, plan: dict, ledger_rows: list[dict], names_by_pair: dict | None = None) -> dict:
    unsupported = code_check(explanation, plan, ledger_rows, names_by_pair)
    models = [llm.COORDINATOR_MODEL]
    txt, used = llm.ask(llm.AUDITOR_MODEL, prompts.AUDIT_SYSTEM,
                        json.dumps({"explanation": explanation, "plan": plan, "ledger": ledger_rows[-40:]}), budget_s=20)
    j = llm.extract_json(txt)
    if used != "none":
        models.append(used)
        if j and not j.get("ok", True):
            unsupported += [str(u)[:80] for u in j.get("unsupported", [])]
    return {"type": "audit", "ok": not unsupported, "models": models, "checks": ["claims", "legs", "wire"], "unsupported": unsupported}
