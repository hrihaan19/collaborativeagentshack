"""Private retrieval: BM25 in pure Python over a hospital's own docs.

Chunks rulebooks by '### §' headings and charts by '## <date> · <type>' headings.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

TOKEN = re.compile(r"[a-z0-9§.]+")
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "be", "with", "by", "at", "as", "this",
        "that", "it", "from", "was", "were", "has", "have", "not", "no", "if", "than", "then", "before", "after"}
K1, B = 1.4, 0.75


def tokens(text: str) -> list[str]:
    return [t for t in TOKEN.findall(text.lower()) if t not in STOP]


def chunk(doc_name: str, text: str) -> list[dict]:
    out = []
    if re.search(r"^### §", text, re.M):
        parts = re.split(r"(?m)^(?=### §)", text)
    else:
        parts = re.split(r"(?m)^(?=## )", text)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        head = part.splitlines()[0].lstrip("# ").strip()
        m = re.search(r"§[0-9.]+", head)
        out.append({"doc": doc_name, "section": m.group(0) if m else head[:40], "text": part})
    return out


class Index:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self.tf = [Counter(tokens(c["text"])) for c in chunks]
        self.dl = [sum(t.values()) for t in self.tf]
        self.avg = (sum(self.dl) / len(self.dl)) if self.dl else 1.0
        self.df: Counter = Counter()
        for t in self.tf:
            self.df.update(t.keys())
        self.n = len(chunks)

    def score(self, q: str, i: int) -> float:
        s = 0.0
        for term in set(tokens(q)):
            f = self.tf[i].get(term, 0)
            if not f:
                continue
            idf = math.log(1 + (self.n - self.df[term] + 0.5) / (self.df[term] + 0.5))
            s += idf * f * (K1 + 1) / (f + K1 * (1 - B + B * self.dl[i] / self.avg))
        return s

    def search(self, q: str, k: int = 2, doc_filter=None) -> list[dict]:
        cands = [i for i, c in enumerate(self.chunks) if doc_filter is None or doc_filter(c)]
        ranked = sorted(cands, key=lambda i: -self.score(q, i))
        return [self.chunks[i] for i in ranked[:k] if self.score(q, i) > 0]


def build(docs_dir: str | Path) -> Index:
    chunks: list[dict] = []
    for p in sorted(Path(docs_dir).glob("**/*.md")):
        chunks += chunk(p.name, p.read_text(encoding="utf-8", errors="ignore"))
    return Index(chunks)


def for_pair(index: Index, pair_id: str, k_per_note: int = 2) -> dict:
    """Pair P: its chart notes + top-k rulebook sections per note + its decisions."""
    notes = [c for c in index.chunks if c["doc"].upper().startswith(pair_id.upper() + "_")]
    is_rule = lambda c: c["section"].startswith("§")  # noqa: E731
    sections: list[dict] = []
    for n in notes:
        for s in index.search(n["text"], k=k_per_note, doc_filter=is_rule):
            if s not in sections:
                sections.append(s)
    decisions = [c for c in index.chunks if c["doc"] == "decisions.md" and pair_id in c["text"]]
    return {"notes": notes, "sections": sections, "decisions": decisions,
            "sections_total": sum(1 for c in index.chunks if is_rule(c))}
