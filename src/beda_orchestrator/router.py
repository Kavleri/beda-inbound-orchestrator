"""
Routing and staff assignment module.

Maps classified inquiries to responsible BEDA staff owners:
- Matt Cooper: Major commercial opportunities & strategic partnerships.
- Ties Rahardjo: Scheduling, administration, logistics, partner ops.
- Zidane Mouldino: Marketing, website, inbound growth, internship apps.
- Ali Pratama: CRM, systems, workflows, data, infrastructure alerts, billing reconciliation.
"""

from __future__ import annotations

from typing import Any


def determine_routing_and_staff(
    classification: str,
    extracted: dict[str, Any],
    crm_match: dict[str, Any] | None,
) -> dict[str, Any]:
    """Determine recommended next action, assigned BEDA owner, and approval requirements."""

    if classification == "SPAM_SOLICITATION":
        return {
            "assigned_staff": "Automated Filter",
            "staff_email": "system@wearebeda.com",
            "action": "AUTO_ARCHIVE_SPAM",
            "requires_human_approval": False,
            "priority": "LOW",
            "recommendation": "Automatically archive junk solicitation. No response sent.",
        }

    if classification == "INTERNAL_SYSTEM_ALERT":
        return {
            "assigned_staff": "Ali Pratama (Senior Business Analyst)",
            "staff_email": "ali@wearebeda.com",
            "action": "URGENT_INFRASTRUCTURE_REMEDIATION",
            "requires_human_approval": True,
            "priority": "CRITICAL",
            "recommendation": "Refresh expired HubSpot OAuth token and trigger sync replay for 146 stalled records.",
        }

    if classification == "BILLING_INVOICE_DISPUTE":
        return {
            "assigned_staff": "Ali Pratama & Ties Rahardjo",
            "staff_email": "ali@wearebeda.com",
            "action": "FINANCE_RECONCILIATION_HOLD",
            "requires_human_approval": True,
            "priority": "HIGH",
            "recommendation": "Hold invoice 1847 payment; reconcile $2,640 variance against PO 8821 before Friday.",
        }

    if classification == "COMMERCIAL_SOLAR_LEAD":
        # Check scale: 2.1 GWh or $80,000/month are enterprise
        is_major = (
            (extracted.get("annual_consumption_gwh") or 0) >= 1.0
            or (extracted.get("monthly_spend_usd") or 0) >= 20_000
        )
        owner = "Matt Cooper (Founder)" if is_major else "Zidane Mouldino (Growth)"
        email = "matt@wearebeda.com" if is_major else "zidane@wearebeda.com"
        action = "ESCALATE_TO_FOUNDER_COMMERCIAL" if is_major else "QUALIFY_INBOUND_LEAD"
        return {
            "assigned_staff": owner,
            "staff_email": email,
            "action": action,
            "requires_human_approval": True,
            "priority": "HIGH" if is_major else "MEDIUM",
            "recommendation": "Schedule discovery call and prepare initial multi-site feasibility review.",
        }

    if classification == "CONTACT_DETAILS_UPDATE":
        return {
            "assigned_staff": "Ali Pratama (CRM & Data)",
            "staff_email": "ali@wearebeda.com",
            "action": "UPDATE_CRM_CONTACT_RECORD",
            "requires_human_approval": True,
            "priority": "MEDIUM",
            "recommendation": "Update Sam's mobile to 0411 999 102 and associate primary email to sam@harbourcoldstores.example.",
        }

    if classification == "CLARIFICATION_NEEDED":
        return {
            "assigned_staff": "Zidane Mouldino (Growth) & Ties Rahardjo",
            "staff_email": "zidane@wearebeda.com",
            "action": "REQUEST_MISSING_BILL_AND_SCHEDULE",
            "requires_human_approval": True,
            "priority": "MEDIUM",
            "recommendation": "Respond requesting recent electricity invoice and current lighting fixture schedule.",
        }

    if classification == "SUBCONTRACTOR_OPERATIONS":
        return {
            "assigned_staff": "Ties Rahardjo (Executive Operations Coordinator)",
            "staff_email": "ties@wearebeda.com",
            "action": "CONFIRM_CREW_SCHEDULE_BALLARAT",
            "requires_human_approval": True,
            "priority": "HIGH",
            "recommendation": "Coordinate with engineering and confirm whether Ballarat commercial install proceeds on Sep 14.",
        }

    if classification == "TECHNICAL_ENGINEERING_REVIEW":
        return {
            "assigned_staff": "Ali Pratama (Systems) & Lead Engineer",
            "staff_email": "ali@wearebeda.com",
            "action": "TECHNICAL_HARMONIC_STUDY_REVIEW",
            "requires_human_approval": True,
            "priority": "MEDIUM",
            "recommendation": "Provide THD limits at PCC for 500 kW battery PCS and advise on harmonic study requirement.",
        }

    if classification == "CAREERS_APPLICATION":
        return {
            "assigned_staff": "Zidane Mouldino & Ties Rahardjo",
            "staff_email": "zidane@wearebeda.com",
            "action": "REVIEW_INTERN_PORTFOLIO",
            "requires_human_approval": True,
            "priority": "LOW",
            "recommendation": "Acknowledge receipt of marketing intern portfolio and route to hiring team.",
        }

    if classification == "UNQUALIFIED_SMALL_COMMERCIAL":
        return {
            "assigned_staff": "Zidane Mouldino (Inbound)",
            "staff_email": "zidane@wearebeda.com",
            "action": "CHECK_LANDLORD_FEASIBILITY",
            "requires_human_approval": True,
            "priority": "LOW",
            "recommendation": "Advise that roof permission from the property landlord is a prerequisite before a quote can be issued.",
        }

    return {
        "assigned_staff": "Ties Rahardjo",
        "staff_email": "ties@wearebeda.com",
        "action": "GENERAL_HUMAN_TRIAGE",
        "requires_human_approval": True,
        "priority": "MEDIUM",
        "recommendation": "Standard triage review required.",
    }
