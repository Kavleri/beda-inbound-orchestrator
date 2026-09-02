"""
HMAC-SHA256 approval token module.

Demonstration of outbound dispatch authorization. The token binds to:
  - payload_hash (SHA-256 of outbound content)
  - recipient_hash (SHA-256 of recipient identifier)
  - decision_id
  - approval_id
  - nonce
  - expires_at

Verification uses constant-time comparison. A local in-memory replay
registry prevents token reuse within a process. This is labeled as a
local demo — distributed replay prevention requires a shared store
(Redis, database) which is not implemented here.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from .models import ApprovalCommand, RoutingDecision


# ---------------------------------------------------------------------------
# Replay registry (in-memory, local demo only)
# ---------------------------------------------------------------------------

_seen_nonces: set[str] = set()


def reset_replay_registry() -> None:
    """Clear the replay registry. For testing only."""
    _seen_nonces.clear()


# ---------------------------------------------------------------------------
# Token construction
# ---------------------------------------------------------------------------

def _get_secret() -> bytes:
    """Load HMAC secret from environment. Fail loud if missing."""
    secret = os.environ.get("BEDA_APPROVAL_SECRET", "")
    if not secret:
        raise RuntimeError(
            "BEDA_APPROVAL_SECRET environment variable is not set. "
            "Set it to a random hex string of at least 32 characters."
        )
    return secret.encode()


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
    """Compute HMAC-SHA256 over the canonical approval fields."""
    message = (
        f"{payload_hash}::{recipient_hash}::{decision_id}::"
        f"{approval_id}::{nonce}::{expires_at.isoformat()}"
    )
    return hmac.new(secret, message.encode(), hashlib.sha256).hexdigest()


def approve_and_send(
    *,
    decision: RoutingDecision,
    approved_draft: str,
    recipient_email: str,
    approver_identity: str,
    payload_hash: str,
    ttl_seconds: int = 3600,
) -> ApprovalCommand:
    """
    Issue an ApprovalCommand for a specific decision.

    This function should only be called from an authenticated approval
    endpoint (e.g., a Slack interactive action handler or an internal
    admin UI). The demo calls it directly.

    Args:
        decision: The routing decision being approved.
        approved_draft: The exact outbound text approved by the human.
        recipient_email: The recipient's email address.
        approver_identity: Identifier of the human approver.
        payload_hash: SHA-256 of the approved outbound content.
        ttl_seconds: How long the token remains valid.

    Returns:
        A frozen ApprovalCommand with a valid HMAC signature.
    """
    secret = _get_secret()
    approval_id = uuid4()
    nonce = secrets.token_hex(16)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    recipient_hash = hashlib.sha256(recipient_email.encode()).hexdigest()

    signature = _compute_signature(
        payload_hash=payload_hash,
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
        payload_hash=payload_hash,
        recipient_hash=recipient_hash,
        approver_identity=approver_identity,
        approved_draft=approved_draft,
        nonce=nonce,
        expires_at=expires_at,
        signature=signature,
    )


# ---------------------------------------------------------------------------
# Token verification
# ---------------------------------------------------------------------------

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
      2. Token has not expired.
      3. Nonce has not been seen before (replay prevention).

    The replay registry is in-memory and resets on process restart.
    For production use, replace with a distributed store.
    """
    secret = _get_secret()
    now = now or datetime.now(timezone.utc)

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
        raise ApprovalVerificationError("Signature mismatch — token may be tampered.")

    # 2. Expiry check.
    if command.is_expired(now):
        raise ApprovalVerificationError(
            f"Token expired at {command.expires_at.isoformat()}, current time {now.isoformat()}."
        )

    # 3. Replay check (local in-memory registry).
    if command.nonce in _seen_nonces:
        raise ApprovalVerificationError(
            f"Nonce {command.nonce!r} already used — possible replay attack."
        )
    _seen_nonces.add(command.nonce)
