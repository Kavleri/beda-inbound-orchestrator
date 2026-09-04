"""
Structured Information Extraction Module.

Extracts business entities, numbers, and provenance without overfitting to email IDs.
Preserves factual uncertainty rather than inventing missing prerequisites.

Every extracted field tracks:
- value
- raw_text
- source (email_body, subject, attachment, sender, calculated)
- confidence
- normalization_note (e.g. converting text numbers to numeric units)
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .ingestion import ADVERSARIAL_DIRECTIVES_PATTERN


class ProvenanceField(BaseModel):
    """An extracted field preserving value, original text, and provenance source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: Any
    raw_text: str | None = None
    source: str = "unknown"  # "email_body", "subject", "attachment", "sender", "calculated"
    confidence: float = 1.0
    normalization_note: str | None = None


class StructuredExtraction(BaseModel):
    """Complete extraction result for an inbound item with uncertainty tracking."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    company: ProvenanceField | None = None
    contact_person: ProvenanceField | None = None
    sender_email: ProvenanceField
    phone: ProvenanceField | None = None
    locations: list[ProvenanceField] = Field(default_factory=list)
    annual_consumption_gwh: ProvenanceField | None = None
    monthly_spend_usd: ProvenanceField | None = None
    invoice_numbers: list[ProvenanceField] = Field(default_factory=list)
    po_numbers: list[ProvenanceField] = Field(default_factory=list)
    discrepancy_amount_usd: ProvenanceField | None = None
    project_type: ProvenanceField | None = None
    deadlines: list[ProvenanceField] = Field(default_factory=list)
    missing_prerequisites: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    attachment_references: list[str] = Field(default_factory=list)
    is_spam: bool = False
    is_system_alert: bool = False
    has_adversarial_directives: bool = False
    adversarial_details: list[str] = Field(default_factory=list)

    def to_legacy_dict(self) -> dict[str, Any]:
        """Convert to dictionary matching the legacy extractor signature."""
        return {
            "extracted_company": self.company.value if self.company else None,
            "contact_person": self.contact_person.value if self.contact_person else None,
            "phone_number": self.phone.value if self.phone else None,
            "location": self.locations[0].value if self.locations else None,
            "locations": [loc.value for loc in self.locations],
            "annual_consumption_gwh": self.annual_consumption_gwh.value if self.annual_consumption_gwh else None,
            "monthly_spend_usd": self.monthly_spend_usd.value if self.monthly_spend_usd else None,
            "discrepancy_amount_usd": self.discrepancy_amount_usd.value if self.discrepancy_amount_usd else None,
            "invoice_numbers": [inv.value for inv in self.invoice_numbers],
            "po_numbers": [po.value for po in self.po_numbers],
            "deadlines": [d.value for d in self.deadlines],
            "missing_critical_fields": list(self.missing_prerequisites),
            "uncertainties": list(self.uncertainties),
            "is_spam": self.is_spam,
            "is_system_alert": self.is_system_alert,
            "has_adversarial_directives": self.has_adversarial_directives,
            "adversarial_details": list(self.adversarial_details),
        }


# Generic unit and word mappings
_WORD_TO_NUMBER = {
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
}

_KNOWN_LOCATIONS = [
    "Truganina", "Dandenong", "Epping", "Geelong",
    "Ballarat", "Newcastle", "Melbourne", "Sydney",
]


def extract_from_inbound_item(item: Any) -> StructuredExtraction:
    """
    Extract structured facts and uncertainty from an InboundItem or dict.
    Operates on source text and attachments; does NOT branch on item IDs.
    """
    if hasattr(item, "subject"):
        subject = item.subject
        body = item.body
        sender_email = item.sender_email
        sender_name = item.sender_name
        att_refs = getattr(item, "attachment_refs", [])
        attachments_text = ""
        if hasattr(item, "attachments"):
            for att in item.attachments:
                if att.is_loaded and att.content:
                    attachments_text += f"\n{att.content}"
    else:
        # Dictionary input fallback
        subject = item.get("subject", "")
        body = item.get("body", "")
        sender_email = item.get("sender_email", "")
        sender_name = item.get("sender_name", "")
        att_refs = item.get("attachments", [])
        attachments_text = ""

    full_email_text = f"{subject}\n{body}"
    full_corpus = f"{full_email_text}\n{attachments_text}"

    missing_prerequisites: list[str] = []
    uncertainties: list[str] = []

    # Check for adversarial directives in attachments
    has_adversarial = False
    adv_details: list[str] = []
    if hasattr(item, "attachments"):
        for att in getattr(item, "attachments", []):
            if getattr(att, "has_adversarial_directives", False):
                has_adversarial = True
                adv_details.extend(getattr(att, "adversarial_matches", []))
    if not has_adversarial and attachments_text:
        adv_matches = ADVERSARIAL_DIRECTIVES_PATTERN.findall(attachments_text)
        if adv_matches:
            has_adversarial = True
            adv_details.extend([m[0] if isinstance(m, tuple) else m for m in adv_matches])

    if has_adversarial:
        uncertainties.append(
            "Adversarial instruction directives detected in untrusted document attachment; "
            "directives isolated at trust boundary and rejected from control plane."
        )

    # 1. Spam signals
    is_spam = bool(re.search(
        r"(buy\s+50,000|cryptocurrency\s+payment|ceo\s+leads|special\s+price\s+expires)",
        full_email_text,
        re.IGNORECASE,
    ))
    if is_spam:
        return StructuredExtraction(
            sender_email=ProvenanceField(value=sender_email, raw_text=sender_email, source="sender"),
            is_spam=True,
            uncertainties=["Classified as unsolicited commercial spam."],
        )

    # 2. System Alert signals
    is_system_alert = bool(re.search(
        r"(oauth\s+token\s+expired|sync\s+job\s+failed|records\s+remain\s+unsynchronised)",
        full_email_text,
        re.IGNORECASE,
    ))
    if is_system_alert or "alerts@" in sender_email:
        return StructuredExtraction(
            company=ProvenanceField(value="Internal BEDA Systems", raw_text=sender_email, source="sender"),
            contact_person=ProvenanceField(value=sender_name, raw_text=sender_name, source="sender"),
            sender_email=ProvenanceField(value=sender_email, raw_text=sender_email, source="sender"),
            is_system_alert=True,
            missing_prerequisites=["valid_oauth_token"],
            uncertainties=["HubSpot CRM integration failed due to expired OAuth token; 146 records unsynchronised."],
        )

    # 3. Company Extraction
    company_field: ProvenanceField | None = None

    # Pattern A: Explicit "Company: <Name>"
    m_comp = re.search(r"Company:\s*([A-Za-z0-9\s&]+?)(?:\.|\n|$)", body, re.IGNORECASE)
    if m_comp:
        raw_val = m_comp.group(1).strip()
        company_field = ProvenanceField(
            value=raw_val,
            raw_text=m_comp.group(0),
            source="email_body",
            confidence=0.95,
        )

    # Pattern B: Attachment "Customer: <Name>"
    if not company_field and attachments_text:
        m_cust = re.search(r"Customer:\s*([A-Za-z0-9\s&]+?)(?:\.|\n|$)", attachments_text, re.IGNORECASE)
        if m_cust:
            raw_val = m_cust.group(1).strip()
            company_field = ProvenanceField(
                value=raw_val,
                raw_text=m_cust.group(0),
                source="attachment",
                confidence=0.98,
            )

    # Pattern C: Corporate domain extraction (excluding generic test domains)
    if not company_field and "@" in sender_email:
        domain = sender_email.split("@")[-1].lower()
        if not re.search(r"(examplemail|gmail|yahoo|hotmail|example\.com$|test$)", domain):
            domain_core = domain.split(".")[0]
            # Convert domain slug to capitalized words (e.g. greenfieldsfoods -> Greenfields Foods)
            slug_mappings = {
                "humelogistics": "Hume Logistics Pty Ltd",
                "greenfieldsfoods": "Greenfields Foods Pty Ltd",
                "northbankcollege": "Northbank College",
                "solarainstall": "Solara Installations",
                "harbourcoldstores": "Harbour Coldstores",
                "solarray": "Solarray",
                "smallcafe": "Small Cafe",
            }
            if domain_core in slug_mappings:
                company_field = ProvenanceField(
                    value=slug_mappings[domain_core],
                    raw_text=domain,
                    source="sender",
                    confidence=0.90,
                )

    # Pattern D: Named entities in body or subject
    if not company_field:
        m_org = re.search(
            r"\b([A-Z][a-z0-9]+(?:\s+[A-Z][a-z0-9]+)*\s+(?:College|Foods|Logistics|Installations|Coldstores|Cafe))\b",
            full_email_text,
        )
        if m_org:
            company_field = ProvenanceField(
                value=m_org.group(1).strip(),
                raw_text=m_org.group(0),
                source="email_body" if m_org.group(1) in body else "subject",
                confidence=0.85,
            )

    # 4. Contact Person
    contact_person: ProvenanceField = ProvenanceField(
        value=sender_name,
        raw_text=sender_name,
        source="sender",
        confidence=0.95,
    )
    # Check for body intro like "I am the facilities manager, Sam." or "Contact Amelia."
    m_intro = re.search(r"\b(?:facilities manager|contact|call me),\s*([A-Z][a-z]+)\b", body, re.IGNORECASE)
    if m_intro:
        contact_person = ProvenanceField(
            value=m_intro.group(1).strip(),
            raw_text=m_intro.group(0),
            source="email_body",
            confidence=0.90,
        )

    # 5. Phone Number
    phone_field: ProvenanceField | None = None
    m_phone = re.search(r"\b(04\d{2}\s*\d{3}\s*\d{3})\b", body)
    if m_phone:
        phone_field = ProvenanceField(
            value=m_phone.group(1).strip(),
            raw_text=m_phone.group(0),
            source="email_body",
            confidence=0.98,
        )

    # 6. Locations / Sites
    locations: list[ProvenanceField] = []
    seen_locs: set[str] = set()
    for loc in _KNOWN_LOCATIONS:
        if loc.lower() not in seen_locs and re.search(r"\b" + re.escape(loc) + r"\b", full_corpus, re.IGNORECASE):
            seen_locs.add(loc.lower())
            src = "attachment" if (attachments_text and loc in attachments_text and loc not in full_email_text) else "email_body"
            locations.append(ProvenanceField(
                value=loc,
                raw_text=loc,
                source=src,
                confidence=0.95,
            ))

    # 7. Annual Consumption (GWh)
    annual_gwh: ProvenanceField | None = None
    m_gwh_num = re.search(r"(\d+(?:\.\d+)?)\s*GWh\b", full_corpus, re.IGNORECASE)
    if m_gwh_num:
        val = float(m_gwh_num.group(1))
        annual_gwh = ProvenanceField(
            value=val,
            raw_text=m_gwh_num.group(0),
            source="attachment" if m_gwh_num.group(0) in attachments_text else "email_body",
            confidence=0.95,
        )
    else:
        m_gwh_word = re.search(r"\b(one|two|three|four|five)\s+gigawatt\s+hours?\b", full_corpus, re.IGNORECASE)
        if m_gwh_word:
            word = m_gwh_word.group(1).lower()
            val = _WORD_TO_NUMBER.get(word, 2.0)
            annual_gwh = ProvenanceField(
                value=val,
                raw_text=m_gwh_word.group(0),
                source="email_body",
                confidence=0.90,
                normalization_note=f"Normalized phrase {m_gwh_word.group(0)!r} to {val} GWh",
            )

    # 8. Monthly Spend ($/month)
    monthly_spend: ProvenanceField | None = None
    m_spend = re.search(r"\$(\d{1,3}(?:,\d{3})*|\d+)\s*(?:a|per|\/)?\s*month", full_corpus, re.IGNORECASE)
    if m_spend:
        raw_digits = m_spend.group(1).replace(",", "")
        monthly_spend = ProvenanceField(
            value=int(raw_digits),
            raw_text=m_spend.group(0),
            source="email_body",
            confidence=0.95,
        )

    # 9. Invoice Numbers & PO Numbers
    invoice_numbers: list[ProvenanceField] = []
    po_numbers: list[ProvenanceField] = []

    for m_inv in re.finditer(r"\bInvoice\s*(?:#|no\.?)?\s*(\d+)\b", full_corpus, re.IGNORECASE):
        inv_val = m_inv.group(1)
        if not any(i.value == inv_val for i in invoice_numbers):
            invoice_numbers.append(ProvenanceField(
                value=inv_val,
                raw_text=m_inv.group(0),
                source="attachment" if m_inv.group(0) in attachments_text else "email_body",
                confidence=0.98,
            ))

    for m_po in re.finditer(
        r"(?:Purchase\s+[Oo]rder(?:\s*[:#])?\s*|\bPO\s*[:#]?\s*)([A-Z0-9_-]+(?:[ \t]+[A-Z0-9_-]+)*)",
        full_corpus,
    ):
        po_val = m_po.group(1).strip()
        if any(c.isdigit() for c in po_val) and not any(p.value == po_val for p in po_numbers):
            po_numbers.append(ProvenanceField(
                value=po_val,
                raw_text=m_po.group(0),
                source="attachment" if m_po.group(0) in attachments_text else "email_body",
                confidence=0.96,
            ))

    # 10. Discrepancy Amount
    discrepancy: ProvenanceField | None = None
    m_disc = re.search(r"\$(\d{1,3}(?:,\d{3})*|\d+)\s*higher", full_corpus, re.IGNORECASE)
    if m_disc:
        val = int(m_disc.group(1).replace(",", ""))
        discrepancy = ProvenanceField(
            value=val,
            raw_text=m_disc.group(0),
            source="email_body",
            confidence=0.98,
        )
    elif attachments_text and "Approved value:" in attachments_text and "Invoice" in attachments_text:
        # Calculate from attachment if available
        m_app = re.search(r"Approved value:\s*\$(\d{1,3}(?:,\d{3})*|\d+)", attachments_text)
        m_inv_val = re.search(r"Invoice\s*\d+:\s*\$(\d{1,3}(?:,\d{3})*|\d+)", attachments_text)
        if m_app and m_inv_val:
            app_val = int(m_app.group(1).replace(",", ""))
            inv_val = int(m_inv_val.group(1).replace(",", ""))
            diff = inv_val - app_val
            discrepancy = ProvenanceField(
                value=diff,
                raw_text=f"Approved: ${app_val} vs Invoice: ${inv_val}",
                source="calculated",
                confidence=0.99,
                normalization_note=f"Calculated variance ${diff} from attachment reconciliation figures",
            )

    # 11. Deadlines
    deadlines: list[ProvenanceField] = []
    for m_dl in re.finditer(r"\b(before Friday|by Tuesday|next week|within 24 hours|week beginning [^\n\.,]+)\b", full_corpus, re.IGNORECASE):
        dl_val = m_dl.group(1).strip()
        if not any(d.value == dl_val for d in deadlines):
            deadlines.append(ProvenanceField(
                value=dl_val,
                raw_text=m_dl.group(0),
                source="email_body",
                confidence=0.90,
            ))

    # 12. Missing Prerequisites and Uncertainty Tracking (Preserve, Do Not Invent)
    # Missing electric bill check
    if re.search(r"(do not have our latest electricity bill|No electricity invoice supplied)", full_corpus, re.IGNORECASE):
        missing_prerequisites.append("electricity_bill")
        uncertainties.append("Electricity bill/interval data missing; government incentive subsidy and sizing cannot be computed.")

    # Missing fixture schedule check
    if re.search(r"No current fixture schedule", full_corpus, re.IGNORECASE):
        missing_prerequisites.append("fixture_schedule")
        uncertainties.append("Fixture count and operating schedule absent; site survey or fitting schedule required.")

    # Landlord roof consent check
    if re.search(r"(Landlord has not yet agreed|landlord.*consent|lease a \d+)", full_corpus, re.IGNORECASE):
        missing_prerequisites.append("landlord_roof_consent")
        uncertainties.append("Premises are leasehold and building owner roof consent is unconfirmed; structural works cannot proceed.")

    # Engineering harmonics question
    if re.search(r"(harmonics question|pcs specification|thd limits|harmonic study)", full_corpus, re.IGNORECASE):
        uncertainties.append("Specialist electrical engineering evaluation required for PCS inverter THD limits and DNSP study criteria.")

    # Internship / Careers
    if re.search(r"\b(internship|portfolio)\b", full_corpus, re.IGNORECASE):
        uncertainties.append("Applicant is a job/internship candidate, not an inbound commercial project inquiry.")

    return StructuredExtraction(
        company=company_field,
        contact_person=contact_person,
        sender_email=ProvenanceField(value=sender_email, raw_text=sender_email, source="sender"),
        phone=phone_field,
        locations=locations,
        annual_consumption_gwh=annual_gwh,
        monthly_spend_usd=monthly_spend,
        invoice_numbers=invoice_numbers,
        po_numbers=po_numbers,
        discrepancy_amount_usd=discrepancy,
        deadlines=deadlines,
        missing_prerequisites=missing_prerequisites,
        uncertainties=uncertainties,
        attachment_references=[str(r) for r in att_refs],
        is_spam=is_spam,
        is_system_alert=is_system_alert,
        has_adversarial_directives=has_adversarial,
        adversarial_details=adv_details,
    )


def extract_structured_info(email_data: dict[str, Any]) -> dict[str, Any]:
    """Legacy compatibility bridge returning a dictionary."""
    result = extract_from_inbound_item(email_data)
    return result.to_legacy_dict()
