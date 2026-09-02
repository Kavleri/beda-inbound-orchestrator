"""
Domain enums shared across the orchestrator.

Each enum is a StrEnum so it serializes as a plain string in JSON.
Add new values at the end to keep ordinal stability.
"""

from enum import StrEnum


class InquiryIntent(StrEnum):
    """Classification label applied by the extraction stage."""

    ENTERPRISE_SALES = "enterprise_sales"
    TECHNICAL_SUPPORT = "technical_support"
    PARTNERSHIP = "partnership"
    CAREERS = "careers"
    SPAM_OR_MALICIOUS = "spam_or_malicious"
    GENERAL_INQUIRY = "general_inquiry"


class UrgencyLevel(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RoutingAction(StrEnum):
    """Terminal action assigned by the deterministic policy engine."""

    ESCALATE_TO_HUMAN_SALES = "escalate_to_human_sales"
    QUEUE_FOR_HITL_DRAFT_REVIEW = "queue_for_hitl_draft_review"
    TRIGGER_CLARIFICATION = "trigger_clarification"
    AUTO_ARCHIVE_SPAM = "auto_archive_spam"
    QUARANTINE = "quarantine"


class ReasonCode(StrEnum):
    """Stable reason code for metrics and audit. One per policy rule."""

    SPAM_CLASSIFIED = "spam_classified"
    LOW_CONFIDENCE = "low_confidence"
    ENTERPRISE_SALES_QUALIFIED = "enterprise_sales_qualified"
    MISSING_CRITICAL_FIELDS = "missing_critical_fields"
    PROMPT_INJECTION_DETECTED = "prompt_injection_detected"
    CONTRADICTORY_FIELDS = "contradictory_fields"
    SUSPICIOUS_BUDGET = "suspicious_budget"
    STANDARD_HITL_REVIEW = "standard_hitl_review"
    SCHEMA_VALIDATION_FAILED = "schema_validation_failed"
    EXTRACTION_TIMEOUT = "extraction_timeout"
    DUPLICATE_EVENT = "duplicate_event"
    APPROVAL_REPLAY_REJECTED = "approval_replay_rejected"
    APPROVAL_EXPIRED = "approval_expired"
    APPROVAL_SIGNATURE_INVALID = "approval_signature_invalid"
    DISPATCH_SUCCESS = "dispatch_success"
    DISPATCH_FAILURE = "dispatch_failure"
    AUDIT_SINK_FAILURE = "audit_sink_failure"


class AuditEventType(StrEnum):
    """Event types recorded in the audit log."""

    ENVELOPE_RECEIVED = "envelope_received"
    DUPLICATE_DETECTED = "duplicate_detected"
    TRIAGE_COMPLETED = "triage_completed"
    TRIAGE_FAILED = "triage_failed"
    POLICY_DECISION = "policy_decision"
    APPROVAL_ISSUED = "approval_issued"
    APPROVAL_REJECTED = "approval_rejected"
    DISPATCH_ATTEMPTED = "dispatch_attempted"
    DISPATCH_SUCCEEDED = "dispatch_succeeded"
    DISPATCH_FAILED = "dispatch_failed"
    QUARANTINED = "quarantined"
