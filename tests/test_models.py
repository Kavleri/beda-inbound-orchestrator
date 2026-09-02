"""
Tests for domain model validation and trust boundary enforcement.

Covers: unknown fields, invalid enums, invalid confidence, overlong strings,
malformed email, bad channel, and injection detection in company name.
"""

import pytest
from pydantic import ValidationError

from beda_orchestrator.enums import InquiryIntent, UrgencyLevel
from beda_orchestrator.models import (
    ApprovalCommand,
    InboundEnvelope,
    InboundTriageResult,
    RoutingDecision,
)
from helpers import make_envelope, make_triage


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
