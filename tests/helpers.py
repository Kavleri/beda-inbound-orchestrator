"""Shared test factories."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from beda_orchestrator.enums import InquiryIntent, UrgencyLevel
from beda_orchestrator.models import InboundEnvelope, InboundTriageResult


def make_envelope(**overrides) -> InboundEnvelope:
    """Build a valid InboundEnvelope with sensible defaults."""
    defaults = dict(
        event_id=uuid4(),
        sender_email="test@example.com",
        sender_name="Test User",
        subject="Test inquiry",
        body="I would like to discuss a potential project with your team.",
        source_channel="email",
        idempotency_key="a" * 64,
        received_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return InboundEnvelope(**defaults)


def make_triage(**overrides) -> InboundTriageResult:
    """Build a valid InboundTriageResult with sensible defaults."""
    defaults = dict(
        triage_id=uuid4(),
        intent=InquiryIntent.GENERAL_INQUIRY,
        urgency=UrgencyLevel.MEDIUM,
        extracted_company="Acme Corp",
        extracted_budget_usd=5000,
        technical_domains=["web"],
        missing_critical_fields=[],
        confidence_score=0.92,
        evidence="Standard inquiry about web development services.",
        draft_response="Thank you for reaching out. We would be happy to discuss.",
    )
    defaults.update(overrides)
    return InboundTriageResult(**defaults)
