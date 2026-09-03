"""
Entity resolution and fuzzy matching module.

Identifies:
1. Fuzzy duplicate companies in CRM (e.g. "Hume Logistic" vs "Hume Logistics Pty Ltd").
2. Cross-email contact updates (e.g. Sam in E009 and E010 with phone correction).
3. Exact or domain-level matching without external dependencies.
"""

from __future__ import annotations

import re
from typing import Any


def _normalize_company(name: str) -> str:
    """Normalize company name by stripping legal suffixes, punctuation, and plural 's'."""
    name = name.lower()
    # Remove common legal suffixes
    name = re.sub(r"\b(pty|ltd|limited|inc|corp|corporation)\b", "", name)
    # Remove punctuation and extra whitespace
    name = re.sub(r"[^\w\s]", " ", name)
    tokens = [t.rstrip("s") for t in name.split()]  # stem trailing 's'
    return " ".join(tokens)


def compute_token_similarity(str1: str, str2: str) -> float:
    """Compute token Jaccard similarity with stemmed tokens."""
    norm1 = _normalize_company(str1)
    norm2 = _normalize_company(str2)
    tokens1 = set(norm1.split())
    tokens2 = set(norm2.split())
    if not tokens1 or not tokens2:
        return 0.0
    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)
    return len(intersection) / len(union)


def find_crm_match(
    company_name: str | None,
    sender_email: str,
    crm_records: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """
    Search CRM for exact email match, domain match, or fuzzy company name match.
    """
    sender_domain = sender_email.split("@")[-1].lower() if "@" in sender_email else ""

    # 1. Exact email match
    for rec in crm_records:
        if rec.get("email") and rec["email"].lower() == sender_email.lower():
            return {"match_type": "exact_email", "record": rec, "confidence": 1.0}

    # 2. Company fuzzy match
    if company_name:
        for rec in crm_records:
            rec_comp = rec.get("company", "")
            sim = compute_token_similarity(company_name, rec_comp)
            if sim >= 0.5:  # e.g., 'hume logistic' matches 'hume logistics'
                return {"match_type": "fuzzy_company", "record": rec, "confidence": round(sim, 2)}

    # 3. Domain match (fallback)
    if sender_domain and sender_domain not in ("gmail.com", "examplemail.test", "example.com"):
        for rec in crm_records:
            rec_email = rec.get("email", "")
            if "@" in rec_email and rec_email.split("@")[-1].lower() == sender_domain:
                return {"match_type": "domain_match", "record": rec, "confidence": 0.8}

    return None
