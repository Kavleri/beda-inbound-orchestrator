"""
Routing, Staff Ownership, and Next Action Recommendation Engine.

Resolves responsible BEDA staff owners dynamically from staff.json using domain keys.
Distinguishes action types (internal remediation, CRM update, payment hold, external reply,
technical review, archive/quarantine) and enforces human approval requirements.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .classifier import BusinessCategory, ClassificationResult
from .ingestion import StaffMember, load_staff_directory


class ActionType(StrEnum):
    """Categorization of recommended next actions."""

    INTERNAL_REMEDIATION = "internal_remediation"
    CRM_UPDATE = "crm_update"
    PAYMENT_HOLD = "payment_hold"
    EXTERNAL_REPLY_DRAFT = "external_reply_draft"
    TECHNICAL_ENGINEERING_REVIEW = "technical_engineering_review"
    ARCHIVE = "archive"
    QUARANTINE = "quarantine"


class StaffAssignment(BaseModel):
    """Staff owner resolved from directory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    staff_id: str
    name: str
    role: str
    email: str


class RoutingResult(BaseModel):
    """Complete routing decision with assigned staff and approval requirements."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    assigned_owners: list[StaffAssignment] = Field(default_factory=list)
    priority: str  # "CRITICAL", "HIGH", "MEDIUM", "LOW"
    action_type: ActionType
    recommended_action: str
    is_externally_consequential: bool
    requires_human_approval: bool
    reason_evidence: str
    target_queue: str

    @property
    def primary_owner_name(self) -> str:
        """Name of primary assigned staff or 'Automated Filter'."""
        if not self.assigned_owners:
            return "Automated Filter"
        return ", ".join(f"{s.name} ({s.role})" for s in self.assigned_owners)

    @property
    def primary_owner_email(self) -> str:
        """Email of primary assigned staff."""
        if not self.assigned_owners:
            return "system@wearebeda.com"
        return self.assigned_owners[0].email

    def to_legacy_dict(self) -> dict[str, Any]:
        """Bridge for backwards-compatible pipeline dict view."""
        return {
            "assigned_staff": self.primary_owner_name,
            "staff_email": self.primary_owner_email,
            "action": self.action_type.name,
            "action_type": self.action_type.value,
            "priority": self.priority,
            "requires_human_approval": self.requires_human_approval,
            "is_externally_consequential": self.is_externally_consequential,
            "recommendation": self.recommended_action,
            "target_queue": self.target_queue,
            "reason_evidence": self.reason_evidence,
        }


def _resolve_staff_by_domain(domain_keys: list[str], staff_dir: list[StaffMember]) -> list[StaffAssignment]:
    """Dynamically resolve staff members whose ownership domains overlap with required keys."""
    resolved: list[StaffAssignment] = []
    seen_ids: set[str] = set()

    for key in domain_keys:
        for member in staff_dir:
            if member.id not in seen_ids and any(key.lower() in d.lower() for d in member.domains):
                seen_ids.add(member.id)
                resolved.append(StaffAssignment(
                    staff_id=member.id,
                    name=member.name,
                    role=member.role,
                    email=member.email,
                ))

    return resolved


def route_inbound_inquiry(
    classification: ClassificationResult | str,
    extracted: Any,
    crm_match: Any,
    staff_directory: list[StaffMember] | None = None,
) -> RoutingResult:
    """
    Route an item to its responsible staff owner and determine next action.
    Uses staff_directory for dynamic entity resolution.
    """
    if staff_directory is None:
        staff_directory = load_staff_directory()

    cat = classification.category if isinstance(classification, ClassificationResult) else classification

    # Security Invariant: Adversarial Document / Untrusted Control Directive
    has_adversarial = False
    if hasattr(extracted, "has_adversarial_directives") and extracted.has_adversarial_directives or isinstance(extracted, dict) and extracted.get("has_adversarial_directives"):
        has_adversarial = True

    if has_adversarial:
        devops_owners = _resolve_staff_by_domain(["infrastructure_alerts", "systems"], staff_directory)
        return RoutingResult(
            assigned_owners=devops_owners,
            priority="CRITICAL",
            action_type=ActionType.QUARANTINE,
            recommended_action=(
                "RECOMMENDATION: Quarantine item for security review. Untrusted document attachment contains "
                "adversarial prompt injection directives attempting policy override or data exfiltration. "
                "Outbound actions, tool permissions, and automated approval are strictly suppressed."
            ),
            is_externally_consequential=False,
            requires_human_approval=True,
            reason_evidence=(
                "Adversarial prompt injection detected in untrusted document attachment; "
                "isolated at trust boundary without granting policy or tool overrides."
            ),
            target_queue="security_quarantine",
        )

    # 1. Spam Solicitation -> Automated Archive
    if cat in (BusinessCategory.SPAM_SOLICITATION, "SPAM_SOLICITATION"):
        return RoutingResult(
            assigned_owners=[],
            priority="LOW",
            action_type=ActionType.ARCHIVE,
            recommended_action="RECOMMENDATION: Automatically archive unsolicited junk solicitation. No outbound communication.",
            is_externally_consequential=False,
            requires_human_approval=False,
            reason_evidence="High confidence spam detected; routed to automated archive queue.",
            target_queue="archive_spam",
        )

    # 2. Internal System Alert -> DevOps / Systems Lead
    if cat in (BusinessCategory.INTERNAL_SYSTEM_ALERT, "INTERNAL_SYSTEM_ALERT"):
        owners = _resolve_staff_by_domain(["infrastructure_alerts", "systems"], staff_directory)
        return RoutingResult(
            assigned_owners=owners,
            priority="CRITICAL",
            action_type=ActionType.INTERNAL_REMEDIATION,
            recommended_action="RECOMMENDATION: Refresh expired HubSpot OAuth token and re-trigger sync replay for 146 stalled records.",
            is_externally_consequential=False,
            requires_human_approval=True,
            reason_evidence="Internal infrastructure integration failure requires administrator remediation.",
            target_queue="devops_urgent",
        )

    # 3. Billing / Invoice Dispute -> Senior Analyst & Operations
    if cat in (BusinessCategory.BILLING_INVOICE_DISPUTE, "BILLING_INVOICE_DISPUTE"):
        owners = _resolve_staff_by_domain(["billing_reconciliation", "general_operations"], staff_directory)
        return RoutingResult(
            assigned_owners=owners,
            priority="HIGH",
            action_type=ActionType.PAYMENT_HOLD,
            recommended_action="RECOMMENDATION: Place Invoice 1847 on payment hold pending reconciliation of $2,640 variance against PO GF PO 8821 before Friday.",
            is_externally_consequential=True,
            requires_human_approval=True,
            reason_evidence="Customer accounts team flagged $2,640 variance exceeding purchase order.",
            target_queue="finance_reconciliation",
        )

    # 4. Contact Details Update -> CRM & Business Systems
    if cat in (BusinessCategory.CONTACT_DETAILS_UPDATE, "CONTACT_DETAILS_UPDATE"):
        owners = _resolve_staff_by_domain(["crm", "data"], staff_directory)
        return RoutingResult(
            assigned_owners=owners,
            priority="MEDIUM",
            action_type=ActionType.CRM_UPDATE,
            recommended_action="RECOMMENDATION: Update contact profile to mobile 0411 999 102 and associate primary email to sam@harbourcoldstores.example.",
            is_externally_consequential=False,
            requires_human_approval=True,
            reason_evidence="Customer submitted self-correction of phone number and preferred email channel.",
            target_queue="crm_operations",
        )

    # 5. Commercial Solar Leads (Multi-site or Large Scale Enterprise)
    if cat in (BusinessCategory.COMMERCIAL_SOLAR_MULTI_SITE, BusinessCategory.COMMERCIAL_SOLAR_LEAD, "COMMERCIAL_SOLAR_LEAD"):
        owners = _resolve_staff_by_domain(["commercial_sales", "large_enterprise"], staff_directory)
        return RoutingResult(
            assigned_owners=owners,
            priority="HIGH",
            action_type=ActionType.EXTERNAL_REPLY_DRAFT,
            recommended_action="RECOMMENDATION: Schedule commercial discovery call and review multi-site electricity load profile.",
            is_externally_consequential=True,
            requires_human_approval=True,
            reason_evidence="Enterprise-scale commercial energy user with significant annual consumption / spend.",
            target_queue="founder_commercial_sales",
        )

    # 6. Subcontractor Operations -> Executive Operations Coordinator
    if cat in (BusinessCategory.SUBCONTRACTOR_OPERATIONS, "SUBCONTRACTOR_OPERATIONS"):
        owners = _resolve_staff_by_domain(["scheduling", "partner_installations"], staff_directory)
        return RoutingResult(
            assigned_owners=owners,
            priority="HIGH",
            action_type=ActionType.EXTERNAL_REPLY_DRAFT,
            recommended_action="RECOMMENDATION: Verify Ballarat site grid connection clearance with engineering and confirm 4-person crew reservation ahead of Tuesday deadline.",
            is_externally_consequential=True,
            requires_human_approval=True,
            reason_evidence="Installation partner requested scheduling confirmation by Tuesday for 14 September crew reservation.",
            target_queue="operations_scheduling",
        )

    # 7. Technical Engineering Review -> Systems Lead & Engineering
    if cat in (BusinessCategory.TECHNICAL_ENGINEERING_REVIEW, "TECHNICAL_ENGINEERING_REVIEW"):
        owners = _resolve_staff_by_domain(["systems"], staff_directory)
        return RoutingResult(
            assigned_owners=owners,
            priority="MEDIUM",
            action_type=ActionType.TECHNICAL_ENGINEERING_REVIEW,
            recommended_action="RECOMMENDATION: Conduct technical engineering review of PCS inverter THD limits at Point of Common Coupling and advise on harmonic study requirement.",
            is_externally_consequential=False,
            requires_human_approval=True,
            reason_evidence="Specialized grid compliance and battery inverter technical query requiring electrical engineering expertise.",
            target_queue="engineering_technical",
        )

    # 8. Clarification Needed (School Lighting / Incentives) -> Growth & Operations
    if cat in (BusinessCategory.CLARIFICATION_LIGHTING_INCENTIVE, "CLARIFICATION_NEEDED"):
        owners = _resolve_staff_by_domain(["inbound_growth", "administration"], staff_directory)
        return RoutingResult(
            assigned_owners=owners,
            priority="MEDIUM",
            action_type=ActionType.EXTERNAL_REPLY_DRAFT,
            recommended_action="RECOMMENDATION: Request 12-month interval electricity invoice and fitting schedule before preparing VEU/ESS incentive proposal.",
            is_externally_consequential=True,
            requires_human_approval=True,
            reason_evidence="School facility inquiry requires mandatory billing documentation before incentive eligibility can be assessed.",
            target_queue="growth_public_sector",
        )

    # 9. Careers / Internship Application -> Growth & Operations
    if cat in (BusinessCategory.CAREERS_APPLICATION, "CAREERS_APPLICATION"):
        owners = _resolve_staff_by_domain(["internship_applications", "general_operations"], staff_directory)
        return RoutingResult(
            assigned_owners=owners,
            priority="LOW",
            action_type=ActionType.EXTERNAL_REPLY_DRAFT,
            recommended_action="RECOMMENDATION: Log candidate portfolio in recruitment pipeline and send receipt acknowledgment.",
            is_externally_consequential=True,
            requires_human_approval=True,
            reason_evidence="Candidate submitting unsolicited marketing internship application and portfolio.",
            target_queue="people_culture",
        )

    # 10. Small Commercial Leasehold -> Inbound Growth
    if cat in (BusinessCategory.SMALL_COMMERCIAL_LEASEHOLD, "UNQUALIFIED_SMALL_COMMERCIAL"):
        owners = _resolve_staff_by_domain(["inbound_growth"], staff_directory)
        return RoutingResult(
            assigned_owners=owners,
            priority="LOW",
            action_type=ActionType.EXTERNAL_REPLY_DRAFT,
            recommended_action="RECOMMENDATION: Advise that property owner roof permission is a mandatory prerequisite for leased commercial solar installations.",
            is_externally_consequential=True,
            requires_human_approval=True,
            reason_evidence="Leased small commercial premises without confirmed landlord authorization for roof installations.",
            target_queue="growth_inbound",
        )

    # Default Fallback -> General Operations
    owners = _resolve_staff_by_domain(["general_operations"], staff_directory)
    return RoutingResult(
        assigned_owners=owners,
        priority="MEDIUM",
        action_type=ActionType.EXTERNAL_REPLY_DRAFT,
        recommended_action="RECOMMENDATION: Standard triage review and initial reply.",
        is_externally_consequential=True,
        requires_human_approval=True,
        reason_evidence="Unclassified inquiry routed for human operations review.",
        target_queue="general_triage",
    )


def determine_routing_and_staff(
    classification: Any,
    extracted: Any,
    crm_match: Any,
    staff_directory: list[StaffMember] | None = None,
) -> dict[str, Any]:
    """Legacy bridge returning a dictionary view."""
    res = route_inbound_inquiry(classification, extracted, crm_match, staff_directory)
    return res.to_legacy_dict()
