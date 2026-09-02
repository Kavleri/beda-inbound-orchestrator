"""
BEDA Inbound Business Inquiry Router & Orchestrator
Core Triage, Pydantic v2 Schema Enforcement, and Deterministic Policy Gate.

Author: Muhammad Hisyam Alfaris (https://aboutsyem.web.id)
"""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)


class InquiryIntent(StrEnum):
    ENTERPRISE_SALES = "enterprise_sales"
    TECHNICAL_SUPPORT = "technical_support"
    PARTNERSHIP = "partnership"
    CAREERS = "careers"
    SPAM_OR_MALICIOUS = "spam_or_malicious"
    GENERAL_INQUIRY = "general_inquiry"


class UrgencyLevel(StrEnum):
    CRITICAL = "critical"  # Requires < 2h SLA
    HIGH = "high"          # Requires < 8h SLA
    MEDIUM = "medium"      # Standard business SLA
    LOW = "low"            # Informational / Backlog


class LeadTier(StrEnum):
    TIER_1_ENTERPRISE = "tier_1_enterprise"  # Budget > $50k
    TIER_2_GROWTH = "tier_2_growth"          # Budget $10k - $50k
    TIER_3_EXPLORATORY = "tier_3_exploratory"# Budget < $10k / Unspecified
    UNQUALIFIED = "unqualified"


class RoutingAction(StrEnum):
    ESCALATE_TO_HUMAN_SALES = "escalate_to_human_sales"
    QUEUE_FOR_HITL_DRAFT_REVIEW = "queue_for_hitl_draft_review"
    TRIGGER_DETERMINISTIC_CLARIFICATION = "trigger_deterministic_clarification"
    AUTO_ARCHIVE_SPAM = "auto_archive_spam"


# ============================================================================
# Pydantic v2 Strict Triage Schema
# ============================================================================

class InboundTriageResult(BaseModel):
    """
    Strict validated schema for structured LLM extraction and intent classification.
    Configured with extra='forbid' to prevent unvalidated parameter injection.
    """
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        validate_default=True,
    )

    triage_id: UUID = Field(default_factory=uuid4, description="Unique triage execution identifier")
    intent: InquiryIntent = Field(..., description="Primary categorized intent of the inbound inquiry")
    urgency: UrgencyLevel = Field(..., description="Operational urgency assessed from message content")
    lead_tier: LeadTier = Field(..., description="Commercial tier evaluated from budget/scope")
    
    extracted_company: str | None = Field(
        default=None,
        min_length=2,
        max_length=120,
        description="Identified company or organization name",
    )
    extracted_budget_usd: Annotated[int | None, Field(ge=0, description="Normalized budget in USD")] = None
    technical_domains: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Extracted technical domains (e.g., 'LLMOps', 'Vector DB')",
    )
    
    missing_critical_fields: list[str] = Field(
        default_factory=list,
        description="List of critical parameters missing from the inquiry needed for scoping",
    )
    
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Aggregate extraction certainty score calculated by the model",
    )
    
    draft_response: str = Field(
        ...,
        min_length=10,
        max_length=4000,
        description="Context-aware response draft prepared for human review",
    )

    @field_validator("extracted_company")
    @classmethod
    def sanitize_company_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if any(char in cleaned for char in ["<", ">", ";", "{", "}"]):
            raise ValueError("Potential injection characters detected in company name.")
        return cleaned


# ============================================================================
# Ingress Payload & Routing Output Models
# ============================================================================

class InboundPayload(BaseModel):
    """Raw ingress message payload received at the edge gateway."""
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    sender_email: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")]
    sender_name: str = Field(..., min_length=1, max_length=100)
    raw_subject: str = Field(..., max_length=255)
    raw_body: str = Field(..., min_length=5, max_length=10000)
    source_channel: str = Field(..., pattern="^(email|webform|slack_api)$")
    idempotency_key: str = Field(..., min_length=64, max_length=64)
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RoutingDecision(BaseModel):
    """Immutable deterministic routing instruction for downstream worker execution."""
    model_config = ConfigDict(strict=True, frozen=True)

    decision_id: UUID = Field(default_factory=uuid4)
    triage_id: UUID
    idempotency_key: str
    action: RoutingAction
    target_queue: str
    requires_human_approval: bool
    requires_immediate_slack_alert: bool
    audit_reason: str
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================================
# Deterministic Evaluation Gate Subsystem
# ============================================================================

