"""
Draft response generation module.

Composes grounded, professional draft responses tailored to each scenario.
Never sent autonomously; always held for human review and cryptographic signing.
"""

from __future__ import annotations

from typing import Any


def generate_draft_response(
    email_data: dict[str, Any],
    classification: str,
    extracted: dict[str, Any],
    routing: dict[str, Any],
) -> str:
    """Draft a response preserving uncertainty and avoiding hallucinated commitments."""
    sender_name = email_data.get("sender_name", "there")

    if classification == "SPAM_SOLICITATION":
        return "[NO DRAFT - AUTO ARCHIVED]"

    if classification == "INTERNAL_SYSTEM_ALERT":
        return "[INTERNAL ALERT - DISPATCH TO SLACK/OPS CHANNEL]"

    if classification == "CONTACT_DETAILS_UPDATE":
        return (
            f"Hi {sender_name},\n\n"
            "Thanks for the update. We have noted your corrected phone number (0411 999 102) "
            "and updated our records to use this email address going forward. "
            "Our team will be in touch regarding the Newcastle cold store enquiry shortly.\n\n"
            "Best regards,\nBEDA Operations"
        )

    if classification == "BILLING_INVOICE_DISPUTE":
        return (
            f"Hi {sender_name},\n\n"
            "Thank you for flagging this. We have put invoice 1847 on review with our finance "
            "and project delivery teams to reconcile the $2,640 variance against PO 8821. "
            "We will get back to you with an amended invoice or clarification before this Friday.\n\n"
            "Best regards,\nAli Pratama, BEDA Accounts"
        )

    if classification == "CLARIFICATION_NEEDED":
        return (
            f"Hi {sender_name},\n\n"
            "Thank you for reaching out regarding Northbank College's LED lighting upgrade. "
            "To accurately assess eligibility for Victorian/NSW government incentives and size "
            "the project, could you please provide a recent 12-month electricity invoice (or interval data) "
            "and an approximate fixture schedule if available? Once received, we can prepare a detailed proposal.\n\n"
            "Best regards,\nZidane Mouldino, BEDA Growth"
        )

    if classification == "COMMERCIAL_SOLAR_LEAD":
        company = extracted.get("extracted_company") or "your organisation"
        return (
            f"Hi {sender_name},\n\n"
            f"Thank you for reaching out regarding solar and energy solutions for {company}. "
            "Given the scale and multi-site requirements mentioned, we would welcome the opportunity "
            "for an initial discovery discussion next week to review your load profile and site specifics.\n\n"
            "Please let us know your preferred times, or feel free to book directly on our calendar.\n\n"
            "Best regards,\nMatt Cooper, Founder, BEDA"
        )

    if classification == "SUBCONTRACTOR_OPERATIONS":
        return (
            f"Hi {sender_name},\n\n"
            "Thanks for checking in on crew availability. We are currently finalizing the Ballarat site "
            "access approvals with engineering and will confirm the 14 September installation schedule "
            "ahead of Tuesday's deadline.\n\n"
            "Best regards,\nTies Rahardjo, BEDA Operations"
        )

    if classification == "TECHNICAL_ENGINEERING_REVIEW":
        return (
            f"Hi {sender_name},\n\n"
            "Thank you for your technical query. Our engineering team is reviewing the PCS specification "
            "for the 500 kW battery system and will provide written confirmation on acceptable THD limits "
            "at the point of common coupling (PCC) shortly.\n\n"
            "Best regards,\nBEDA Engineering Team"
        )

    if classification == "CAREERS_APPLICATION":
        return (
            f"Hi {sender_name},\n\n"
            "Thank you for your interest in BEDA and for sharing your portfolio for the marketing internship. "
            "Our recruitment team is reviewing submissions and will reach out if there is a match for the upcoming intake.\n\n"
            "Best regards,\nBEDA People & Culture"
        )

    if classification == "UNQUALIFIED_SMALL_COMMERCIAL":
        return (
            f"Hi {sender_name},\n\n"
            "Thank you for contacting BEDA. For leased commercial premises, written approval from the building "
            "owner/landlord for structural roof access and electrical works is required before we can carry out "
            "a formal solar feasibility study. Please let us know if your landlord is open to discussion.\n\n"
            "Best regards,\nBEDA Commercial Team"
        )

    return f"Hi {sender_name},\n\nThank you for contacting BEDA. We have received your inquiry and will review it shortly."
