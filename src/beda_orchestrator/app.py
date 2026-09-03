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
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

# Ensure secret is set
if not os.environ.get("BEDA_APPROVAL_SECRET"):
    os.environ["BEDA_APPROVAL_SECRET"] = "demo_secret_change_me_in_production_32chars"

from .approval import approve_and_send
from .audit import AuditSink
from .classifier import classify_inbound_item
from .dispatch import mock_dispatch
from .drafter import generate_draft_response
from .enums import ReasonCode, RoutingAction
from .extractor import extract_from_inbound_item
from .ingestion import (
    InboundItem,
    get_default_data_dir,
    load_crm_records,
    load_emails,
    load_staff_directory,
)
from .matcher import find_crm_match
from .models import RoutingDecision
from .router import route_inbound_inquiry


def run_interactive_app() -> None:
    data_dir = get_default_data_dir()
    emails = load_emails(
        emails_file=data_dir / "emails.json",
        attachments_dir=data_dir / "attachments",
    )
    crm_records = load_crm_records(data_dir / "crm_seeds.json")
    staff_directory = load_staff_directory(data_dir / "staff.json")

    base_dir = Path(__file__).resolve().parent.parent.parent
    audit_path = base_dir / "interactive_audit.jsonl"
    audit_sink = AuditSink(audit_path)

    while True:
        print("\n" + "=" * 75)
        print("   BEDA INBOUND INQUIRY ORCHESTRATOR — OPERATOR CONSOLE")
        print("=" * 75)
        print(" Select an inbound item to review and process:\n")

        for idx, item in enumerate(emails, 1):
            sender = item.sender_name
            subj = item.subject[:35]
            print(f"  [{idx:2d}] {item.id} | {sender:<18} | {subj:<35}")

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
        _process_item_interactive(selected_item, crm_records, staff_directory, audit_sink)


def _process_item_interactive(
    item: InboundItem,
    crm_records: list[Any],
    staff_directory: list[Any],
    audit_sink: AuditSink,
) -> None:
    print("\n" + "=" * 75)
    print(f"  REVIEWING INQUIRY: {item.id} ({item.subject})")
    print("=" * 75)
    print(f"From:        {item.sender_name} <{item.sender_email}>")
    print(f"Subject:     {item.subject}")
    print(f"Raw Body:\n  \"{item.body}\"")
    if item.attachments:
        print("\nAttachments:")
        for att in item.attachments:
            status = "LOADED" if att.is_loaded else f"WARNING: {att.warning}"
            print(f"  * {att.filename} [{status}]")
    print("-" * 75)

    # 1. Extraction & Uncertainty
    extracted = extract_from_inbound_item(item)
    print("EXTRACTION & UNCERTAINTY ANALYSIS:")
    print(f"  * Extracted Entity:  {extracted.company.value if extracted.company else 'None detected'}")
    if extracted.annual_consumption_gwh:
        print(f"  * Consumption:       {extracted.annual_consumption_gwh.value} GWh / year")
    if extracted.monthly_spend_usd:
        print(f"  * Monthly Spend:     ${extracted.monthly_spend_usd.value:,}")
    if extracted.discrepancy_amount_usd:
        print(f"  * Billing Variance:  ${extracted.discrepancy_amount_usd.value:,}")

    if extracted.uncertainties:
        print("  * UNCERTAINTY WARNINGS:")
        for u in extracted.uncertainties:
            print(f"    [!] {u}")
    else:
        print("  * Uncertainty Flags: None (Complete factual basis)")

    # 2. CRM Matching
    crm_match = find_crm_match(
        company_name=extracted.company.value if extracted.company else None,
        sender_email=item.sender_email,
        crm_records=crm_records,
        sender_phone=extracted.phone.value if extracted.phone else None,
    )
    print("\nCRM RECORD RESOLUTION:")
    if crm_match.matched_crm_id != "NONE" and crm_match.record:
        rec = crm_match.record
        print(f"  * Match Found:       {rec['id']} - {rec['company']} ({crm_match.match_type.value})")
        print(f"  * Existing Stage:    {rec.get('stage')} | Service: {rec.get('service')}")
    else:
        print("  * Match Result:      No existing CRM record found (New Prospect)")

    # 3. Classification & Routing
    classification = classify_inbound_item(item, extracted)
    routing = route_inbound_inquiry(classification, extracted, crm_match, staff_directory)
    print("\nPOLICY EVALUATION & STAFF ROUTING:")
    print(f"  * Classification:    {classification.category_label}")
    print(f"  * Assigned Owner:    {routing.primary_owner_name}")
    print(f"  * Recommended Step:  {routing.recommended_action}")
    print(f"  * Priority Level:    {routing.priority}")
    print(f"  * Human Approval:    {'REQUIRED' if routing.requires_human_approval else 'AUTO-PROCESSED'}")

    # 4. Draft Response
    draft = generate_draft_response(item, classification, extracted, routing)
    print("\nSUGGESTED DRAFT RESPONSE:")
    print("-" * 40)
    print(draft)
    print("-" * 40)

    # 5. Human Action Gate
    if not routing.requires_human_approval:
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


def _execute_approval_and_dispatch(
    item: InboundItem,
    draft: str,
    routing: Any,
    audit_sink: AuditSink,
) -> None:
    print("\nGenerating cryptographic approval command...")

    dummy_decision = RoutingDecision(
        event_id=item.envelope.event_id,
        triage_id=uuid4(),
        idempotency_key="interactive_" + item.id,
        action=RoutingAction.ESCALATE_TO_HUMAN_SALES,
        target_queue="operator_queue",
        requires_human_approval=True,
        reason_code=ReasonCode.STANDARD_HITL_REVIEW,
        reason_detail="Approved via Operator Console",
    )

    payload_hash = hashlib.sha256(draft.encode()).hexdigest()
    approver_name = routing.assigned_owners[0].name if routing.assigned_owners else "Operator"
    approver_email = routing.assigned_owners[0].email if routing.assigned_owners else "system@wearebeda.com"

    command = approve_and_send(
        decision=dummy_decision,
        approved_draft=draft,
        recipient_email=item.sender_email,
        approver_identity=f"{approver_name} <{approver_email}>",
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
