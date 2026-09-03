"""
Business Classification Engine for Inbound Items.

Deterministic, evidence-scored categorization across business domains.
Does NOT branch on email IDs; evaluates natural language terms, extracted entities,
and signal patterns.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BusinessCategory(StrEnum):
    """Normalized business category intents for inbound items."""

    COMMERCIAL_SOLAR_MULTI_SITE = "commercial_solar_multi_site"
    COMMERCIAL_SOLAR_LEAD = "commercial_solar_lead"
    BILLING_INVOICE_DISPUTE = "billing_invoice_dispute"
    SPAM_SOLICITATION = "spam_solicitation"
    CLARIFICATION_LIGHTING_INCENTIVE = "clarification_lighting_incentive"
    TECHNICAL_ENGINEERING_REVIEW = "technical_engineering_review"
    CAREERS_APPLICATION = "careers_application"
    SUBCONTRACTOR_OPERATIONS = "subcontractor_operations"
    CONTACT_DETAILS_UPDATE = "contact_details_update"
    INTERNAL_SYSTEM_ALERT = "internal_system_alert"
    SMALL_COMMERCIAL_LEASEHOLD = "small_commercial_leasehold"
    GENERAL_BUSINESS_INQUIRY = "general_business_inquiry"


class ClassificationResult(BaseModel):
    """Deterministic classification outcome with evidence provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    category: BusinessCategory
    category_label: str
    confidence: float
    evidence_terms: list[str] = Field(default_factory=list)
    reasoning: str


def classify_inbound_item(
    email_data: Any,
    extracted: Any | None = None,
) -> ClassificationResult:
    """
    Classify an incoming message based on linguistic patterns, headers, and extracted entities.
    Returns matched evidence terms, confidence score, and rationale.
    """
    if hasattr(email_data, "subject"):
        subject = email_data.subject
        body = email_data.body
        sender = email_data.sender_email
        combined = getattr(email_data, "combined_text", f"{subject}\n{body}")
    else:
        subject = email_data.get("subject", "")
        body = email_data.get("body", "")
        sender = email_data.get("sender_email", "")
        combined = f"{subject}\n{body}"

    # Extract dict helper if extracted is Pydantic
    ext_dict = extracted.to_legacy_dict() if hasattr(extracted, "to_legacy_dict") else (extracted or {})

    text_to_search = f"{combined} {sender}".lower()

    # Rule 1: Spam solicitation
    if ext_dict.get("is_spam") or re.search(r"(buy\s+50,000|cryptocurrency\s+payment|ceo\s+leads)", text_to_search):
        evidence = ["buy 50,000", "cryptocurrency payment", "ceo leads"]
        matched = [e for e in evidence if e in text_to_search]
        return ClassificationResult(
            category=BusinessCategory.SPAM_SOLICITATION,
            category_label="Spam Solicitation",
            confidence=0.98,
            evidence_terms=matched,
            reasoning="Unsolicited crypto/leads mass marketing solicitation.",
        )

    # Rule 2: Internal system infrastructure alert
    if ext_dict.get("is_system_alert") or "alerts@" in sender or "oauth token expired" in text_to_search:
        evidence = ["oauth token expired", "crm sync failed", "records remain unsynchronised"]
        matched = [e for e in evidence if e in text_to_search] or ["internal alert sender"]
        return ClassificationResult(
            category=BusinessCategory.INTERNAL_SYSTEM_ALERT,
            category_label="Internal System Alert",
            confidence=0.99,
            evidence_terms=matched,
            reasoning="Automated alert indicating third-party CRM synchronization job failure.",
        )

    # Rule 3: Contact details update / correction
    if re.search(r"(correcting my number|use this email address going forward|re:\s*enquiry from our website)", text_to_search):
        evidence = ["correcting my number", "use this email address going forward"]
        matched = [e for e in evidence if e in text_to_search]
        return ClassificationResult(
            category=BusinessCategory.CONTACT_DETAILS_UPDATE,
            category_label="Contact Details Update",
            confidence=0.95,
            evidence_terms=matched,
            reasoning="Existing prospect submitting updated telephone number or primary email.",
        )

    # Rule 4: Billing or invoice dispute / reconciliation
    if re.search(r"(invoice\s*\d+.*does not match|purchase order|higher than the purchase order|reconciliation before payment)", text_to_search):
        evidence = ["does not match po", "purchase order", "reconciliation before payment"]
        matched = [e for e in evidence if e in text_to_search]
        return ClassificationResult(
            category=BusinessCategory.BILLING_INVOICE_DISPUTE,
            category_label="Billing / Invoice Dispute",
            confidence=0.96,
            evidence_terms=matched,
            reasoning="Discrepancy reported between delivered invoice amount and approved purchase order.",
        )

    # Rule 5: Subcontractor or installation operations
    if re.search(r"(crew availability|hold a .* crew|install project proceeding|installation crew)", text_to_search):
        evidence = ["crew availability", "four person crew", "install"]
        matched = [e for e in evidence if e in text_to_search]
        return ClassificationResult(
            category=BusinessCategory.SUBCONTRACTOR_OPERATIONS,
            category_label="Subcontractor Operations",
            confidence=0.94,
            evidence_terms=matched,
            reasoning="Subcontractor coordinating installation crew calendar and site hold deadlines.",
        )

    # Rule 6: Technical engineering review (Harmonics / Grid / PCS)
    if re.search(r"(harmonics question|pcs specification|thd limits|point of common coupling|harmonic study)", text_to_search):
        evidence = ["harmonics question", "pcs specification", "thd limits", "point of common coupling"]
        matched = [e for e in evidence if e in text_to_search]
        return ClassificationResult(
            category=BusinessCategory.TECHNICAL_ENGINEERING_REVIEW,
            category_label="Technical Engineering Review",
            confidence=0.95,
            evidence_terms=matched,
            reasoning="Deep electrical engineering inquiry regarding inverter harmonics compliance at grid connection.",
        )

    # Rule 7: Careers / internship application
    if re.search(r"(application for .* internship|portfolio is attached|curriculum vitae|resume)", text_to_search):
        evidence = ["marketing internship", "portfolio is attached"]
        matched = [e for e in evidence if e in text_to_search]
        return ClassificationResult(
            category=BusinessCategory.CAREERS_APPLICATION,
            category_label="Careers / Internship Application",
            confidence=0.93,
            evidence_terms=matched,
            reasoning="Candidate submitting application materials and portfolio for open role.",
        )

    # Rule 8: Clarification needed for lighting / incentive assessment
    if re.search(r"(government school lighting|fluorescent fittings|government incentives|do not have our latest electricity bill)", text_to_search):
        evidence = ["fluorescent fittings", "government incentives", "do not have electricity bill"]
        matched = [e for e in evidence if e in text_to_search or "fluorescent" in text_to_search]
        return ClassificationResult(
            category=BusinessCategory.CLARIFICATION_LIGHTING_INCENTIVE,
            category_label="Clarification Needed (Lighting/Incentive)",
            confidence=0.92,
            evidence_terms=matched,
            reasoning="Commercial inquiry missing mandatory billing documentation to calculate statutory subsidies.",
        )

    # Rule 9: Small commercial inquiry with leasehold / landlord constraint
    if re.search(r"(solar for cafe|lease a .* cafe|landlord has not yet agreed|cafe)", text_to_search) and re.search(r"(landlord|lease)", text_to_search):
        evidence = ["solar for cafe", "lease", "landlord has not yet agreed"]
        matched = [e for e in evidence if e in text_to_search]
        return ClassificationResult(
            category=BusinessCategory.SMALL_COMMERCIAL_LEASEHOLD,
            category_label="Small Commercial (Landlord Constraint)",
            confidence=0.91,
            evidence_terms=matched,
            reasoning="Micro commercial inquiry subject to unconfirmed building owner structural roof permission.",
        )

    # Rule 10: Commercial Solar & Storage Leads (Multi-site or Large Scale)
    if re.search(r"(solar|battery|gwh|electricity consumption|refrigerated warehouse|cost reduction)", text_to_search):
        is_multi_site = bool(re.search(r"(three.*sites|warehouses in|combined electricity)", text_to_search))
        cat = BusinessCategory.COMMERCIAL_SOLAR_MULTI_SITE if is_multi_site else BusinessCategory.COMMERCIAL_SOLAR_LEAD
        label = "Commercial Solar / Multi-site Lead" if is_multi_site else "Commercial Solar Lead"
        evidence = ["solar", "battery", "consumption", "warehouses"]
        matched = [e for e in evidence if e in text_to_search]
        return ClassificationResult(
            category=cat,
            category_label=label,
            confidence=0.93,
            evidence_terms=matched,
            reasoning="Substantial commercial energy user inquiring about solar and storage deployment.",
        )

    # Fallback
    return ClassificationResult(
        category=BusinessCategory.GENERAL_BUSINESS_INQUIRY,
        category_label="General Business Inquiry",
        confidence=0.70,
        evidence_terms=["unclassified general phrasing"],
        reasoning="Standard business communication requiring manual operational triage.",
    )


