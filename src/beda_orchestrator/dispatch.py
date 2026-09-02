"""
Mock dispatcher and idempotency registry for the local demo.

The dispatcher accepts only a verified ApprovalCommand. It does not
accept free-form draft text or raw model output. The mock writes the
outbound action to the audit log and prints to stdout.

External integrations (SMTP, SendGrid, Slack) are not implemented.
They would be added as adapter implementations behind the same
interface.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from .approval import ApprovalVerificationError, verify_approval
from .audit import AuditEvent, AuditSink
from .enums import AuditEventType, ReasonCode
from .models import ApprovalCommand, InboundEnvelope, RoutingDecision


# ---------------------------------------------------------------------------
# Idempotency registry (in-memory, local demo)
# ---------------------------------------------------------------------------

_seen_events: dict[str, RoutingDecision] = {}


def reset_idempotency_registry() -> None:
    """Clear the idempotency registry. For testing only."""
    _seen_events.clear()


def check_duplicate(envelope: InboundEnvelope) -> RoutingDecision | None:
    """Return the prior decision if the event_id was already processed."""
    key = str(envelope.idempotency_key)
    return _seen_events.get(key)


def record_decision(envelope: InboundEnvelope, decision: RoutingDecision) -> None:
    """Record a decision for future duplicate checks."""
    _seen_events[str(envelope.idempotency_key)] = decision


# ---------------------------------------------------------------------------
# Mock dispatcher
# ---------------------------------------------------------------------------

class DispatchResult:
    """Result of a dispatch attempt."""

    __slots__ = ("success", "detail")

    def __init__(self, success: bool, detail: str) -> None:
        self.success = success
        self.detail = detail


def mock_dispatch(
    command: ApprovalCommand,
    *,
    audit_sink: AuditSink,
    now: datetime | None = None,
) -> DispatchResult:
    """
    Dispatch an approved outbound message (mock implementation).

    Steps:
      1. Verify the approval command (signature, expiry, replay).
      2. Log the dispatch attempt.
      3. Simulate sending (print to stdout).
      4. Log success or failure.

    Returns:
        DispatchResult indicating success or failure.
    """
    correlation = str(command.event_id)

    # Log dispatch attempt.
    audit_sink.log(AuditEvent(
        event_type=AuditEventType.DISPATCH_ATTEMPTED,
        correlation_id=correlation,
        actor=command.approver_identity,
        payload_hash=command.payload_hash,
        outcome="attempting",
        reason_code="",
        detail=f"Dispatching approved draft for decision {command.decision_id}.",
    ))

    # Verify approval token.
    try:
        verify_approval(command, now=now)
    except ApprovalVerificationError as exc:
        reason = ReasonCode.APPROVAL_SIGNATURE_INVALID
        if "expired" in exc.reason.lower():
            reason = ReasonCode.APPROVAL_EXPIRED
        elif "replay" in exc.reason.lower() or "nonce" in exc.reason.lower():
            reason = ReasonCode.APPROVAL_REPLAY_REJECTED

        audit_sink.log(AuditEvent(
            event_type=AuditEventType.DISPATCH_FAILED,
            correlation_id=correlation,
            actor=command.approver_identity,
            payload_hash=command.payload_hash,
            outcome="rejected",
            reason_code=reason,
            detail=exc.reason,
        ))
        return DispatchResult(success=False, detail=exc.reason)

    # Mock send — in production this would call SMTP or an API.
    print(f"[MOCK DISPATCH] To: (recipient hash {command.recipient_hash[:12]}...) "
          f"Draft length: {len(command.approved_draft)} chars. "
          f"Approved by: {command.approver_identity}")

    audit_sink.log(AuditEvent(
        event_type=AuditEventType.DISPATCH_SUCCEEDED,
        correlation_id=correlation,
        actor=command.approver_identity,
        payload_hash=command.payload_hash,
        outcome="sent",
        reason_code=ReasonCode.DISPATCH_SUCCESS,
        detail="Mock dispatch completed successfully.",
    ))

    return DispatchResult(success=True, detail="Mock dispatch completed.")
