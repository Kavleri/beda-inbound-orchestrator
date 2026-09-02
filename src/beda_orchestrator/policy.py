"""
Deterministic policy engine.

Pure function. No network, no database, no side effects.
Evaluates an untrusted InboundTriageResult against deterministic rules
and produces a RoutingDecision. The LLM's lead_tier is ignored; tier
is recomputed from extracted_budget_usd.

Rule precedence (first match wins):
  1. Prompt injection / suspicious content → quarantine
  2. Spam / malicious intent → archive
  3. Contradictory fields → quarantine
  4. Low confidence → HITL review
  5. Enterprise sales (budget ≥ $50k) → human sales escalation
  6. Missing ≥ 2 critical fields → clarification (with approval)
  7. Default → HITL draft review
"""

from __future__ import annotations

import re

from .enums import InquiryIntent, ReasonCode, RoutingAction, UrgencyLevel
from .models import (
    CONFIDENCE_THRESHOLD,
    ENTERPRISE_BUDGET_FLOOR_USD,
    POLICY_VERSION,
    InboundEnvelope,
    InboundTriageResult,
    RoutingDecision,
    _INJECTION_PATTERNS,
)


def _compute_lead_tier(budget: int | None) -> str:
    """Recompute lead tier from budget. Does not trust LLM-provided tier."""
    if budget is None:
        return "unqualified"
    if budget >= ENTERPRISE_BUDGET_FLOOR_USD:
        return "tier_1_enterprise"
    if budget >= 10_000:
        return "tier_2_growth"
    return "tier_3_exploratory"


def _has_injection_signals(triage: InboundTriageResult) -> bool:
    """Check free-text fields for prompt injection patterns."""
    texts = [
        triage.extracted_company or "",
        triage.evidence,
        triage.draft_response,
        " ".join(triage.technical_domains),
    ]
    return any(_INJECTION_PATTERNS.search(t) for t in texts)


def _has_contradictory_fields(triage: InboundTriageResult) -> bool:
    """
    Detect contradictions that suggest unreliable extraction:
    - Intent is spam but confidence is high and budget is present.
    - Budget is very high but intent is support/careers.
    """
    if (
        triage.intent == InquiryIntent.SPAM_OR_MALICIOUS
        and triage.confidence_score > 0.9
        and triage.extracted_budget_usd is not None
        and triage.extracted_budget_usd > 0
    ):
        return True
    if (
        triage.intent in (InquiryIntent.TECHNICAL_SUPPORT, InquiryIntent.CAREERS)
        and triage.extracted_budget_usd is not None
        and triage.extracted_budget_usd >= ENTERPRISE_BUDGET_FLOOR_USD
    ):
        return True
    return False


def _decision(
    envelope: InboundEnvelope,
    triage: InboundTriageResult,
    *,
    action: RoutingAction,
    queue: str,
    approval: bool,
    reason_code: ReasonCode,
    detail: str,
) -> RoutingDecision:
    """Helper to build a RoutingDecision with common fields."""
    return RoutingDecision(
        event_id=envelope.event_id,
        triage_id=triage.triage_id,
        idempotency_key=envelope.idempotency_key,
        action=action,
        target_queue=queue,
        requires_human_approval=approval,
        reason_code=reason_code,
        reason_detail=detail,
        policy_version=POLICY_VERSION,
    )


def evaluate_triage_decision(
    triage: InboundTriageResult,
    envelope: InboundEnvelope,
) -> RoutingDecision:
    """
    Deterministic policy evaluation. Pure function — no side effects.

    Args:
        triage: Untrusted extraction result from LLM or mock.
        envelope: Validated transport metadata.

    Returns:
        A frozen RoutingDecision with action, reason_code, and policy_version.
    """

    # Rule 1: Prompt injection indicators → quarantine immediately.
    if _has_injection_signals(triage):
        return _decision(
            envelope,
            triage,
            action=RoutingAction.QUARANTINE,
            queue="quarantine",
            approval=False,
            reason_code=ReasonCode.PROMPT_INJECTION_DETECTED,
            detail="Prompt injection pattern detected in extraction output.",
        )

    # Rule 2: Spam or malicious classification.
    if triage.intent == InquiryIntent.SPAM_OR_MALICIOUS:
        return _decision(
            envelope,
            triage,
            action=RoutingAction.AUTO_ARCHIVE_SPAM,
            queue="archive_spam",
            approval=False,
            reason_code=ReasonCode.SPAM_CLASSIFIED,
            detail="Intent classified as spam or malicious.",
        )

    # Rule 3: Contradictory fields → quarantine for investigation.
    if _has_contradictory_fields(triage):
        return _decision(
            envelope,
            triage,
            action=RoutingAction.QUARANTINE,
            queue="quarantine",
            approval=False,
            reason_code=ReasonCode.CONTRADICTORY_FIELDS,
            detail="Contradictory extraction fields detected.",
        )

    # Rule 4: Low confidence → mandatory human review.
    if triage.confidence_score < CONFIDENCE_THRESHOLD:
        return _decision(
            envelope,
            triage,
            action=RoutingAction.QUEUE_FOR_HITL_DRAFT_REVIEW,
            queue="hitl_low_confidence",
            approval=True,
            reason_code=ReasonCode.LOW_CONFIDENCE,
            detail=f"Confidence {triage.confidence_score:.2f} below threshold {CONFIDENCE_THRESHOLD}.",
        )

    # Rule 5: Enterprise sales (tier recomputed from budget, not from LLM).
    computed_tier = _compute_lead_tier(triage.extracted_budget_usd)
    if (
        triage.intent == InquiryIntent.ENTERPRISE_SALES
        and computed_tier == "tier_1_enterprise"
    ):
        return _decision(
            envelope,
            triage,
            action=RoutingAction.ESCALATE_TO_HUMAN_SALES,
            queue="sales_tier_1",
            approval=True,
            reason_code=ReasonCode.ENTERPRISE_SALES_QUALIFIED,
            detail=f"Enterprise sales, budget ${triage.extracted_budget_usd:,}, tier recomputed as {computed_tier}.",
        )

    # Rule 6: Missing critical fields → clarification with approval.
    if len(triage.missing_critical_fields) >= 2:
        missing = ", ".join(triage.missing_critical_fields[:5])
        return _decision(
            envelope,
            triage,
            action=RoutingAction.TRIGGER_CLARIFICATION,
            queue="hitl_clarification",
            approval=True,
            reason_code=ReasonCode.MISSING_CRITICAL_FIELDS,
            detail=f"Missing fields: {missing}.",
        )

    # Rule 7: Default — standard HITL review.
    return _decision(
        envelope,
        triage,
        action=RoutingAction.QUEUE_FOR_HITL_DRAFT_REVIEW,
        queue="hitl_standard",
        approval=True,
        reason_code=ReasonCode.STANDARD_HITL_REVIEW,
        detail="Standard inquiry routed for human review.",
    )
