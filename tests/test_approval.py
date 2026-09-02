"""
Tests for HMAC approval token issuance, verification, and failure modes.

Covers: valid approval, payload mutation, recipient mutation, expiry,
replay, wrong secret, missing secret.
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
    payload_hash = hashlib.sha256(draft.encode()).hexdigest()
    return approve_and_send(
        decision=decision,
        approved_draft=draft,
        recipient_email="client@example.com",
        approver_identity="admin@beda.studio",
        payload_hash=payload_hash,
    )


class TestApprovalIssuance:
    def test_issued_command_verifies(self):
        cmd = _issue_command()
        # Should not raise.
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


class TestPayloadMutation:
    def test_modified_payload_hash_fails(self):
        cmd = _issue_command()
        # Mutate payload_hash by creating a new command with different hash.
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


class TestReplay:
    def test_replay_fails(self):
        cmd = _issue_command()
        verify_approval(cmd)  # First use succeeds.
        with pytest.raises(ApprovalVerificationError, match="[Rr]eplay|[Nn]once"):
            verify_approval(cmd)  # Second use fails.


class TestWrongSecret:
    def test_wrong_secret_fails(self, monkeypatch):
        cmd = _issue_command()
        # Change the secret after issuance.
        monkeypatch.setenv("BEDA_APPROVAL_SECRET", "different_secret_" + "y" * 32)
        reset_replay_registry()
        with pytest.raises(ApprovalVerificationError, match="Signature"):
            verify_approval(cmd)


class TestMissingSecret:
    def test_missing_secret_raises_runtime_error(self, monkeypatch):
        monkeypatch.delenv("BEDA_APPROVAL_SECRET", raising=False)
        with pytest.raises(RuntimeError, match="BEDA_APPROVAL_SECRET"):
            _issue_command()
