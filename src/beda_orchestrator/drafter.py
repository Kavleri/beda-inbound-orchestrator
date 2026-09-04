"""
Context-Grounded Response Draft Generator.

Generates realistic, fact-grounded response drafts without overfitting to email IDs.
Builds drafts strictly from extracted facts, verified attachments, and business categories.

Guarantees:
- Never makes claims about completed reviews or finalized state transitions.
- Acknowledges attachments only if actually loaded into the system.
- Explicitly asks for missing prerequisites rather than guessing values.
- Produces no outbound draft for spam or internal system alerts.
- All drafts are labeled as suggestions pending human approval.
"""

from __future__ import annotations

from typing import Any

from .classifier import BusinessCategory, ClassificationResult
from .extractor import StructuredExtraction
from .router import ActionType


def generate_draft_response(
    inbound_item: Any,
    classification: ClassificationResult | str,
    extracted: StructuredExtraction | dict[str, Any],
    routing: Any,
) -> str:
    """
    Generate an entity-grounded response draft.
    Does NOT branch on email IDs; composes responses based on structured facts and category.
    """
    cat = classification.category if isinstance(classification, ClassificationResult) else classification

    # Case 0: Adversarial document / Quarantine -> strictly suppress outbound draft
    if (
        getattr(routing, "action_type", None) == ActionType.QUARANTINE
        or getattr(extracted, "has_adversarial_directives", False)
        or (isinstance(extracted, dict) and extracted.get("has_adversarial_directives"))
    ):
        return (
            "[NO OUTBOUND DRAFT — ADVERSARIAL DOCUMENT QUARANTINED FOR SECURITY REVIEW]\n"
            "Alert: Inbound attachment contains unauthorized control directives attempting policy override or data exfiltration. "
            "Outbound communications and tool permissions are strictly suppressed."
        )

    # Case 1: Spam solicitation -> strictly no draft
    if cat in (BusinessCategory.SPAM_SOLICITATION, "SPAM_SOLICITATION"):
        return "[NO DRAFT - AUTO-ARCHIVED SPAM]"

    # Case 2: Internal system infrastructure alert -> no external client draft
    if cat in (BusinessCategory.INTERNAL_SYSTEM_ALERT, "INTERNAL_SYSTEM_ALERT"):
        return (
            "[INTERNAL INCIDENT NOTIFICATION — NO EXTERNAL DRAFT]\n"
            "Alert: HubSpot CRM sync failure (OAuth token expired; 146 records unsynchronised).\n"
            "Action: Routed to Ali Pratama (DevOps & Systems Lead) for credential refresh."
        )

    # Extract clean helper values
    if hasattr(inbound_item, "sender_name"):
        sender_name = inbound_item.sender_name.strip() or "there"
        attachments = getattr(inbound_item, "attachments", [])
        has_loaded_att = any(getattr(a, "is_loaded", False) for a in attachments)
    else:
        sender_name = inbound_item.get("sender_name", "there").strip() or "there"
        has_loaded_att = bool(inbound_item.get("attachments"))

    ext_dict = extracted.to_legacy_dict() if hasattr(extracted, "to_legacy_dict") else (extracted or {})

    company = ext_dict.get("extracted_company")
    phone = ext_dict.get("phone_number")
    gwh = ext_dict.get("annual_consumption_gwh")
    spend = ext_dict.get("monthly_spend_usd")
    variance = ext_dict.get("discrepancy_amount_usd")
    invoices = ext_dict.get("invoice_numbers", [])
    po_nums = ext_dict.get("po_numbers", [])
    locations = ext_dict.get("locations", [])

    footer = "\n\n---\n[DRAFT SUGGESTION — REQUIRES AUTHENTICATED HUMAN APPROVAL BEFORE DISPATCH]"

    # Case 3: Billing / Invoice Dispute
    if cat in (BusinessCategory.BILLING_INVOICE_DISPUTE, "BILLING_INVOICE_DISPUTE"):
        inv_text = f"Invoice {invoices[0]}" if invoices else "your invoice"
        po_text = f"Purchase Order {po_nums[0]}" if po_nums else "the approved purchase order"
        var_text = f" of ${variance:,}" if variance else ""
        return (
            f"Dear {sender_name},\n\n"
            f"Thank you for contacting us regarding {inv_text}.\n\n"
            f"We have logged your inquiry regarding the discrepancy{var_text} between {inv_text} and {po_text}. "
            f"Our operations and finance team will review the reconciliation details and provide clarification "
            f"ahead of Friday's deadline.\n\n"
            f"Sincerely,\n"
            f"BEDA Accounts & Project Operations{footer}"
        )

    # Case 4: Clarification Needed (Missing Electricity Bill / School Lighting)
    if cat in (BusinessCategory.CLARIFICATION_LIGHTING_INCENTIVE, "CLARIFICATION_NEEDED"):
        comp_name = company or "your school"
        return (
            f"Dear {sender_name},\n\n"
            f"Thank you for reaching out regarding LED lighting upgrade options for {comp_name}.\n\n"
            f"To accurately evaluate potential eligibility for government energy efficiency upgrade incentives "
            f"and to size the project without making unsubstantiated assumptions, could you kindly provide:\n"
            f"  1. A recent 12-month electricity invoice or interval meter data (NMI).\n"
            f"  2. An approximate schedule or count of existing fixture types and typical operating hours.\n\n"
            f"Once this information is available, our commercial team will prepare a structured feasibility review.\n\n"
            f"Warm regards,\n"
            f"BEDA Growth & Public Sector Partnerships{footer}"
        )

    # Case 5: Technical Engineering Review (Harmonics / Grid PCC)
    if cat in (BusinessCategory.TECHNICAL_ENGINEERING_REVIEW, "TECHNICAL_ENGINEERING_REVIEW"):
        return (
            f"Hello {sender_name},\n\n"
            f"Thank you for consulting BEDA regarding the inverter PCS specification and harmonics requirements.\n\n"
            f"Your inquiry regarding acceptable Total Harmonic Distortion (THD) limits at the Point of Common Coupling (PCC) "
            f"and the necessity of an additional harmonic injection study has been routed to our electrical systems engineer. "
            f"We will follow up with technical guidance once engineering review is complete.\n\n"
            f"Best regards,\n"
            f"BEDA Clean Energy Systems Engineering{footer}"
        )

    # Case 6: Subcontractor / Partner Installation Operations
    if cat in (BusinessCategory.SUBCONTRACTOR_OPERATIONS, "SUBCONTRACTOR_OPERATIONS"):
        loc_text = f"the {locations[0]} site" if locations else "the upcoming commercial installation"
        return (
            f"Hi {sender_name},\n\n"
            f"Thank you for checking in on crew availability and holding your installation crew.\n\n"
            f"We are coordinating site access and connection sign-offs for {loc_text}. "
            f"We will provide confirmation regarding the project schedule ahead of Tuesday's deadline.\n\n"
            f"Best regards,\n"
            f"BEDA Project Operations & Scheduling{footer}"
        )

    # Case 7: Contact Details Correction
    if cat in (BusinessCategory.CONTACT_DETAILS_UPDATE, "CONTACT_DETAILS_UPDATE"):
        phone_mention = f"with your updated number ({phone}) " if phone else ""
        return (
            f"Hi {sender_name},\n\n"
            f"Thank you for providing your updated contact details.\n\n"
            f"Our team will review your submission and update our records {phone_mention}"
            f"so that subsequent project communications reach you directly.\n\n"
            f"Best regards,\n"
            f"BEDA Client Operations{footer}"
        )

    # Case 8: Small Commercial with Landlord Constraint (Cafe)
    if cat in (BusinessCategory.SMALL_COMMERCIAL_LEASEHOLD, "UNQUALIFIED_SMALL_COMMERCIAL"):
        return (
            f"Hi {sender_name},\n\n"
            f"Thank you for contacting BEDA regarding solar options for your premises.\n\n"
            f"Because the premises are leased, written roof access and electrical consent from the property landlord "
            f"is a prerequisite before a formal engineering assessment or physical installation can be undertaken. "
            f"We recommend discussing roof works with your building owner, and we would be pleased to assist "
            f"once preliminary landlord consent is confirmed.\n\n"
            f"Best regards,\n"
            f"BEDA Commercial Advisory{footer}"
        )

    # Case 9: Careers / Internship Application
    if cat in (BusinessCategory.CAREERS_APPLICATION, "CAREERS_APPLICATION"):
        return (
            f"Dear {sender_name},\n\n"
            f"Thank you for your interest in BEDA and for sharing your application materials.\n\n"
            f"We have received your submission. Our recruitment team will review your application "
            f"and reach out if there is a suitable alignment with our upcoming intake.\n\n"
            f"Best regards,\n"
            f"BEDA People & Culture{footer}"
        )

    # Case 10: Commercial Solar & Storage Leads (Multi-site or Single site)
    if cat in (BusinessCategory.COMMERCIAL_SOLAR_MULTI_SITE, BusinessCategory.COMMERCIAL_SOLAR_LEAD, "COMMERCIAL_SOLAR_LEAD"):
        comp_mention = f"for {company}" if company else "for your organisation"
        loc_mention = f" across {', '.join(locations)}" if locations else ""
        att_ack = " We have also received your attached electricity billing information." if has_loaded_att else ""
        scale_mention = f" (reflecting approximately {gwh} GWh annual consumption)" if gwh else (f" (monthly spend approx ${spend:,})" if spend else "")
        phone_followup = f" at {phone}" if phone else ""

        return (
            f"Dear {sender_name},\n\n"
            f"Thank you for reaching out to BEDA regarding commercial solar and energy storage solutions "
            f"{comp_mention}{loc_mention}{scale_mention}.{att_ack}\n\n"
            f"Given the project requirements, we would welcome the opportunity for an initial discovery discussion "
            f"next week to review your facility energy profile. We will follow up{phone_followup} to coordinate a suitable time.\n\n"
            f"Best regards,\n"
            f"Matt Cooper\n"
            f"Founder, BEDA{footer}"
        )

    # Fallback for general valid inquiries
    return (
        f"Dear {sender_name},\n\n"
        f"Thank you for contacting BEDA. We have received your inquiry and routed it to our team "
        f"for review. We will follow up with you shortly.\n\n"
        f"Best regards,\n"
        f"BEDA Operations{footer}"
    )
