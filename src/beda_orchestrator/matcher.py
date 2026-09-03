"""
Entity Resolution, Duplicate Detection, and CRM Record Matching.

Implements two distinct concepts:
A. Duplicate / Related Inbound Submissions:
   - Identifies exact duplicates (idempotency key / content hash)
   - Identifies probable related submissions (e.g. E001 and E002 Hume Logistics; E009 and E010 Harbour Coldstores)
   - Flags ambiguous relationships for human review without premature merging.

B. CRM Record Matching:
   - Evaluates exact email, normalized phone, normalized company name, fuzzy token overlap, and domain.
   - Returns matched CRM ID or 'NONE', match type, score, evidence, and ambiguity flags.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SubmissionRelationship(StrEnum):
    """Classification of inbound submission relationship to prior items."""

    EXACT_DUPLICATE = "exact_duplicate"
    PROBABLE_RELATED_SUBMISSION = "probable_related_submission"
    NOT_DUPLICATE = "not_duplicate"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


class InboundDuplicateResult(BaseModel):
    """Evaluation of inbound submission against previously seen items."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: SubmissionRelationship
    related_to_item_id: str | None = None
    similarity_score: float = 0.0
    evidence: list[str] = Field(default_factory=list)
    explanation: str


class CRMMatchType(StrEnum):
    """Type of match found in CRM seed records."""

    EXACT_EMAIL = "exact_email"
    PHONE_MATCH = "phone_match"
    NORMALIZED_COMPANY = "normalized_company"
    FUZZY_COMPANY = "fuzzy_company"
    DOMAIN_MATCH = "domain_match"
    NONE = "none"


