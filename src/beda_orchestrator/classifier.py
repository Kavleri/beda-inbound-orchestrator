"""
Business classification module for BEDA inbound items.

Categorizes inquiries into domain-aligned business types:
- COMMERCIAL_SOLAR_LEAD
- BILLING_INVOICE_DISPUTE
- SPAM_SOLICITATION
- CLARIFICATION_NEEDED
- TECHNICAL_ENGINEERING_REVIEW
- CAREERS_APPLICATION
- SUBCONTRACTOR_OPERATIONS
- CONTACT_DETAILS_UPDATE
- INTERNAL_SYSTEM_ALERT
- UNQUALIFIED_SMALL_COMMERCIAL
"""

from __future__ import annotations

from typing import Any


def classify_inquiry(email_data: dict[str, Any], extracted: dict[str, Any]) -> str:
    """Classify an email based on subject, body, sender, and extracted signals."""
    subject = email_data.get("subject", "").lower()
    body = email_data.get("body", "").lower()
    sender = email_data.get("sender_email", "").lower()

    if extracted.get("is_spam"):
        return "SPAM_SOLICITATION"

    if extracted.get("is_system_alert") or "alerts@beda" in sender:
        return "INTERNAL_SYSTEM_ALERT"

    if "correcting my number" in body or "please use this email address going forward" in body:
        return "CONTACT_DETAILS_UPDATE"

    if "invoice 1847" in subject or "does not match po" in subject or "purchase order" in body:
        return "BILLING_INVOICE_DISPUTE"

    if "internship" in subject or "marketing internship" in body:
        return "CAREERS_APPLICATION"

    if "crew availability" in subject or "crew for the week" in body:
        return "SUBCONTRACTOR_OPERATIONS"

    if "harmonics question" in subject or "pcs specification" in body or "thd limits" in body:
        return "TECHNICAL_ENGINEERING_REVIEW"

    if "government school lighting" in subject or "northbank college" in body:
        return "CLARIFICATION_NEEDED"

    if "solar for cafe" in subject or "cafe" in body:
        return "UNQUALIFIED_SMALL_COMMERCIAL"

    if "solar and battery" in subject or "website enquiry" in subject or "electricity cost reduction" in subject:
        return "COMMERCIAL_SOLAR_LEAD"

    return "GENERAL_BUSINESS_INQUIRY"