def evaluate_triage_decision(
    triage: InboundTriageResult,
    payload: InboundPayload,
) -> RoutingDecision:
    """
    Deterministic Policy Evaluation Gate.
    
    Applies strict business logic to the LLM's structured output. The generative model 
    never decides the routing action; it only supplies data to this deterministic gate.
    """
    # Rule 1: Immediate disposal of spam and malicious inputs
    if triage.intent == InquiryIntent.SPAM_OR_MALICIOUS:
        return RoutingDecision(
            triage_id=triage.triage_id,
            idempotency_key=payload.idempotency_key,
            action=RoutingAction.AUTO_ARCHIVE_SPAM,
            target_queue="queue_archive_deadletter",
            requires_human_approval=False,
            requires_immediate_slack_alert=False,
            audit_reason="Deterministic Rule: Inbound classified as spam/malicious payload.",
        )

    # Rule 2: Low-confidence extraction requires mandatory human review
    if triage.confidence_score < 0.85:
        return RoutingDecision(
            triage_id=triage.triage_id,
            idempotency_key=payload.idempotency_key,
            action=RoutingAction.QUEUE_FOR_HITL_DRAFT_REVIEW,
            target_queue="queue_hitl_low_confidence",
            requires_human_approval=True,
            requires_immediate_slack_alert=False,
            audit_reason=f"Safety Gate: Confidence score {triage.confidence_score:.2f} below threshold (0.85).",
        )

    # Rule 3: High-Value Enterprise Lead Routing
    if (
        triage.intent == InquiryIntent.ENTERPRISE_SALES
        and triage.lead_tier == LeadTier.TIER_1_ENTERPRISE
    ):
        return RoutingDecision(
            triage_id=triage.triage_id,
            idempotency_key=payload.idempotency_key,
            action=RoutingAction.ESCALATE_TO_HUMAN_SALES,
            target_queue="queue_sales_tier_1",
            requires_human_approval=True,
            requires_immediate_slack_alert=True,
            audit_reason="Priority Gate: Qualified Tier-1 Enterprise Opportunity detected.",
        )

    # Rule 4: Incomplete parameters trigger a deterministic clarification request
    if len(triage.missing_critical_fields) >= 2:
        return RoutingDecision(
            triage_id=triage.triage_id,
            idempotency_key=payload.idempotency_key,
            action=RoutingAction.TRIGGER_DETERMINISTIC_CLARIFICATION,
            target_queue="queue_hitl_clarification",
            requires_human_approval=True,  # Mandatory human sign-off before dispatching clarification
            requires_immediate_slack_alert=False,
            audit_reason=(
                f"Clarification Gate: Missing critical parameters: "
                f"{', '.join(triage.missing_critical_fields)}"
            ),
        )

    # Default Rule: Standard Lead HITL Draft Review
    return RoutingDecision(
        triage_id=triage.triage_id,
        idempotency_key=payload.idempotency_key,
        action=RoutingAction.QUEUE_FOR_HITL_DRAFT_REVIEW,
        target_queue="queue_hitl_standard_drafts",
        requires_human_approval=True,
        requires_immediate_slack_alert=(triage.urgency == UrgencyLevel.CRITICAL),
        audit_reason="Standard Flow: Routing to HITL approval queue for draft sign-off.",
    )


if __name__ == "__main__":
    import json

    sample_payload = InboundPayload(
        sender_email="alex.vance@blackmesa-research.com",
        sender_name="Alex Vance",
        raw_subject="Custom LLM Orchestration Infrastructure Project",
        raw_body="We need an enterprise-grade agent orchestration framework. Budget is approx $75,000.",
        source_channel="webform",
        idempotency_key="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )

    mock_triage_output = InboundTriageResult(
        intent=InquiryIntent.ENTERPRISE_SALES,
        urgency=UrgencyLevel.HIGH,
        lead_tier=LeadTier.TIER_1_ENTERPRISE,
        extracted_company="Black Mesa Research",
        extracted_budget_usd=75000,
        technical_domains=["LLMOps", "Orchestration", "Distributed Systems"],
        missing_critical_fields=[],
        confidence_score=0.96,
        draft_response=(
            "Hi Alex,\n\nThank you for reaching out to BEDA. We specialize in resilient "
            "agentic infrastructure and would be thrilled to discuss your architectural requirements.\n\n"
            "Best regards,\nBEDA Solutions Team"
        ),
    )

    decision = evaluate_triage_decision(mock_triage_output, sample_payload)
    print("=" * 80)
    print("DETERMINISTIC EVALUATION GATE RESULT")
    print("=" * 80)
    print(json.dumps(decision.model_dump(mode="json"), indent=2))
    assert decision.action == RoutingAction.ESCALATE_TO_HUMAN_SALES
    assert decision.requires_human_approval is True
    assert decision.requires_immediate_slack_alert is True
    print("\n[SUCCESS] Assertions verified successfully.")
