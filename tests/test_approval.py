"""
Tests for HMAC approval token issuance, verification, eligibility, and failure modes.

Covers:
  - Valid approval issuance & internal payload hash computation
  - Invariant: payload_hash == SHA256(approved_draft)
  - Expected payload hash mismatch rejection
  - Approval eligibility (spam, quarantine, requires_approval=False rejected)
  - Draft bounds (empty, whitespace, >8000 chars rejected)
  - TTL bounds (<=0 or >7 days rejected)
  - Recipient email format validation
  - Payload mutation, recipient mutation, expiry, replay, wrong secret, missing secret
"""

import hashlib
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from beda_orchestrator.approval import (
    ApprovalVerificationError,
    approve_and_send,
    reset_replay_registry,
    verify_approval,
)
from beda_orchestrator.enums import ReasonCode, RoutingAction
from beda_orchestrator.models import ApprovalCommand, RoutingDecision


@pytest.fixture(autouse=True)
def _set_secret_and_reset(monkeypatch):
    """Set a test secret and clear replay registry before each test."""
    monkeypatch.setenv("BEDA_APPROVAL_SECRET", "test_secret_key_" + "x" * 32)
    reset_replay_registry()


def _make_decision(**overrides) -> RoutingDecision:
    defaults = dict(
        event_id=uuid4(),
        triage_id=uuid4(),
        idempotency_key="a" * 64,
        action=RoutingAction.ESCALATE_TO_HUMAN_SALES,
        target_queue="sales_tier_1",
        requires_human_approval=True,
        reason_code=ReasonCode.ENTERPRISE_SALES_QUALIFIED,
        reason_detail="Test decision.",
        policy_version="0.1.0",
    )
    defaults.update(overrides)
    return RoutingDecision(**defaults)


def _issue_command(decision: RoutingDecision | None = None) -> ApprovalCommand:
    decision = decision or _make_decision()
    draft = "Thank you for your interest. We will schedule a call."
    return approve_and_send(
        decision=decision,
        approved_draft=draft,
        recipient_email="client@example.com",
        approver_identity="admin@beda.studio",
    )


class TestApprovalIssuance:
    def test_issued_command_verifies(self):
        cmd = _issue_command()
        verify_approval(cmd)

    def test_command_has_required_fields(self):
        cmd = _issue_command()
        assert cmd.approval_id
        assert cmd.decision_id
        assert cmd.payload_hash
        assert cmd.recipient_hash
        assert cmd.nonce
        assert cmd.expires_at > datetime.now(timezone.utc)
        assert cmd.signature

    def test_payload_hash_computed_internally_invariant(self):
        """Invariant: payload_hash == SHA256(approved_draft.encode('utf-8'))."""
        draft = "Exact approved response content for verification."
        expected_hash = hashlib.sha256(draft.encode("utf-8")).hexdigest()
        cmd = approve_and_send(
            decision=_make_decision(),
            approved_draft=draft,
            recipient_email="client@example.com",
            approver_identity="approver@beda.studio",
        )
        assert cmd.payload_hash == expected_hash

    def test_expected_payload_hash_matching_succeeds(self):
        draft = "Verified proposal text."
        valid_hash = hashlib.sha256(draft.encode("utf-8")).hexdigest()
        cmd = approve_and_send(
            decision=_make_decision(),
            approved_draft=draft,
            recipient_email="client@example.com",
            approver_identity="approver@beda.studio",
            expected_payload_hash=valid_hash,
        )
        assert cmd.payload_hash == valid_hash

    def test_expected_payload_hash_mismatch_fails(self):
        draft = "Verified proposal text."
        tampered_hash = "f" * 64
        with pytest.raises(ValueError, match="mismatch"):
            approve_and_send(
                decision=_make_decision(),
                approved_draft=draft,
                recipient_email="client@example.com",
                approver_identity="approver@beda.studio",
                expected_payload_hash=tampered_hash,
            )


