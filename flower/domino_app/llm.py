"""Model access with a time budget, a fallback and strict JSON extraction.

The Flower runtime injects FLWR_RUNTIME_BASE_URL / FLWR_RUNTIME_API_KEY. No
provider keys live in the repo. Every call is optional: on any failure the
caller gets None and uses code (rules / templates) instead.
"""
from __future__ import annotations

import json
import os
import re
import time

COORDINATOR_MODEL = os.environ.get("DOMINO_COORDINATOR_MODEL", "flower-endeavor-v1.0")
FALLBACK_MODEL = os.environ.get("DOMINO_FALLBACK_MODEL", "openai/gpt-5.6-sol")
AUDITOR_MODEL = os.environ.get("DOMINO_AUDITOR_MODEL", "openai/gpt-5.6-sol")
HOSPITAL_MODEL = os.environ.get("DOMINO_HOSPITAL_MODEL", "qwen3.5:4b")


def _client():
    base, key = os.environ.get("FLWR_RUNTIME_BASE_URL"), os.environ.get("FLWR_RUNTIME_API_KEY")
    if not base or not key:
        return None
    try:
        from openai import OpenAI

        return OpenAI(base_url=base, api_key=key, max_retries=0, timeout=25)
    except Exception:  # noqa: BLE001
        return None


def ask(model: str, instructions: str, prompt: str, budget_s: float = 25.0, fallback: str | None = None) -> tuple[str | None, str]:
    """Returns (text, model_used). text is None when no model answered in budget."""
    c = _client()
    if c is None:
        return None, "none"
    for m in [model] + ([fallback] if fallback else []):
        t0 = time.time()
        try:
            r = c.responses.create(model=m, input=prompt, instructions=instructions)
            txt = getattr(r, "output_text", None) or ""
            if txt.strip():
                return txt, m
        except Exception:  # noqa: BLE001
            pass
        if time.time() - t0 > budget_s:
            break
    return None, "none"


def extract_json(text: str | None) -> dict | None:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None
