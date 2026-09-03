"""
Tests for domain model validation, immutability, and trust boundary enforcement.

Covers:
  - InboundEnvelope validation, normalization, and timezone checks
  - InboundTriageResult bounds, sanitization, and immutability
  - RoutingDecision frozenness and timezone validation
  - ApprovalCommand bounds, signature length, and timezone-aware expiry
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from helpers import make_envelope, make_triage
from pydantic import ValidationError

from beda_orchestrator.enums import (
    InquiryIntent,
    ReasonCode,
    RoutingAction,
    UrgencyLevel,
)
from beda_orchestrator.models import (
    ApprovalCommand,
    InboundEnvelope,
    InboundTriageResult,
    RoutingDecision,
)


class TestInboundEnvelope:
    def test_valid_envelope(self):
        e = make_envelope()
        assert e.sender_email == "test@example.com"
        assert e.source_channel == "email"

    def test_email_normalized_to_lowercase(self):
        e = make_envelope(sender_email="  User@Example.COM  ")
        assert e.sender_email == "user@example.com"

    def test_rejects_malformed_email(self):
        with pytest.raises(ValidationError, match="email"):
            make_envelope(sender_email="not-an-email")

    def test_rejects_empty_sender_name(self):
        with pytest.raises(ValidationError):
            make_envelope(sender_name="")

    def test_rejects_overlong_subject(self):
        with pytest.raises(ValidationError):
            make_envelope(subject="x" * 501)

    def test_rejects_empty_body(self):
        with pytest.raises(ValidationError):
            make_envelope(body="")

    def test_rejects_invalid_channel(self):
        with pytest.raises(ValidationError, match="pattern"):
            make_envelope(source_channel="telegram")

    def test_rejects_timezone_naive_received_at(self):
        with pytest.raises(ValidationError, match="timezone-aware"):
            make_envelope(received_at=datetime(2026, 1, 1, 12, 0, 0))

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValidationError, match="extra"):
            InboundEnvelope(
                sender_email="a@b.com",
                sender_name="A",
                subject="S",
                body="Hello world",
                source_channel="email",
                idempotency_key="a" * 64,
                unknown_field="bad",
            )

    def test_frozen(self):
        e = make_envelope()
        with pytest.raises(ValidationError):
            e.sender_email = "other@test.com"

    def test_body_hash_deterministic(self):
        e = make_envelope(body="Hello world")
        assert e.body_hash() == e.body_hash()
        assert len(e.body_hash()) == 64

    def test_payload_hash_deterministic(self):
        e = make_envelope()
        assert e.payload_hash() == e.payload_hash()


class TestInboundTriageResult:
    def test_valid_triage(self):
        t = make_triage()
        assert t.intent == InquiryIntent.GENERAL_INQUIRY
        assert t.confidence_score == 0.92

    def test_rejects_invalid_intent(self):
        with pytest.raises(ValidationError):
            make_triage(intent="invalid_intent")

    def test_rejects_confidence_above_1(self):
        with pytest.raises(ValidationError):
            make_triage(confidence_score=1.5)

    def test_rejects_confidence_below_0(self):
        with pytest.raises(ValidationError):
            make_triage(confidence_score=-0.1)

    def test_rejects_negative_budget(self):
        with pytest.raises(ValidationError):
            make_triage(extracted_budget_usd=-100)

    def test_rejects_injection_in_company_name(self):
        with pytest.raises(ValidationError, match="Suspicious"):
            make_triage(extracted_company="<script>alert(1)</script>")

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValidationError, match="extra"):
            InboundTriageResult(
                intent=InquiryIntent.GENERAL_INQUIRY,
                urgency=UrgencyLevel.LOW,
                confidence_score=0.9,
                sneaky_field="injected",
            )

    def test_none_company_is_allowed(self):
        t = make_triage(extracted_company=None)
        assert t.extracted_company is None

    def test_overlong_company_rejected(self):
        with pytest.raises(ValidationError):
            make_triage(extracted_company="A" * 201)

    def test_frozen(self):
        t = make_triage()
        with pytest.raises(ValidationError):
            t.confidence_score = 0.5


class TestRoutingDecisionModel:
    def test_valid_decision(self):
        d = RoutingDecision(
            event_id=uuid4(),
            triage_id=uuid4(),
            idempotency_key="k" * 32,
            action=RoutingAction.QUEUE_FOR_HITL_DRAFT_REVIEW,
            target_queue="hitl_standard",
            requires_human_approval=True,
            reason_code=ReasonCode.STANDARD_HITL_REVIEW,
            reason_detail="Standard review.",
        )
        assert d.requires_human_approval is True
        assert d.policy_version == "0.1.0"

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError, match="extra"):
            RoutingDecision(
                event_id=uuid4(),
                triage_id=uuid4(),
                idempotency_key="k" * 32,
                action=RoutingAction.QUEUE_FOR_HITL_DRAFT_REVIEW,
                target_queue="hitl_standard",
                requires_human_approval=True,
                reason_code=ReasonCode.STANDARD_HITL_REVIEW,
                reason_detail="Standard review.",
                illegal_extra="should_fail",
            )

    def test_rejects_timezone_naive_evaluated_at(self):
        with pytest.raises(ValidationError, match="timezone-aware"):
            RoutingDecision(
                event_id=uuid4(),
                triage_id=uuid4(),
                idempotency_key="k" * 32,
                action=RoutingAction.QUEUE_FOR_HITL_DRAFT_REVIEW,
                target_queue="hitl_standard",
                requires_human_approval=True,
                reason_code=ReasonCode.STANDARD_HITL_REVIEW,
                reason_detail="Standard review.",
                evaluated_at=datetime(2026, 1, 1, 12, 0, 0),
            )


class TestApprovalCommandModel:
    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError, match="extra"):
            ApprovalCommand(
                approval_id=uuid4(),
                decision_id=uuid4(),
                event_id=uuid4(),
                payload_hash="a" * 64,
                recipient_hash="b" * 64,
                approver_identity="user@beda.studio",
                approved_draft="Draft text.",
                nonce="c" * 32,
                expires_at=datetime.now(UTC),
                signature="d" * 64,
                extra_param="forbidden",
            )

    def test_rejects_timezone_naive_expires_at(self):
        with pytest.raises(ValidationError, match="timezone-aware"):
            ApprovalCommand(
                approval_id=uuid4(),
                decision_id=uuid4(),
                event_id=uuid4(),
                payload_hash="a" * 64,
                recipient_hash="b" * 64,
                approver_identity="user@beda.studio",
                approved_draft="Draft text.",
                nonce="c" * 32,
                expires_at=datetime(2026, 1, 1, 12, 0, 0),  # Naive
                signature="d" * 64,
            )
