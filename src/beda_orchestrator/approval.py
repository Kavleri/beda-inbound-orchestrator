"""
HMAC-SHA256 approval token module.

Demonstration of outbound dispatch authorization. The token binds to:
  - payload_hash (SHA-256 of outbound content)
  - recipient_hash (SHA-256 of normalized recipient identifier)
  - decision_id
  - approval_id
  - nonce
  - expires_at

Security invariants:
  1. Payload hash is computed internally from approved_draft. Caller cannot spoof it.
  2. ApprovalCommand can only be issued for decisions requiring human approval
     and eligible actions (no spam, no quarantine).
  3. Verification uses constant-time HMAC comparison.
  4. Single-use nonce prevents replay attacks within the process.
  5. Tokens have bounded TTL (max 7 days) and explicit timezone-aware expiry.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from .enums import RoutingAction
from .models import ApprovalCommand, RoutingDecision

MAX_APPROVAL_TTL_SECONDS = 604_800  # 7 days
MIN_APPROVAL_TTL_SECONDS = 1
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

# Ineligible actions that must not produce an outbound approval command.
INELIGIBLE_ACTIONS = {
    RoutingAction.AUTO_ARCHIVE_SPAM,
    RoutingAction.QUARANTINE,
}

# This registry is process-local by design. A production deployment would need
# a shared idempotency store; distributed replay prevention is out of scope here.
_seen_nonces: set[str] = set()


def reset_replay_registry() -> None:
    """Clear the replay registry. For testing only."""
    _seen_nonces.clear()


def _get_secret() -> bytes:
    """Load HMAC secret from environment. Fail loud if missing."""
    secret = os.environ.get("BEDA_APPROVAL_SECRET", "")
    if not secret:
        raise RuntimeError(
            "BEDA_APPROVAL_SECRET environment variable is not set. "
            "Set it to a random hex string of at least 32 characters."
        )
    return secret.encode("utf-8")


def _compute_signature(
    *,
    payload_hash: str,
    recipient_hash: str,
    decision_id: UUID,
    approval_id: UUID,
    nonce: str,
    expires_at: datetime,
    secret: bytes,
) -> str:
    """Compute HMAC-SHA256 over canonical approval fields."""
    message = (
        f"{payload_hash}::{recipient_hash}::{decision_id}::"
        f"{approval_id}::{nonce}::{expires_at.isoformat()}"
    )
    return hmac.new(secret, message.encode("utf-8"), hashlib.sha256).hexdigest()


def approve_and_send(
    *,
    decision: RoutingDecision,
    approved_draft: str,
    recipient_email: str,
    approver_identity: str,
    expected_payload_hash: str | None = None,
    ttl_seconds: int = 3600,
) -> ApprovalCommand:
    """
    Issue an ApprovalCommand for an eligible routing decision.

    Security & Eligibility Checks:
      1. Decision must require human approval (`requires_human_approval == True`).
      2. Decision action must be outbound-eligible (not spam, not quarantine).
      3. Draft must be non-empty and within length limits (1..8000).
      4. Recipient email must be well-formed.
      5. Approver identity must be non-empty.
      6. TTL must be bounded (1s .. 7 days).
      7. Payload hash is computed deterministically from approved_draft.

    Args:
        decision: The routing decision being approved.
        approved_draft: The exact outbound text approved by the human.
        recipient_email: The recipient's email address.
        approver_identity: Identifier of the authenticated human approver.
        expected_payload_hash: Optional expected SHA-256 for verification.
        ttl_seconds: How long the token remains valid (default: 1 hour).

    Returns:
        A frozen ApprovalCommand with a valid HMAC signature.
    """
    # 1. Eligibility: must require approval
    if not decision.requires_human_approval:
        raise ValueError(
            f"Decision {decision.decision_id} does not require human approval."
        )

    # 2. Eligibility: action check
    if decision.action in INELIGIBLE_ACTIONS:
        raise ValueError(
            f"Action '{decision.action}' is ineligible for outbound approval."
        )

    # 3. Draft validation
    cleaned_draft = approved_draft.strip()
    if not cleaned_draft:
        raise ValueError("Approved draft cannot be empty or whitespace-only.")
    if len(approved_draft) > 8000:
        raise ValueError("Approved draft exceeds maximum length (8000 characters).")

    # 4. Recipient validation
    norm_recipient = recipient_email.strip().lower()
    if not EMAIL_REGEX.match(norm_recipient):
        raise ValueError(f"Invalid recipient email format: {recipient_email!r}")

    # 5. Approver validation
    if not approver_identity or not approver_identity.strip():
        raise ValueError("Approver identity cannot be empty.")

    # 6. TTL bounds validation
    if ttl_seconds < MIN_APPROVAL_TTL_SECONDS or ttl_seconds > MAX_APPROVAL_TTL_SECONDS:
        raise ValueError(
            f"TTL must be between {MIN_APPROVAL_TTL_SECONDS}s and "
            f"{MAX_APPROVAL_TTL_SECONDS}s (got {ttl_seconds}s)."
        )

    # 7. Internal payload & recipient hash computation
    computed_payload_hash = hashlib.sha256(approved_draft.encode("utf-8")).hexdigest()
    if expected_payload_hash and expected_payload_hash != computed_payload_hash:
        raise ValueError(
            f"Provided expected_payload_hash mismatch: expected {expected_payload_hash!r}, "
            f"computed {computed_payload_hash!r}."
        )

    recipient_hash = hashlib.sha256(norm_recipient.encode("utf-8")).hexdigest()

    secret = _get_secret()
    approval_id = uuid4()
    nonce = secrets.token_hex(16)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

    signature = _compute_signature(
        payload_hash=computed_payload_hash,
        recipient_hash=recipient_hash,
        decision_id=decision.decision_id,
        approval_id=approval_id,
        nonce=nonce,
        expires_at=expires_at,
        secret=secret,
    )

    return ApprovalCommand(
        approval_id=approval_id,
        decision_id=decision.decision_id,
        event_id=decision.event_id,
        payload_hash=computed_payload_hash,
        recipient_hash=recipient_hash,
        approver_identity=approver_identity.strip(),
        approved_draft=approved_draft,
        nonce=nonce,
        expires_at=expires_at,
        signature=signature,
    )


class ApprovalVerificationError(Exception):
    """Raised when an approval command fails verification."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def verify_approval(
    command: ApprovalCommand,
    *,
    now: datetime | None = None,
) -> None:
    """
    Verify an ApprovalCommand. Raises ApprovalVerificationError on failure.

    Checks:
      1. Signature is valid (constant-time comparison).
      2. Token has not expired (timezone-aware).
      3. Nonce has not been seen before (single-use command).

    Verification consumes the single-use nonce. A replayed command fails closed.
    """
    secret = _get_secret()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Comparison datetime 'now' must be timezone-aware (e.g. UTC).")

    # 1. Constant-time signature verification.
    expected = _compute_signature(
        payload_hash=command.payload_hash,
        recipient_hash=command.recipient_hash,
        decision_id=command.decision_id,
        approval_id=command.approval_id,
        nonce=command.nonce,
        expires_at=command.expires_at,
        secret=secret,
    )
    if not hmac.compare_digest(expected, command.signature):
        raise ApprovalVerificationError("Signature mismatch -- token may be tampered.")

    # 2. Expiry check.
    if command.is_expired(now):
        raise ApprovalVerificationError(
            f"Token expired at {command.expires_at.isoformat()}, current time {now.isoformat()}."
        )

    # 3. Replay check (single-use consumption).
    if command.nonce in _seen_nonces:
        raise ApprovalVerificationError(
            f"Nonce {command.nonce!r} already used -- single-use command cannot be replayed."
        )
    _seen_nonces.add(command.nonce)