class TestApprovalEligibility:
    def test_spam_decision_cannot_be_approved(self):
        spam_decision = _make_decision(
            action=RoutingAction.AUTO_ARCHIVE_SPAM,
            requires_human_approval=False,
            reason_code=ReasonCode.SPAM_CLASSIFIED,
        )
        with pytest.raises(ValueError, match="does not require human approval"):
            approve_and_send(
                decision=spam_decision,
                approved_draft="Draft text.",
                recipient_email="spam@example.com",
                approver_identity="admin@beda.studio",
            )

    def test_quarantine_decision_cannot_be_approved(self):
        quarantine_decision = _make_decision(
            action=RoutingAction.QUARANTINE,
            requires_human_approval=False,
            reason_code=ReasonCode.PROMPT_INJECTION_DETECTED,
        )
        with pytest.raises(ValueError, match="does not require human approval"):
            approve_and_send(
                decision=quarantine_decision,
                approved_draft="Draft text.",
                recipient_email="user@example.com",
                approver_identity="admin@beda.studio",
            )

    def test_ineligible_action_with_approval_flag_rejected(self):
        """Even if requires_human_approval were True, quarantine/spam action is rejected."""
        bad_decision = _make_decision(
            action=RoutingAction.QUARANTINE,
            requires_human_approval=True,
            reason_code=ReasonCode.CONTRADICTORY_FIELDS,
        )
        with pytest.raises(ValueError, match="ineligible"):
            approve_and_send(
                decision=bad_decision,
                approved_draft="Draft text.",
                recipient_email="user@example.com",
                approver_identity="admin@beda.studio",
            )

    def test_empty_or_whitespace_draft_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            approve_and_send(
                decision=_make_decision(),
                approved_draft="   ",
                recipient_email="user@example.com",
                approver_identity="admin@beda.studio",
            )

    def test_overlong_draft_rejected(self):
        with pytest.raises(ValueError, match="maximum length"):
            approve_and_send(
                decision=_make_decision(),
                approved_draft="x" * 8001,
                recipient_email="user@example.com",
                approver_identity="admin@beda.studio",
            )

    def test_invalid_ttl_rejected(self):
        with pytest.raises(ValueError, match="TTL"):
            approve_and_send(
                decision=_make_decision(),
                approved_draft="Valid text",
                recipient_email="user@example.com",
                approver_identity="admin@beda.studio",
                ttl_seconds=0,
            )
        with pytest.raises(ValueError, match="TTL"):
            approve_and_send(
                decision=_make_decision(),
                approved_draft="Valid text",
                recipient_email="user@example.com",
                approver_identity="admin@beda.studio",
                ttl_seconds=1_000_000,
            )

    def test_invalid_recipient_email_rejected(self):
        with pytest.raises(ValueError, match="Invalid recipient email"):
            approve_and_send(
                decision=_make_decision(),
                approved_draft="Valid text",
                recipient_email="not-an-email",
                approver_identity="admin@beda.studio",
            )

    def test_empty_approver_identity_rejected(self):
        with pytest.raises(ValueError, match="Approver identity"):
            approve_and_send(
                decision=_make_decision(),
                approved_draft="Valid text",
                recipient_email="user@example.com",
                approver_identity="",
            )


class TestPayloadMutation:
    def test_modified_payload_hash_fails(self):
        cmd = _issue_command()
        tampered = ApprovalCommand(
            approval_id=cmd.approval_id,
            decision_id=cmd.decision_id,
            event_id=cmd.event_id,
            payload_hash="b" * 64,  # Different hash
            recipient_hash=cmd.recipient_hash,
            approver_identity=cmd.approver_identity,
            approved_draft=cmd.approved_draft,
            nonce=cmd.nonce,
            expires_at=cmd.expires_at,
            signature=cmd.signature,
        )
        with pytest.raises(ApprovalVerificationError, match="Signature"):
            verify_approval(tampered)


class TestRecipientMutation:
    def test_modified_recipient_hash_fails(self):
        cmd = _issue_command()
        tampered = ApprovalCommand(
            approval_id=cmd.approval_id,
            decision_id=cmd.decision_id,
            event_id=cmd.event_id,
            payload_hash=cmd.payload_hash,
            recipient_hash="c" * 64,  # Different recipient
            approver_identity=cmd.approver_identity,
            approved_draft=cmd.approved_draft,
            nonce=cmd.nonce,
            expires_at=cmd.expires_at,
            signature=cmd.signature,
        )
        with pytest.raises(ApprovalVerificationError, match="Signature"):
            verify_approval(tampered)


class TestExpiry:
    def test_expired_token_fails(self):
        cmd = _issue_command()
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        with pytest.raises(ApprovalVerificationError, match="expired"):
            verify_approval(cmd, now=future)

    def test_timezone_naive_comparison_rejected(self):
        cmd = _issue_command()
        naive_now = datetime.now()  # timezone-naive
        with pytest.raises(ValueError, match="timezone-aware"):
            verify_approval(cmd, now=naive_now)


class TestReplay:
    def test_replay_fails(self):
        cmd = _issue_command()
        verify_approval(cmd)  # First use succeeds.
        with pytest.raises(ApprovalVerificationError, match="[Rr]eplay|[Nn]once"):
            verify_approval(cmd)  # Second use fails.


class TestWrongSecret:
    def test_wrong_secret_fails(self, monkeypatch):
        cmd = _issue_command()
        monkeypatch.setenv("BEDA_APPROVAL_SECRET", "different_secret_" + "y" * 32)
        reset_replay_registry()
        with pytest.raises(ApprovalVerificationError, match="Signature"):
            verify_approval(cmd)


class TestMissingSecret:
    def test_missing_secret_raises_runtime_error(self, monkeypatch):
        monkeypatch.delenv("BEDA_APPROVAL_SECRET", raising=False)
        with pytest.raises(RuntimeError, match="BEDA_APPROVAL_SECRET"):
            _issue_command()
