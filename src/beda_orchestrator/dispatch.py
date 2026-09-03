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

from datetime import datetime

from .approval import ApprovalVerificationError, verify_approval
from .audit import AuditEvent, AuditSink
from .enums import AuditEventType, ReasonCode
from .models import ApprovalCommand, InboundEnvelope, RoutingDecision

# This registry is process-local by design. It tracks processed events to return
# idempotent responses within the demo session.
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


class DispatchResult:
    """Result of a dispatch attempt."""

    __slots__ = ("detail", "success")

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

    Single-Use Semantics:
      Verification consumes the command's single-use nonce immediately. If a
      downstream provider failure or network timeout occurs, the command cannot
      be blindly reused. A production system would require a dedicated dispatch
      state machine and provider idempotency key; this reference implementation
      enforces single-use command verification only.

    Steps:
      1. Log dispatch attempt to audit sink.
      2. Verify the approval command (signature, expiry, single-use nonce).
      3. Simulate delivery (print summary to stdout without PII or raw draft).
      4. Log outcome to audit sink.

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
