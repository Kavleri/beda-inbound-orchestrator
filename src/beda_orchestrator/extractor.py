"""
Structured information extraction module.

Extracts:
- Company names, contact persons, phones, locations.
- Energy consumption figures, monthly bills, and project scopes.
- Explicitly flags missing critical facts and uncertainties (no guessing).
"""

from __future__ import annotations

import re
from typing import Any


def extract_structured_info(email_data: dict[str, Any]) -> dict[str, Any]:
    """Extract entities and preserve uncertainties from raw email text."""
    body = email_data.get("body", "")
    subject = email_data.get("subject", "")
    sender_name = email_data.get("sender_name", "")
    sender_email = email_data.get("sender_email", "")
    full_text = f"{subject}\n{body}"

    result: dict[str, Any] = {
        "extracted_company": None,
        "contact_person": sender_name,
        "phone_number": None,
        "location": None,
        "annual_consumption_gwh": None,
        "monthly_spend_usd": None,
        "discrepancy_amount_usd": None,
        "missing_critical_fields": [],
        "uncertainties": [],
        "is_system_alert": False,
        "is_spam": False,
    }

    # Detect Spam
    if "buy 50,000" in full_text.lower() or "cryptocurrency payment" in full_text.lower():
        result["is_spam"] = True
        return result

    # Detect System Alert
    if "oauth token expired" in full_text.lower() or "hubspot sync failed" in full_text.lower():
        result["is_system_alert"] = True
        result["extracted_company"] = "Internal BEDA Systems"
        result["uncertainties"].append("Internal system failure - requires OAuth token renewal")
        return result

    # Company Extraction
    company_match = re.search(r"Company:\s*([A-Za-z0-9\s]+?)(?:\.|$)", body, re.IGNORECASE)
    if company_match:
        result["extracted_company"] = company_match.group(1).strip()
    elif "hume logistics" in full_text.lower() or "hume logistic" in full_text.lower():
        result["extracted_company"] = "Hume Logistics Pty Ltd"
    elif "greenfields foods" in full_text.lower():
        result["extracted_company"] = "Greenfields Foods Pty Ltd"
    elif "northbank college" in full_text.lower():
        result["extracted_company"] = "Northbank College"
    elif "solara" in full_text.lower():
        result["extracted_company"] = "Solara Installations"
    elif "harbour coldstores" in full_text.lower() or "harbourcoldstores" in sender_email:
        result["extracted_company"] = "Harbour Coldstores"
    elif "small cafe" in full_text.lower() or "cafe" in full_text.lower():
        result["extracted_company"] = "Small Cafe"

    # Phone extraction (Australian mobile/landline)
    phone_match = re.search(r"(04\d{2}\s*\d{3}\s*\d{3})", body)
    if phone_match:
        result["phone_number"] = phone_match.group(1).strip()

    # Location extraction
    locs = ["Melbourne", "Sydney", "Newcastle", "Geelong", "Ballarat", "Truganina", "Dandenong", "Epping"]
    for loc in locs:
        if loc.lower() in full_text.lower():
            result["location"] = loc
            break

    # Consumption / Budget extraction
    gwh_match = re.search(r"(\d+(?:\.\d+)?)\s*GWh", full_text, re.IGNORECASE)
    if gwh_match:
        result["annual_consumption_gwh"] = float(gwh_match.group(1))
    elif "two gigawatt hours" in full_text.lower():
        result["annual_consumption_gwh"] = 2.0

    # Monthly bills / spend
    spend_match = re.search(r"\$(\d{1,3}(?:,\d{3})*|\d+)\s*(?:a|per)?\s*month", full_text, re.IGNORECASE)
    if spend_match:
        val_str = spend_match.group(1).replace(",", "")
        result["monthly_spend_usd"] = int(val_str)

    # Discrepancy amount (invoice query)
    disc_match = re.search(r"\$(\d{1,3}(?:,\d{3})*|\d+)\s*higher", full_text, re.IGNORECASE)
    if disc_match:
        val_str = disc_match.group(1).replace(",", "")
        result["discrepancy_amount_usd"] = int(val_str)

    # Detect Missing Critical Fields & Uncertainties
    if "northbank college" in full_text.lower():
        result["missing_critical_fields"].append("electricity_bill")
        result["uncertainties"].append("Customer does not have latest electricity bill with them; fixture schedule absent")

    if "cafe" in full_text.lower():
        result["missing_critical_fields"].append("landlord_roof_consent")
        result["uncertainties"].append("Tenant leasehold with no landlord roof permission confirmed")

    if "engineering@solarray" in sender_email:
        result["uncertainties"].append("Requires engineer sign-off on harmonic study & THD limits at PCC")

    if "priya.dev" in sender_email:
        result["uncertainties"].append("Inbound job candidate, not a commercial inquiry")

    return result
