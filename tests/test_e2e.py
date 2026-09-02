"""
End-to-end vertical slice test.

Runs the complete local flow without external services:
  envelope → mock triage → policy → approval → dispatch → audit

Covers: standard support, enterprise sales, malformed LLM output,
duplicate event, and replayed approval token.
"""

import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from beda_orchestrator.approval import (
    ApprovalVerificationError,
    approve_and_send,
    reset_replay_registry,
    verify_approval,
)
from beda_orchestrator.audit import AuditEvent, AuditSink
from beda_orchestrator.dispatch import (
    check_duplicate,
    mock_dispatch,
    record_decision,
    reset_idempotency_registry,
)
from beda_orchestrator.enums import (
    AuditEventType,
    InquiryIntent,
    ReasonCode,
    RoutingAction,
    UrgencyLevel,
)
from beda_orchestrator.models import InboundEnvelope, InboundTriageResult, RoutingDecision
from beda_orchestrator.policy import evaluate_triage_decision
from helpers import make_envelope, make_triage


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    monkeypatch.setenv("BEDA_APPROVAL_SECRET", "e2e_test_secret_" + "z" * 32)
    reset_replay_registry()
    reset_idempotency_registry()


@pytest.fixture
def audit_sink(tmp_path) -> AuditSink:
    return AuditSink(tmp_path / "e2e_audit.jsonl")


class TestSupportFlow:
    """Standard support inquiry: triage → policy → HITL review."""

    def test_support_inquiry_full_flow(self, audit_sink):
        envelope = make_envelope(
            sender_email="user@company.com",
            subject="API integration help",
            body="We need help integrating your API with our platform.",
            idempotency_key="s" * 64,
        )
        triage = make_triage(
            intent=InquiryIntent.TECHNICAL_SUPPORT,
            urgency=UrgencyLevel.MEDIUM,
            extracted_budget_usd=3000,
            confidence_score=0.93,
        )

        # Log envelope receipt.
        audit_sink.log(AuditEvent(
            event_type=AuditEventType.ENVELOPE_RECEIVED,
            correlation_id=str(envelope.event_id),
            payload_hash=envelope.body_hash(),
        ))

        # Policy decision.
        decision = evaluate_triage_decision(triage, envelope)
        assert decision.action == RoutingAction.QUEUE_FOR_HITL_DRAFT_REVIEW
        assert decision.requires_human_approval

        # Record for idempotency.
        record_decision(envelope, decision)

        # Log decision.
        audit_sink.log(AuditEvent(
            event_type=AuditEventType.POLICY_DECISION,
            correlation_id=str(envelope.event_id),
            reason_code=decision.reason_code,
            detail=decision.reason_detail,
            policy_version=decision.policy_version,
        ))

        # Verify audit chain.
        valid, count, error = audit_sink.verify_chain()
        assert valid, error
        assert count == 2


class TestEnterpriseSalesFlow:
    """Enterprise sales: triage → policy → approval → dispatch."""

    def test_enterprise_sales_with_approval_and_dispatch(self, audit_sink):
        envelope = make_envelope(
            sender_email="cto@bigcorp.com",
            subject="Enterprise LLM infrastructure RFP",
            body="We need a custom LLM orchestration platform. Budget: $120,000.",
            idempotency_key="e" * 64,
        )
        triage = make_triage(
            intent=InquiryIntent.ENTERPRISE_SALES,
            urgency=UrgencyLevel.HIGH,
            extracted_company="BigCorp Inc",
            extracted_budget_usd=120_000,
            confidence_score=0.97,
            draft_response="Thank you for your interest in our enterprise solutions.",
        )

        decision = evaluate_triage_decision(triage, envelope)
        assert decision.action == RoutingAction.ESCALATE_TO_HUMAN_SALES
        assert decision.requires_human_approval
        record_decision(envelope, decision)

        # Human approves.
        draft = "Dear CTO, thank you for considering BEDA for your infrastructure needs."
        payload_hash = hashlib.sha256(draft.encode()).hexdigest()
        command = approve_and_send(
            decision=decision,
            approved_draft=draft,
            recipient_email="cto@bigcorp.com",
            approver_identity="sales_lead@beda.studio",
            payload_hash=payload_hash,
        )

        result = mock_dispatch(command, audit_sink=audit_sink)
        assert result.success

        valid, count, error = audit_sink.verify_chain()
        assert valid, error
        assert count >= 2  # dispatch_attempted + dispatch_succeeded


class TestMalformedLLMOutput:
    """Malformed LLM output should be caught by Pydantic validation."""

    def test_invalid_confidence_rejected(self):
        with pytest.raises(Exception):
            make_triage(confidence_score=2.0)

    def test_extra_fields_rejected(self):
        with pytest.raises(Exception):
            InboundTriageResult(
                intent=InquiryIntent.GENERAL_INQUIRY,
                urgency=UrgencyLevel.LOW,
                confidence_score=0.9,
                invented_field="hallucinated",
            )


class TestDuplicateEvent:
    """Duplicate events return the prior decision."""

    def test_duplicate_returns_prior_decision(self):
        envelope = make_envelope(idempotency_key="d" * 64)
        triage = make_triage(confidence_score=0.92)

        # First processing.
        decision = evaluate_triage_decision(triage, envelope)
        record_decision(envelope, decision)

        # Second processing of same event.
        prior = check_duplicate(envelope)
        assert prior is not None
        assert prior.decision_id == decision.decision_id
        assert prior.action == decision.action


class TestReplayedApproval:
    """Replayed approval tokens must fail closed."""

    def test_replayed_token_rejected_at_dispatch(self, audit_sink):
        envelope = make_envelope(idempotency_key="r" * 64)
        decision = RoutingDecision(
            event_id=envelope.event_id,
            triage_id=uuid4(),
            idempotency_key=envelope.idempotency_key,
            action=RoutingAction.ESCALATE_TO_HUMAN_SALES,
            target_queue="sales_tier_1",
            requires_human_approval=True,
            reason_code=ReasonCode.ENTERPRISE_SALES_QUALIFIED,
            reason_detail="Test.",
            policy_version="0.1.0",
        )

        draft = "Approved response text."
        payload_hash = hashlib.sha256(draft.encode()).hexdigest()
        command = approve_and_send(
            decision=decision,
            approved_draft=draft,
            recipient_email="client@example.com",
            approver_identity="admin@beda.studio",
            payload_hash=payload_hash,
        )

        # First dispatch succeeds.
        result1 = mock_dispatch(command, audit_sink=audit_sink)
        assert result1.success

        # Replay: same token again.
        result2 = mock_dispatch(command, audit_sink=audit_sink)
        assert not result2.success
        assert "replay" in result2.detail.lower() or "nonce" in result2.detail.lower()