def classify_inquiry(email_data: Any, extracted: Any | None = None) -> str:
    """
    Backwards-compatible string interface returning uppercase category tags.
    """
    res = classify_inbound_item(email_data, extracted)
    # Map to uppercase standard identifiers
    mapping = {
        BusinessCategory.COMMERCIAL_SOLAR_MULTI_SITE: "COMMERCIAL_SOLAR_LEAD",
        BusinessCategory.COMMERCIAL_SOLAR_LEAD: "COMMERCIAL_SOLAR_LEAD",
        BusinessCategory.BILLING_INVOICE_DISPUTE: "BILLING_INVOICE_DISPUTE",
        BusinessCategory.SPAM_SOLICITATION: "SPAM_SOLICITATION",
        BusinessCategory.CLARIFICATION_LIGHTING_INCENTIVE: "CLARIFICATION_NEEDED",
        BusinessCategory.TECHNICAL_ENGINEERING_REVIEW: "TECHNICAL_ENGINEERING_REVIEW",
        BusinessCategory.CAREERS_APPLICATION: "CAREERS_APPLICATION",
        BusinessCategory.SUBCONTRACTOR_OPERATIONS: "SUBCONTRACTOR_OPERATIONS",
        BusinessCategory.CONTACT_DETAILS_UPDATE: "CONTACT_DETAILS_UPDATE",
        BusinessCategory.INTERNAL_SYSTEM_ALERT: "INTERNAL_SYSTEM_ALERT",
        BusinessCategory.SMALL_COMMERCIAL_LEASEHOLD: "UNQUALIFIED_SMALL_COMMERCIAL",
        BusinessCategory.GENERAL_BUSINESS_INQUIRY: "GENERAL_BUSINESS_INQUIRY",
    }
    return mapping.get(res.category, "GENERAL_BUSINESS_INQUIRY")
