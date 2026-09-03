"""
Interactive Console Application for BEDA Inbound Orchestrator.

Allows human operators to:
1. View all 12 ingested inbound inquiries.
2. Inspect extracted data, detected uncertainties, and CRM matches.
3. Perform manual review: Approve, Reject, or Edit drafts.
4. Issue cryptographically signed ApprovalCommands via HMAC-SHA256.
5. Dispatch outbound messages and inspect audit records.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

# Ensure secret is set
if not os.environ.get("BEDA_APPROVAL_SECRET"):
    os.environ["BEDA_APPROVAL_SECRET"] = "demo_secret_change_me_in_production_32chars"

from .approval import approve_and_send
from .audit import AuditEvent, AuditSink
from .classifier import classify_inquiry
from .dispatch import mock_dispatch
from .drafter import generate_draft_response
from .enums import AuditEventType, ReasonCode, RoutingAction
from .extractor import extract_structured_info
from .matcher import find_crm_match
from .models import InboundEnvelope, RoutingDecision
from .pipeline import load_dataset
from .router import determine_routing_and_staff


def run_interactive_app() -> None:
    base_dir = Path(__file__).resolve().parent.parent.parent
    data_dir = base_dir / "data"
    emails, crm_records, _ = load_dataset(data_dir)

    audit_path = base_dir / "interactive_audit.jsonl"
    audit_sink = AuditSink(audit_path)

    while True:
        print("\n" + "=" * 75)
        print("   BEDA INBOUND INQUIRY ORCHESTRATOR — OPERATOR CONSOLE")
        print("=" * 75)
        print(" Select an inbound item to review and process:\n")

        for idx, item in enumerate(emails, 1):
            sender = item["sender_name"]
            subj = item["subject"][:35]
            print(f"  [{idx:2d}] {item['id']} | {sender:<18} | {subj:<35}")

        print("\n  [ 0] Exit Console")
        print("-" * 75)

        choice = input("Enter inquiry number (0-12): ").strip()
        if choice == "0":
            print("\nExiting Operator Console. Goodbye!\n")
            break

        if not choice.isdigit() or int(choice) < 1 or int(choice) > len(emails):
            print("Invalid selection. Please try again.")
            continue

        selected_item = emails[int(choice) - 1]
        _process_item_interactive(selected_item, crm_records, audit_sink)


def _process_item_interactive(item: dict, crm_records: list, audit_sink: AuditSink) -> None:
    print("\n" + "=" * 75)
    print(f"  REVIEWING INQUIRY: {item['id']} ({item['subject']})")
    print("=" * 75)
    print(f"From:        {item['sender_name']} <{item['sender_email']}>")
    print(f"Subject:     {item['subject']}")
    print(f"Raw Body:\n  \"{item['body']}\"")
    print("-" * 75)

    # 1. Extraction & Uncertainty
    extracted = extract_structured_info(item)
    print("EXTRACTION & UNCERTAINTY ANALYSIS:")
    print(f"  * Extracted Entity:  {extracted.get('extracted_company') or 'None detected'}")
    if extracted.get("annual_consumption_gwh"):
        print(f"  * Consumption:       {extracted['annual_consumption_gwh']} GWh / year")
    if extracted.get("monthly_spend_usd"):
        print(f"  * Monthly Spend:     ${extracted['monthly_spend_usd']:,}")
    if extracted.get("discrepancy_amount_usd"):
        print(f"  * Billing Variance:  ${extracted['discrepancy_amount_usd']:,}")

    if extracted.get("uncertainties"):
        print("  * UNCERTAINTY WARNINGS:")
        for u in extracted["uncertainties"]:
            print(f"    [!] {u}")
    else:
        print("  * Uncertainty Flags: None (Complete factual basis)")

    # 2. CRM Matching
    crm_match = find_crm_match(extracted.get("extracted_company"), item["sender_email"], crm_records)
    print("\nCRM RECORD RESOLUTION:")
    if crm_match:
        rec = crm_match["record"]
        print(f"  * Match Found:       {rec['id']} - {rec['company']} ({crm_match['match_type']})")
        print(f"  * Existing Stage:    {rec.get('stage')} | Service: {rec.get('service')}")
    else:
        print("  * Match Result:      No existing CRM record found (New Prospect)")

    # 3. Classification & Routing
    classification = classify_inquiry(item, extracted)
    routing = determine_routing_and_staff(classification, extracted, crm_match)
    print("\nPOLICY EVALUATION & STAFF ROUTING:")
    print(f"  * Classification:    {classification}")
    print(f"  * Assigned Owner:    {routing['assigned_staff']}")
    print(f"  * Recommended Step:  {routing['recommendation']}")
    print(f"  * Priority Level:    {routing['priority']}")
    print(f"  * Human Approval:    {'REQUIRED' if routing['requires_human_approval'] else 'AUTO-PROCESSED'}")

    # 4. Draft Response
    draft = generate_draft_response(item, classification, extracted, routing)
    print("\nSUGGESTED DRAFT RESPONSE:")
    print("-" * 40)
    print(draft)
    print("-" * 40)

    # 5. Human Action Gate
    if not routing["requires_human_approval"]:
        print("\n-> This item requires NO external human approval (e.g. spam auto-archive).")
        input("\nPress [Enter] to return to the main menu...")
        return

    print("\nHUMAN-IN-THE-LOOP ACTIONS:")
    print("  [1] Approve & Dispatch Draft with HMAC-SHA256 Signature")
    print("  [2] Reject Draft (Flag for Revision)")
    print("  [3] Return to Main Menu without action")

    action_choice = input("\nSelect action (1/2/3): ").strip()
    if action_choice == "1":
        _execute_approval_and_dispatch(item, draft, routing, audit_sink)
    elif action_choice == "2":
        print("\n[DECISION REJECTED] Draft returned to queue for manual editing. No message sent.")
        input("\nPress [Enter] to continue...")
    else:
        print("\nNo action taken.")


def _execute_approval_and_dispatch(item: dict, draft: str, routing: dict, audit_sink: AuditSink) -> None:
    print("\nGenerating cryptographic approval command...")

    # Create dummy decision for approval gate
    import uuid
    dummy_decision = RoutingDecision(
        event_id=uuid.uuid4(),
        triage_id=uuid.uuid4(),
        idempotency_key="interactive_" + item["id"],
        action=RoutingAction.ESCALATE_TO_HUMAN_SALES,
        target_queue="operator_queue",
        requires_human_approval=True,
        reason_code=ReasonCode.STANDARD_HITL_REVIEW,
        reason_detail="Approved via Operator Console",
    )

    payload_hash = hashlib.sha256(draft.encode()).hexdigest()
    approver = routing["assigned_staff"].split("(")[0].strip()

    command = approve_and_send(
        decision=dummy_decision,
        approved_draft=draft,
        recipient_email=item["sender_email"],
        approver_identity=f"{approver} <{routing['staff_email']}>",
        expected_payload_hash=payload_hash,
    )

    print(f"  -> Approval Token:   {command.signature[:32]}... (HMAC-SHA256)")
    print(f"  -> Single-use Nonce: {command.nonce}")
    print(f"  -> Approver:         {command.approver_identity}")

    print("\nDispatching through verified gate...")
    dispatch_res = mock_dispatch(command, audit_sink=audit_sink)

    if dispatch_res.success:
        print("\n[SUCCESS] Outbound message authorized and dispatched to audit trail.")
    else:
        print(f"\n[FAILED] Dispatch rejected: {dispatch_res.detail}")

    input("\nPress [Enter] to return to main menu...")


if __name__ == "__main__":
    run_interactive_app()
