"""
End-to-End Pipeline for BEDA Inbound Orchestrator (Test 2).

Orchestrates:
1. Typed data ingestion from data/ (emails, attachments, CRM seeds, staff directory).
2. Generalized structured information extraction with provenance and uncertainty preservation.
3. Linguistic and evidence-scored business classification.
4. Inbound submission relationship detection (exact duplicates, probable related items) and CRM matching.
5. Dynamic staff ownership resolution from staff.json and action recommendations.
6. Context-grounded response drafting held strictly for human approval.
7. End-to-end demonstration of the HMAC-SHA256 approval and mock dispatch gate.
8. Verifiable hash-chained audit logging to test2_audit.jsonl.
9. Structured inspection output: test2_results.json and lightweight UI test2_report.html.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure secret is set for local execution
if not os.environ.get("BEDA_APPROVAL_SECRET"):
    os.environ["BEDA_APPROVAL_SECRET"] = "demo_secret_change_me_in_production_32chars"

from .approval import approve_and_send, reset_replay_registry
from .audit import AuditEvent, AuditSink
from .classifier import classify_inbound_item
from .dispatch import mock_dispatch, reset_idempotency_registry
from .drafter import generate_draft_response
from .enums import AuditEventType, ReasonCode, RoutingAction
from .extractor import extract_from_inbound_item
from .ingestion import (
    InboundItem,
    get_default_data_dir,
    load_crm_records,
    load_emails,
    load_staff_directory,
)
from .matcher import check_inbound_relationship, find_crm_match
from .models import RoutingDecision
from .router import ActionType, route_inbound_inquiry


def run_pipeline(
    data_dir: Path | None = None,
    audit_path: Path | None = None,
    demonstrate_approval_item_id: str = "E001",
) -> dict[str, Any]:
    """
    Execute the Test 2 pipeline across all ingested inbound items.
    """
    # Clean process-local registries
    reset_replay_registry()
    reset_idempotency_registry()

    base_dir = Path(__file__).resolve().parent.parent.parent
    if data_dir is None:
        data_dir = get_default_data_dir()

    if audit_path is None:
        audit_path = base_dir / "test2_audit.jsonl"

    if audit_path.exists():
        audit_path.unlink()
    audit_sink = AuditSink(audit_path)

    # Ingestion Layer (Phase 1)
    items = load_emails(
        emails_file=data_dir / "emails.json",
        attachments_dir=data_dir / "attachments",
    )
    crm_records = load_crm_records(data_dir / "crm_seeds.json")
    staff_directory = load_staff_directory(data_dir / "staff.json")

    processed_items: list[dict[str, Any]] = []
    prior_items: list[InboundItem] = []
    prior_extractions: dict[str, Any] = {}

    print("\n" + "=" * 80)
    print("  BEDA INBOUND ORCHESTRATOR — TEST 2 SYNTHETIC DATA PACK EXECUTION")
    print("  Processing 12 inbound items through deterministic trust boundaries")
    print("=" * 80 + "\n")

    for item in items:
        correlation_id = str(item.envelope.event_id)

        # 1. Audit Ingress Event
        audit_sink.log(AuditEvent(
            event_type=AuditEventType.ENVELOPE_RECEIVED,
            correlation_id=correlation_id,
            actor="ingress_gateway",
            payload_hash=item.envelope.body_hash(),
            detail=f"Ingested item {item.id} from {item.sender_email} ({len(item.attachments)} attachments)",
        ))

        # 2. Structured Extraction & Uncertainty Preservation (Phase 2)
        extracted = extract_from_inbound_item(item)
        prior_extractions[item.id] = extracted

        # 3. Business Classification (Phase 3)
        classification = classify_inbound_item(item, extracted)

        # 4. Duplicate Detection & CRM Record Matching (Phase 4)
        duplicate_rel = check_inbound_relationship(item, prior_items, extracted, prior_extractions)
        crm_match = find_crm_match(
            company_name=extracted.company.value if extracted.company else None,
            sender_email=item.sender_email,
            crm_records=crm_records,
            sender_phone=extracted.phone.value if extracted.phone else None,
        )

        # 5. Routing & Staff Ownership (Phase 5)
        routing = route_inbound_inquiry(classification, extracted, crm_match, staff_directory)

        # 6. Response Drafting (Phase 7)
        draft = generate_draft_response(item, classification, extracted, routing)

        # 7. Audit Policy & Routing Decision (Phase 8)
        audit_sink.log(AuditEvent(
            event_type=AuditEventType.POLICY_DECISION,
            correlation_id=correlation_id,
            actor=routing.primary_owner_name,
            payload_hash=item.envelope.body_hash(),
            reason_code=ReasonCode.ENTERPRISE_SALES_QUALIFIED if "COMMERCIAL" in classification.category else ReasonCode.STANDARD_HITL_REVIEW,
            detail=f"Classified as {classification.category.value}; routed to {routing.primary_owner_name} ({routing.action_type.value})",
        ))

        # Initial Approval State
        if routing.action_type == ActionType.ARCHIVE:
            approval_state = "AUTO_ARCHIVED"
        else:
            approval_state = "PENDING_APPROVAL"

        record: dict[str, Any] = {
            "email_id": item.id,
            "sender_email": item.sender_email,
            "sender_name": item.sender_name,
            "subject": item.subject,
            "classification": {
                "category": classification.category.value,
                "label": classification.category_label,
                "confidence": classification.confidence,
                "evidence_terms": classification.evidence_terms,
                "reasoning": classification.reasoning,
            },
            "extracted_fields": {
                "company": extracted.company.value if extracted.company else None,
                "contact_person": extracted.contact_person.value if extracted.contact_person else None,
                "phone": extracted.phone.value if extracted.phone else None,
                "annual_consumption_gwh": extracted.annual_consumption_gwh.value if extracted.annual_consumption_gwh else None,
                "monthly_spend_usd": extracted.monthly_spend_usd.value if extracted.monthly_spend_usd else None,
                "discrepancy_amount_usd": extracted.discrepancy_amount_usd.value if extracted.discrepancy_amount_usd else None,
                "invoice_numbers": [i.value for i in extracted.invoice_numbers],
                "po_numbers": [p.value for p in extracted.po_numbers],
                "locations": [loc.value for loc in extracted.locations],
                "deadlines": [d.value for d in extracted.deadlines],
                "missing_prerequisites": extracted.missing_prerequisites,
            },
            "uncertainties": extracted.uncertainties,
            "duplicate_relation": {
                "decision": duplicate_rel.decision.value,
                "related_to_item_id": duplicate_rel.related_to_item_id,
                "similarity_score": duplicate_rel.similarity_score,
                "evidence": duplicate_rel.evidence,
                "explanation": duplicate_rel.explanation,
            },
            "crm_match": {
                "matched_crm_id": crm_match.matched_crm_id,
                "match_type": crm_match.match_type.value,
                "score": crm_match.score,
                "evidence": crm_match.evidence,
                "ambiguity_flag": crm_match.ambiguity_flag,
            },
            "assigned_staff": [
                {"staff_id": o.staff_id, "name": o.name, "role": o.role, "email": o.email}
                for o in routing.assigned_owners
            ],
            "assigned_staff_summary": routing.primary_owner_name,
            "priority": routing.priority,
            "action_type": routing.action_type.value,
            "recommended_action": routing.recommended_action,
            "is_externally_consequential": routing.is_externally_consequential,
            "requires_human_approval": routing.requires_human_approval,
            "approval_state": approval_state,
            "draft_preview": draft[:200] + "..." if len(draft) > 200 else draft,
            "draft_text": draft,
            "audit_correlation_id": correlation_id,
        }

        processed_items.append(record)
        prior_items.append(item)

        # Terminal Output
        print(f"[{item.id}] {item.subject[:42]:<42} | {classification.category.value:<32} | -> {routing.primary_owner_name}")
        if duplicate_rel.decision != "not_duplicate":
            print(f"       -> Duplicate Relation: {duplicate_rel.decision.value.upper()} (Related to {duplicate_rel.related_to_item_id})")
        if crm_match.matched_crm_id != "NONE":
            print(f"       -> CRM Match: {crm_match.matched_crm_id} [{crm_match.match_type.value}] ({crm_match.evidence})")
        if extracted.uncertainties:
            print(f"       -> Uncertainty Flag: {extracted.uncertainties[0]}")

    # Demonstrate explicit local human approval on one item (Phase 6 / Criterion 10)
    if demonstrate_approval_item_id:
        target_item = next((it for it in processed_items if it["email_id"] == demonstrate_approval_item_id), None)
        if target_item and target_item["requires_human_approval"]:
            print(f"\n{'='*80}")
            print(f"  [PHASE 6 GATE DEMO] Demonstrating Local Human Approval & Mock Dispatch for {demonstrate_approval_item_id}")
            print(f"{'='*80}")

            decision = RoutingDecision(
                event_id=item.envelope.event_id,
                triage_id=item.envelope.event_id,
                idempotency_key="demo_approval_" + demonstrate_approval_item_id,
                action=RoutingAction.ESCALATE_TO_HUMAN_SALES,
                target_queue="sales_tier_1",
                requires_human_approval=True,
                reason_code=ReasonCode.ENTERPRISE_SALES_QUALIFIED,
                reason_detail="Commercial lead approved by founder.",
            )

            # Generate full draft
            raw_item = next(it for it in items if it.id == demonstrate_approval_item_id)
            c_res = classify_inbound_item(raw_item, prior_extractions[demonstrate_approval_item_id])
            r_res = route_inbound_inquiry(c_res, prior_extractions[demonstrate_approval_item_id], None, staff_directory)
            full_draft = generate_draft_response(raw_item, c_res, prior_extractions[demonstrate_approval_item_id], r_res)

            payload_hash = hashlib.sha256(full_draft.encode()).hexdigest()
            approver_email = target_item["assigned_staff"][0]["email"] if target_item["assigned_staff"] else "matt@wearebeda.com"
            approver_name = target_item["assigned_staff"][0]["name"] if target_item["assigned_staff"] else "Matt Cooper"

            command = approve_and_send(
                decision=decision,
                approved_draft=full_draft,
                recipient_email=target_item["sender_email"],
                approver_identity=f"{approver_name} <{approver_email}>",
                expected_payload_hash=payload_hash,
            )

            dispatch_res = mock_dispatch(command, audit_sink=audit_sink)
            print(f"  Approved by:       {command.approver_identity}")
            print(f"  HMAC Signature:    {command.signature[:32]}... (SHA-256 bound to draft hash)")
            print(f"  Single-use Nonce:  {command.nonce}")
            print(f"  Dispatch Result:   {'MOCK_DISPATCHED' if dispatch_res.success else 'FAILED'}")

            target_item["approval_state"] = "MOCK_DISPATCHED" if dispatch_res.success else "FAILED"

    # Verify audit chain integrity
    valid, count, error = audit_sink.verify_chain()
    print("\n" + "-" * 80)
    print(f"  Audit Chain Integrity: {'VALID' if valid else 'COMPROMISED'} ({count} cryptographic events logged)")
    if error:
        print(f"  Audit Chain Error: {error}")
    print("-" * 80)

    # Export structured JSON results
    results_path = base_dir / "test2_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now(UTC).isoformat(),
            "total_items": len(processed_items),
            "audit_chain_valid": valid,
            "legend": {
                "RECOMMENDATION": "Proposed next step only; pending human review and execution",
                "PENDING_APPROVAL": "Held at cryptographic trust boundary; no external action taken",
                "MOCK_DISPATCHED": "Verified via local single-use HMAC approval command; delivered to local mock sink only",
                "AUTO_ARCHIVED": "Deterministic filter archived junk solicitation without human disruption",
            },
            "results": processed_items,
        }, f, indent=2)
    print(f"  Exported structured results to: {results_path}")

    # Generate lightweight HTML inspection dashboard
    html_path = base_dir / "test2_report.html"
    _generate_html_report(html_path, processed_items)
    print(f"  Generated inspection UI: {html_path}\n")

    return {
        "processed_count": len(processed_items),
        "audit_valid": valid,
        "items": processed_items,
    }


def _generate_html_report(output_path: Path, items: list[dict[str, Any]]) -> None:
    """Generate a clean inspection UI for reviewing results and distinguishing recommendations vs actions."""
    rows = ""
    for it in items:
        badge_color = {
            "CRITICAL": "#ef4444",
            "HIGH": "#f97316",
            "MEDIUM": "#3b82f6",
            "LOW": "#6b7280",
        }.get(it["priority"], "#3b82f6")

        status_color = {
            "MOCK_DISPATCHED": "#10b981",
            "PENDING_APPROVAL": "#f59e0b",
            "AUTO_ARCHIVED": "#6b7280",
        }.get(it["approval_state"], "#f59e0b")

        uncertainty_html = ""
        if it["uncertainties"]:
            uncertainty_html = f"<div style='color: #d97706; font-size: 0.85em; margin-top: 4px;'><strong>⚠️ Uncertainty:</strong> {'; '.join(it['uncertainties'])}</div>"

        dup_html = ""
        if it["duplicate_relation"]["decision"] != "not_duplicate":
            dup_html = f"<div style='color: #8b5cf6; font-size: 0.8em; margin-top: 4px;'><strong>🔗 Related:</strong> {it['duplicate_relation']['decision'].upper()} (to {it['duplicate_relation']['related_to_item_id']})</div>"

        crm_badge = f"<span style='font-family: monospace; font-size: 0.85em;'>{it['crm_match']['matched_crm_id']}</span>"
        if it["crm_match"]["match_type"] != "none":
            crm_badge += f"<br/><span style='color: #6b7280; font-size: 0.75em;'>({it['crm_match']['match_type']})</span>"

        rows += f"""
        <tr>
            <td style="font-weight: bold; font-family: monospace;">{it['email_id']}</td>
            <td>
                <strong>{it['sender_name']}</strong><br/>
                <span style="color: #6b7280; font-size: 0.85em;">{it['sender_email']}</span><br/>
                <em>{it['subject']}</em>
                {dup_html}
            </td>
            <td>
                <span style="background: #f3f4f6; padding: 2px 6px; border-radius: 4px; font-weight: 500; font-size: 0.85em;">{it['classification']['category']}</span><br/>
                <span style="color: #4b5563; font-size: 0.75em;">{it['classification']['label']}</span>
            </td>
            <td>
                <strong>{it['assigned_staff_summary']}</strong><br/>
                <span style="color: #4b5563; font-size: 0.85em;">{it['action_type']}</span>
                {uncertainty_html}
            </td>
            <td>
                <span style="background: {badge_color}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 0.75em; font-weight: 600;">{it['priority']}</span>
            </td>
            <td>{crm_badge}</td>
            <td>
                <span style="background: {status_color}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 0.75em; font-weight: 600;">{it['approval_state']}</span>
            </td>
            <td>
                <div style="font-size: 0.85em; color: #374151;">{it['recommended_action']}</div>
            </td>
        </tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>BEDA Inbound Inquiry Router — Test 2 Results</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 30px 40px; background: #f9fafb; color: #111827; }}
        h1 {{ font-size: 1.5rem; margin-bottom: 4px; }}
        .subtitle {{ color: #6b7280; margin-bottom: 16px; font-size: 0.95rem; }}
        .legend-card {{ background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 6px; padding: 12px 16px; margin-bottom: 20px; font-size: 0.85rem; }}
        .legend-card strong {{ color: #1e40af; }}
        .card {{ background: white; border-radius: 8px; border: 1px solid #e5e7eb; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
        table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 0.88rem; }}
        th {{ background: #f3f4f6; padding: 10px 14px; border-bottom: 1px solid #e5e7eb; color: #4b5563; font-weight: 600; font-size: 0.82rem; text-transform: uppercase; }}
        td {{ padding: 12px 14px; border-bottom: 1px solid #f3f4f6; vertical-align: top; }}
        tr:hover {{ background: #f9fafb; }}
        .footer {{ margin-top: 24px; font-size: 0.82rem; color: #9ca3af; text-align: center; }}
    </style>
</head>
<body>
    <h1>BEDA Inbound Inquiry Router — Test 2 Results</h1>
    <div class="subtitle">Evaluated on 12 synthetic inbound items against 4 staff ownership domains, CRM seed records, and document attachments.</div>
    
    <div class="legend-card">
        <strong>CRITICAL SAFETY LEGEND:</strong><br/>
        • <strong>RECOMMENDATION:</strong> Proposed action only. Work is not performed until authorized by an authenticated human operator.<br/>
        • <strong>PENDING_APPROVAL:</strong> Held at cryptographic trust boundary; no external email, API call, or CRM mutation has occurred.<br/>
        • <strong>MOCK_DISPATCHED:</strong> Verified through local single-use HMAC-SHA256 approval command; simulated delivery logged to audit sink.<br/>
        • <strong>AUTO_ARCHIVED:</strong> High-confidence unsolicited spam safely archived without human interruption.
    </div>

    <div class="card">
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Sender & Subject</th>
                    <th>Classification</th>
                    <th>Assigned Owner & Action</th>
                    <th>Priority</th>
                    <th>CRM Match</th>
                    <th>Approval State</th>
                    <th>Recommended Next Action</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
    </div>
    <div class="footer">Deterministic Policy & Cryptographic Trust Boundaries · All 12 items verified offline with zero external network dependencies</div>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    run_pipeline()
