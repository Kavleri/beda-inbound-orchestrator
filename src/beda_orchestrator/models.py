"""
Domain models with explicit trust boundaries.

InboundEnvelope  — transport metadata, validated at ingress.
InboundTriageResult — untrusted LLM extraction, never authoritative.
RoutingDecision  — output of deterministic policy, frozen.
ApprovalCommand  — bounded command created by authenticated human.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import InquiryIntent, ReasonCode, RoutingAction, UrgencyLevel

POLICY_VERSION = "0.1.0"
CONFIDENCE_THRESHOLD = 0.85
ENTERPRISE_BUDGET_FLOOR_USD = 50_000
GROWTH_BUDGET_FLOOR_USD = 10_000

# Patterns that suggest prompt injection in free-text fields.
_INJECTION_PATTERNS = re.compile(
    r"(ignore\s+(previous|all|prior)\s+instructions"
    r"|system\s*:\s*you\s+are"
    r"|<\s*script"
    r"|javascript\s*:"
    r"|\}\s*\{)",
    re.IGNORECASE,
)


class InboundEnvelope(BaseModel):
    """
    Transport-level metadata for an inbound inquiry.

    Validated at ingress. Fields are normalized (stripped, lowercased where
    appropriate) but not semantically interpreted. This is the trust boundary
    between the outside world and the processing pipeline.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: UUID = Field(default_factory=uuid4)
    sender_email: str = Field(..., max_length=320)
    sender_name: str = Field(..., min_length=1, max_length=200)
    subject: str = Field(..., max_length=500)
    body: str = Field(..., min_length=1, max_length=50_000)
    source_channel: str = Field(..., pattern=r"^(email|webform|slack_api|whatsapp)$")
    idempotency_key: str = Field(..., min_length=16, max_length=128)
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("sender_email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", v):
            raise ValueError(f"Invalid email format: {v!r}")
        return v

    @field_validator("sender_name", "subject")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()

    @field_validator("received_at")
    @classmethod
    def validate_received_at_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("received_at must be timezone-aware (e.g., UTC).")
        return v

    def body_hash(self) -> str:
        """SHA-256 of the raw body for audit correlation without storing PII."""
        return hashlib.sha256(self.body.encode()).hexdigest()

    def payload_hash(self) -> str:
        """SHA-256 over sender + subject + body, used for approval binding."""
        content = f"{self.sender_email}::{self.subject}::{self.body}"
        return hashlib.sha256(content.encode()).hexdigest()


class InboundTriageResult(BaseModel):
    """
    Semantic extraction from an LLM or mock extractor.

    This is untrusted output. The policy engine will re-derive lead tier
    from extracted_budget_usd and will not trust intent or urgency blindly.
    This model must NOT contain an executable action.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    triage_id: UUID = Field(default_factory=uuid4)
    intent: InquiryIntent
    urgency: UrgencyLevel
    extracted_company: str | None = Field(default=None, max_length=200)
    extracted_budget_usd: Annotated[int | None, Field(ge=0, le=999_999_999)] = None
    technical_domains: list[str] = Field(default_factory=list, max_length=20)
    missing_critical_fields: list[str] = Field(default_factory=list, max_length=20)
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    evidence: str = Field(
        default="",
        max_length=2000,
        description="Free-text reasoning from the extractor, for human review only.",
    )
    draft_response: str = Field(
        default="",
        max_length=8000,
        description="Suggested response draft. Never sent without human approval.",
    )

    @field_validator("extracted_company")
    @classmethod
    def reject_injection_in_company(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if any(c in v for c in "<>{}"):
            raise ValueError("Suspicious characters in company name")
        return v


class RoutingDecision(BaseModel):
    """
    Output of the deterministic policy engine. Frozen after creation.

    The policy engine produces this; no LLM or external call influences
    the action field. Every decision carries a stable reason_code for
    metrics and a policy_version for reproducibility.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_id: UUID = Field(default_factory=uuid4)
    event_id: UUID
    triage_id: UUID
    idempotency_key: str
    action: RoutingAction
    target_queue: str
    requires_human_approval: bool
    reason_code: ReasonCode
    reason_detail: str
    policy_version: str = POLICY_VERSION
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("evaluated_at")
    @classmethod
    def validate_evaluated_at_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("evaluated_at must be timezone-aware (e.g., UTC).")
        return v



class ApprovalCommand(BaseModel):
    """
    A bounded command created only by an authenticated human approval.

    The dispatcher accepts only a verified ApprovalCommand. It binds to the
    exact payload hash and recipient hash so that modifying the draft or
    recipient after approval invalidates the command.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: UUID = Field(default_factory=uuid4)
    decision_id: UUID
    event_id: UUID
    payload_hash: str = Field(..., min_length=64, max_length=64)
    recipient_hash: str = Field(..., min_length=64, max_length=64)
    approver_identity: str = Field(..., min_length=1, max_length=200)
    approved_draft: str = Field(..., min_length=1, max_length=8000)
    nonce: str = Field(..., min_length=16, max_length=64)
    expires_at: datetime
    signature: str = Field(..., min_length=64, max_length=128)
    issued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("expires_at", "issued_at")
    @classmethod
    def validate_tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("Datetime must be timezone-aware (e.g., UTC).")
        return v

    def is_expired(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        if now.tzinfo is None:
            raise ValueError("Comparison datetime 'now' must be timezone-aware.")
        return now >= self.expires_at