class CRMMatchResult(BaseModel):
    """Result of searching the CRM seed records for a matching entity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    matched_crm_id: str  # e.g. "C001" or "NONE"
    match_type: CRMMatchType
    score: float
    evidence: str
    ambiguity_flag: bool = False
    record: dict[str, Any] | None = None


def normalize_company_name(name: str | None) -> str:
    """Normalize company name by stripping legal suffixes, punctuation, and plural endings."""
    if not name:
        return ""
    name = name.lower()
    # Strip common corporate designations
    name = re.sub(r"\b(pty|ltd|limited|inc|corp|corporation|llc|co)\b", " ", name)
    # Strip non-alphanumeric characters
    name = re.sub(r"[^\w\s]", " ", name)
    # Stem trailing 's' for simple singular/plural invariance
    tokens = [t.rstrip("s") for t in name.split() if t]
    return " ".join(tokens)


def compute_token_similarity(str1: str, str2: str) -> float:
    """Compute token Jaccard similarity between two stemmed company strings."""
    norm1 = normalize_company_name(str1)
    norm2 = normalize_company_name(str2)
    tokens1 = set(norm1.split())
    tokens2 = set(norm2.split())
    if not tokens1 or not tokens2:
        return 0.0
    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)
    return len(intersection) / len(union)


def normalize_phone_digits(phone: str | None) -> str:
    """Extract digits only from phone string for deterministic equality comparison."""
    if not phone:
        return ""
    return re.sub(r"\D", "", phone)


def _get_item_field(item: Any, field_name: str, default: str = "") -> str:
    """Safely extract field from InboundItem or dict."""
    if hasattr(item, field_name):
        val = getattr(item, field_name)
        return str(val) if val is not None else default
    if isinstance(item, dict):
        val = item.get(field_name, default)
        return str(val) if val is not None else default
    return default


def check_inbound_relationship(
    current_item: Any,
    prior_items: list[Any],
    current_extracted: Any | None = None,
    prior_extractions: dict[str, Any] | None = None,
) -> InboundDuplicateResult:
    """
    Compare current inbound item against previously seen items in the pipeline session.
    Detects exact duplicate content and probable related submissions.
    """
    curr_id = _get_item_field(current_item, "id")
    curr_email = _get_item_field(current_item, "sender_email").lower()
    curr_hash = _get_item_field(current_item, "content_hash")
    curr_domain = curr_email.split("@")[-1] if "@" in curr_email else ""

    # Pull current extracted properties
    curr_phone = ""
    curr_comp = ""
    if current_extracted:
        if hasattr(current_extracted, "phone") and current_extracted.phone:
            curr_phone = normalize_phone_digits(current_extracted.phone.value)
        elif isinstance(current_extracted, dict):
            curr_phone = normalize_phone_digits(current_extracted.get("phone_number"))

        if hasattr(current_extracted, "company") and current_extracted.company:
            curr_comp = str(current_extracted.company.value)
        elif isinstance(current_extracted, dict):
            curr_comp = str(current_extracted.get("extracted_company", ""))

    for prev in prior_items:
        prev_id = _get_item_field(prev, "id")
        if prev_id == curr_id:
            continue

        prev_email = _get_item_field(prev, "sender_email").lower()
        prev_hash = _get_item_field(prev, "content_hash")
        prev_domain = prev_email.split("@")[-1] if "@" in prev_email else ""

        # 1. Exact Duplicate
        if curr_hash and prev_hash and curr_hash == prev_hash:
            return InboundDuplicateResult(
                decision=SubmissionRelationship.EXACT_DUPLICATE,
                related_to_item_id=prev_id,
                similarity_score=1.0,
                evidence=["Identical SHA-256 payload content hash"],
                explanation=f"Exact duplicate of prior submission {prev_id}.",
            )

        # Pull previous extracted properties
        prev_phone = ""
        prev_comp = ""
        if prior_extractions and prev_id in prior_extractions:
            p_ext = prior_extractions[prev_id]
            if hasattr(p_ext, "phone") and p_ext.phone:
                prev_phone = normalize_phone_digits(p_ext.phone.value)
            elif isinstance(p_ext, dict):
                prev_phone = normalize_phone_digits(p_ext.get("phone_number"))

            if hasattr(p_ext, "company") and p_ext.company:
                prev_comp = str(p_ext.company.value)
            elif isinstance(p_ext, dict):
                prev_comp = str(p_ext.get("extracted_company", ""))

        evidence: list[str] = []

        # Check phone match
        if curr_phone and prev_phone and curr_phone == prev_phone:
            evidence.append(f"Identical phone number digits ({curr_phone})")

        # Check company similarity
        comp_sim = 0.0
        if curr_comp and prev_comp:
            comp_sim = compute_token_similarity(curr_comp, prev_comp)
            if comp_sim >= 0.5:
                evidence.append(f"Company token similarity {comp_sim:.2f} ('{curr_comp}' vs '{prev_comp}')")

        # Check domain match (for non-generic domains)
        is_corporate_domain = (
            curr_domain and prev_domain and curr_domain == prev_domain
            and not re.search(r"(examplemail|gmail|yahoo|hotmail|test$|example\.com$)", curr_domain)
        )
        if is_corporate_domain:
            evidence.append(f"Identical corporate domain ({curr_domain})")

        # Check contact update signals
        curr_body = _get_item_field(current_item, "body").lower()
        if "correcting my number" in curr_body and is_corporate_domain:
            evidence.append("Explicit contact update referencing prior web form inquiry")

        # Determine if probable related submission
        if len(evidence) >= 2 or ("Explicit contact update" in " ".join(evidence)):
            return InboundDuplicateResult(
                decision=SubmissionRelationship.PROBABLE_RELATED_SUBMISSION,
                related_to_item_id=prev_id,
                similarity_score=max(0.85, comp_sim),
                evidence=evidence,
                explanation=f"Probable related submission to {prev_id} ({'; '.join(evidence)}). Preserving both records without auto-merge.",
            )
        elif len(evidence) == 1 and comp_sim >= 0.5:
            return InboundDuplicateResult(
                decision=SubmissionRelationship.NEEDS_HUMAN_REVIEW,
                related_to_item_id=prev_id,
                similarity_score=comp_sim,
                evidence=evidence,
                explanation=f"Possible relationship to {prev_id} on single attribute ({evidence[0]}). Requires human review.",
            )

    return InboundDuplicateResult(
        decision=SubmissionRelationship.NOT_DUPLICATE,
        related_to_item_id=None,
        similarity_score=0.0,
        evidence=[],
        explanation="No matching duplicate or related submission detected in current batch.",
    )


def find_crm_match(
    company_name: str | None,
    sender_email: str,
    crm_records: list[Any],
    sender_phone: str | None = None,
) -> CRMMatchResult:
    """
    Search CRM records with priority:
    1. Exact email match (highest priority, score 1.0)
    2. Normalized phone match (score 0.95)
    3. Normalized company name exact match (score 0.90)
    4. Fuzzy company token similarity (score 0.50 - 0.89)
    5. Corporate email domain match (score 0.75)
    """
    email_clean = sender_email.strip().lower()
    phone_clean = normalize_phone_digits(sender_phone)
    domain = email_clean.split("@")[-1] if "@" in email_clean else ""

    # Convert CRM records to uniform dict view if they are Pydantic models
    records_dict: list[dict[str, Any]] = []
    for r in crm_records:
        if hasattr(r, "model_dump"):
            records_dict.append(r.model_dump())
        elif isinstance(r, dict):
            records_dict.append(r)
        else:
            records_dict.append(vars(r))

    # 1. Exact Email Match
    email_candidates = [
        r for r in records_dict
        if r.get("email") and str(r["email"]).strip().lower() == email_clean
    ]
    if len(email_candidates) == 1:
        rec = email_candidates[0]
        return CRMMatchResult(
            matched_crm_id=rec["id"],
            match_type=CRMMatchType.EXACT_EMAIL,
            score=1.0,
            evidence=f"Exact email match on '{email_clean}'",
            ambiguity_flag=False,
            record=rec,
        )
    elif len(email_candidates) > 1:
        rec = email_candidates[0]
        return CRMMatchResult(
            matched_crm_id=rec["id"],
            match_type=CRMMatchType.EXACT_EMAIL,
            score=1.0,
            evidence=f"Multiple CRM records share exact email '{email_clean}' ({[r['id'] for r in email_candidates]})",
            ambiguity_flag=True,
            record=rec,
        )

    # 2. Normalized Phone Match
    if phone_clean:
        phone_candidates = [
            r for r in records_dict
            if r.get("phone") and normalize_phone_digits(str(r["phone"])) == phone_clean
        ]
        if len(phone_candidates) == 1:
            rec = phone_candidates[0]
            return CRMMatchResult(
                matched_crm_id=rec["id"],
                match_type=CRMMatchType.PHONE_MATCH,
                score=0.95,
                evidence=f"Normalized phone match on digits '{phone_clean}' (CRM contact: {rec.get('contact_name')})",
                ambiguity_flag=False,
                record=rec,
            )
        elif len(phone_candidates) > 1:
            rec = phone_candidates[0]
            return CRMMatchResult(
                matched_crm_id=rec["id"],
                match_type=CRMMatchType.PHONE_MATCH,
                score=0.95,
                evidence=f"Multiple CRM records share phone digits '{phone_clean}' ({[r['id'] for r in phone_candidates]})",
                ambiguity_flag=True,
                record=rec,
            )

    # 3. Normalized & Fuzzy Company Matching
    if company_name:
        norm_curr = normalize_company_name(company_name)
        scored_candidates: list[tuple[float, dict[str, Any]]] = []

        for rec in records_dict:
            rec_comp = rec.get("company", "")
            norm_rec = normalize_company_name(rec_comp)
            if norm_curr and norm_rec:
                if norm_curr == norm_rec:
                    scored_candidates.append((0.90, rec))
                else:
                    sim = compute_token_similarity(company_name, rec_comp)
                    if sim >= 0.5:
                        scored_candidates.append((round(sim, 2), rec))

        if scored_candidates:
            # Sort by highest similarity
            scored_candidates.sort(key=lambda x: x[0], reverse=True)
            best_score, best_rec = scored_candidates[0]
            # Check if there is ambiguity (two top scores equal)
            ambiguity = len(scored_candidates) > 1 and scored_candidates[0][0] == scored_candidates[1][0]
            m_type = CRMMatchType.NORMALIZED_COMPANY if best_score == 0.90 else CRMMatchType.FUZZY_COMPANY
            return CRMMatchResult(
                matched_crm_id=best_rec["id"],
                match_type=m_type,
                score=best_score,
                evidence=f"Company name match on '{company_name}' vs CRM '{best_rec['company']}' (similarity: {best_score})",
                ambiguity_flag=ambiguity,
                record=best_rec,
            )

    # 4. Corporate Domain Match (fallback)
    if domain and not re.search(r"(examplemail|gmail|yahoo|hotmail|test$|example\.com$)", domain):
        domain_candidates = [
            r for r in records_dict
            if r.get("email") and "@" in str(r["email"]) and str(r["email"]).split("@")[-1].lower() == domain
        ]
        if domain_candidates:
            rec = domain_candidates[0]
            ambiguity = len(domain_candidates) > 1
            return CRMMatchResult(
                matched_crm_id=rec["id"],
                match_type=CRMMatchType.DOMAIN_MATCH,
                score=0.75,
                evidence=f"Corporate email domain match on '{domain}' ({rec['company']})",
                ambiguity_flag=ambiguity,
                record=rec,
            )

    # No match found
    return CRMMatchResult(
        matched_crm_id="NONE",
        match_type=CRMMatchType.NONE,
        score=0.0,
        evidence="No matching CRM seed record found by email, phone, company, or domain.",
        ambiguity_flag=False,
        record=None,
    )
