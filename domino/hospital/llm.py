"""OPTIONAL local model at the hospital (Ollama, direct call on this machine).

Used for exactly one beat: reading a new private note and suggesting REVIEW.
Bounded: at most 3 model calls (1 call + up to 1 repair + 1 probe), 8 s
timeout, structured JSON output. The model can only *suggest* review. It can
never set AVAILABLE, clear a HOLD, or reach the approval endpoint - it has no
HTTP client to the console and returns a dict to the caller, nothing else.

If OLLAMA_URL is unset or the model fails: mode = "RULE-BASED FALLBACK" and
the rule (new note => REVIEW_REQUIRED) applies regardless.

Status label: IMPLEMENTED-UNVERIFIED until a hospital machine actually runs it.
"""
from __future__ import annotations

import json
import os

import httpx

OLLAMA_URL = os.environ.get("OLLAMA_URL")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")
TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "8"))
MAX_CALLS = 3

_SYSTEM = (
    "You read ONE fictional clinical-style note from a software demo. Reply with JSON only: "
    '{"suggest_review": true|false, "reason_code": "<one of NEW_FINDING|SCHEDULING|ADMIN|UNCLEAR>"}. '
    "Nothing here is real. Do not add any other keys or text."
)


def status() -> dict:
    if not OLLAMA_URL:
        return {"configured": False, "mode": "RULE-BASED FALLBACK", "label": "RULE-BASED FALLBACK (no OLLAMA_URL)"}
    return {"configured": True, "model": OLLAMA_MODEL, "url": OLLAMA_URL, "label": "IMPLEMENTED-UNVERIFIED until a call succeeds"}


def _call(messages: list[dict]) -> str:
    r = httpx.post(
        f"{OLLAMA_URL}/api/chat",
        json={"model": OLLAMA_MODEL, "messages": messages, "stream": False, "format": "json",
              "options": {"temperature": 0, "num_predict": 80}},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["message"]["content"]


def suggest_review(note_text: str) -> dict:
    """Never raises. Never returns model prose - only the two bounded fields."""
    if not OLLAMA_URL:
        return {"mode": "RULE-BASED FALLBACK", "suggest_review": None, "reason_code": None, "calls": 0}
    calls = 0
    messages = [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": note_text[:2000]}]
    try:
        while calls < MAX_CALLS - 1:
            calls += 1
            raw = _call(messages)
            try:
                obj = json.loads(raw)
                sr = obj.get("suggest_review")
                rc = str(obj.get("reason_code", "UNCLEAR"))[:16]
                if isinstance(sr, bool) and rc in {"NEW_FINDING", "SCHEDULING", "ADMIN", "UNCLEAR"}:
                    return {"mode": "LOCAL_MODEL_SUGGESTED", "suggest_review": sr, "reason_code": rc, "calls": calls,
                            "label": "VERIFIED local model call"}
            except (ValueError, AttributeError):
                pass
            # one repair attempt
            messages.append({"role": "assistant", "content": raw[:500]})
            messages.append({"role": "user", "content": "Invalid. Reply with exactly the JSON schema and nothing else."})
    except Exception:  # noqa: BLE001 - any failure -> fallback, never surface exception text
        pass
    return {"mode": "RULE-BASED FALLBACK", "suggest_review": None, "reason_code": None, "calls": calls}
