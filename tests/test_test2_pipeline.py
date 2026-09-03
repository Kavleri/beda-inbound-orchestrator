"""
Comprehensive Test Matrix for Test 2.

Covers:
1. Specific assertions for all 12 synthetic items (E001–E012).
2. Generalization / anti-overfitting tests on completely unseen synthetic inputs.
3. Invariant tests: non-null classifications, staff assignments, and default pending approval.
4. Cryptographic approval and dispatch gate tests (HMAC-SHA256, payload tampering, replay prevention).
5. Audit log hash-chain verification and tampering detection.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from beda_orchestrator.approval import (
    ApprovalVerificationError,
    approve_and_send,
    reset_replay_registry,
    verify_approval,
)
from beda_orchestrator.audit import AuditEvent, AuditSink
from beda_orchestrator.classifier import BusinessCategory, classify_inbound_item
from beda_orchestrator.dispatch import mock_dispatch, reset_idempotency_registry
from beda_orchestrator.enums import AuditEventType, ReasonCode, RoutingAction
from beda_orchestrator.extractor import extract_from_inbound_item
from beda_orchestrator.ingestion import (
    load_staff_directory,
)
from beda_orchestrator.matcher import (
    SubmissionRelationship,
)
from beda_orchestrator.models import RoutingDecision
from beda_orchestrator.pipeline import run_pipeline
from beda_orchestrator.router import ActionType, route_inbound_inquiry


@pytest.fixture(autouse=True)
def _reset_test_state(monkeypatch):
    monkeypatch.setenv("BEDA_APPROVAL_SECRET", "test_suite_secret_key_32_characters_long")
    reset_replay_registry()
    reset_idempotency_registry()


@pytest.fixture(scope="module")
def pipeline_run_data():
    return run_pipeline()


# ==============================================================================
# 1. SPECIFIC EMAIL TESTS FOR ALL 12 ITEMS (E001–E012)
# ==============================================================================

class TestAllTwelveInboundItems:
    def test_e001_multi_site_commercial_solar(self, pipeline_run_data):
        item = next(it for it in pipeline_run_data["items"] if it["email_id"] == "E001")
        assert item["classification"]["category"] == BusinessCategory.COMMERCIAL_SOLAR_MULTI_SITE
        assert "Matt Cooper" in item["assigned_staff_summary"]
        assert item["extracted_fields"]["annual_consumption_gwh"] == 2.1
        assert "Truganina" in item["extracted_fields"]["locations"]
        assert "Dandenong" in item["extracted_fields"]["locations"]
        assert "Epping" in item["extracted_fields"]["locations"]
        assert item["crm_match"]["matched_crm_id"] == "C001"
        assert item["approval_state"] == "MOCK_DISPATCHED"  # Demonstrated in pipeline

    def test_e002_related_submission_hume(self, pipeline_run_data):
        item = next(it for it in pipeline_run_data["items"] if it["email_id"] == "E002")
        assert item["classification"]["category"] == BusinessCategory.COMMERCIAL_SOLAR_MULTI_SITE
        assert "Matt Cooper" in item["assigned_staff_summary"]
        assert item["duplicate_relation"]["decision"] == SubmissionRelationship.PROBABLE_RELATED_SUBMISSION
        assert item["duplicate_relation"]["related_to_item_id"] == "E001"
        assert item["crm_match"]["matched_crm_id"] == "C002"
        assert item["approval_state"] == "PENDING_APPROVAL"

    def test_e003_billing_invoice_dispute(self, pipeline_run_data):
        item = next(it for it in pipeline_run_data["items"] if it["email_id"] == "E003")
        assert item["classification"]["category"] == BusinessCategory.BILLING_INVOICE_DISPUTE
        assert item["action_type"] == ActionType.PAYMENT_HOLD
        assert item["extracted_fields"]["discrepancy_amount_usd"] == 2640
        assert "1847" in item["extracted_fields"]["invoice_numbers"]
        assert any("8821" in po for po in item["extracted_fields"]["po_numbers"])
        assert "Ali Pratama" in item["assigned_staff_summary"]
        assert "Ties Rahardjo" in item["assigned_staff_summary"]
        assert "hold" in item["recommended_action"].lower()
        assert item["approval_state"] == "PENDING_APPROVAL"

    def test_e004_spam_auto_archive(self, pipeline_run_data):
        item = next(it for it in pipeline_run_data["items"] if it["email_id"] == "E004")
        assert item["classification"]["category"] == BusinessCategory.SPAM_SOLICITATION
        assert item["action_type"] == ActionType.ARCHIVE
        assert item["requires_human_approval"] is False
        assert item["approval_state"] == "AUTO_ARCHIVED"
        assert "NO DRAFT" in item["draft_preview"]

    def test_e005_clarification_lighting_no_hallucination(self, pipeline_run_data):
        item = next(it for it in pipeline_run_data["items"] if it["email_id"] == "E005")
        assert item["classification"]["category"] == BusinessCategory.CLARIFICATION_LIGHTING_INCENTIVE
        assert "electricity_bill" in item["extracted_fields"]["missing_prerequisites"]
        assert any("electricity bill" in u.lower() for u in item["uncertainties"])
        # Verify draft does not hallucinate arbitrary incentive dollar values
        assert "$" not in item["draft_preview"]
        assert "Zidane Mouldino" in item["assigned_staff_summary"]
        assert item["approval_state"] == "PENDING_APPROVAL"

    def test_e006_technical_engineering_review(self, pipeline_run_data):
        item = next(it for it in pipeline_run_data["items"] if it["email_id"] == "E006")
        assert item["classification"]["category"] == BusinessCategory.TECHNICAL_ENGINEERING_REVIEW
        assert item["action_type"] == ActionType.TECHNICAL_ENGINEERING_REVIEW
        assert any("harmonic" in u.lower() or "thd" in u.lower() for u in item["uncertainties"])
        assert "Ali Pratama" in item["assigned_staff_summary"]
        assert "electrical systems engineer" in item["draft_text"].lower()
        assert item["approval_state"] == "PENDING_APPROVAL"

    def test_e007_careers_missing_attachment_warning(self, pipeline_run_data):
        item = next(it for it in pipeline_run_data["items"] if it["email_id"] == "E007")
        assert item["classification"]["category"] == BusinessCategory.CAREERS_APPLICATION
        assert any("internship" in u.lower() or "candidate" in u.lower() for u in item["uncertainties"])
        assert "Zidane Mouldino" in item["assigned_staff_summary"]
        assert item["approval_state"] == "PENDING_APPROVAL"

    def test_e008_subcontractor_operations(self, pipeline_run_data):
        item = next(it for it in pipeline_run_data["items"] if it["email_id"] == "E008")
        assert item["classification"]["category"] == BusinessCategory.SUBCONTRACTOR_OPERATIONS
        assert "Ties Rahardjo" in item["assigned_staff_summary"]
        assert "Ballarat" in item["extracted_fields"]["locations"]
        assert any("tuesday" in d.lower() for d in item["extracted_fields"]["deadlines"])
        assert item["crm_match"]["matched_crm_id"] == "C005"
        assert item["approval_state"] == "PENDING_APPROVAL"

    def test_e009_commercial_solar_lead(self, pipeline_run_data):
        item = next(it for it in pipeline_run_data["items"] if it["email_id"] == "E009")
        assert item["classification"]["category"] == BusinessCategory.COMMERCIAL_SOLAR_LEAD
        assert "Matt Cooper" in item["assigned_staff_summary"]
        assert item["extracted_fields"]["monthly_spend_usd"] == 80000
        assert item["approval_state"] == "PENDING_APPROVAL"

    def test_e010_contact_update_related_to_e009(self, pipeline_run_data):
        item = next(it for it in pipeline_run_data["items"] if it["email_id"] == "E010")
        assert item["classification"]["category"] == BusinessCategory.CONTACT_DETAILS_UPDATE
        assert item["action_type"] == ActionType.CRM_UPDATE
        assert item["duplicate_relation"]["decision"] == SubmissionRelationship.PROBABLE_RELATED_SUBMISSION
        assert item["duplicate_relation"]["related_to_item_id"] == "E009"
        assert "Ali Pratama" in item["assigned_staff_summary"]
        assert item["extracted_fields"]["phone"] == "0411 999 102"
        assert item["approval_state"] == "PENDING_APPROVAL"

    def test_e011_internal_system_alert(self, pipeline_run_data):
        item = next(it for it in pipeline_run_data["items"] if it["email_id"] == "E011")
        assert item["classification"]["category"] == BusinessCategory.INTERNAL_SYSTEM_ALERT
        assert item["priority"] == "CRITICAL"
        assert item["action_type"] == ActionType.INTERNAL_REMEDIATION
        assert "Ali Pratama" in item["assigned_staff_summary"]
        assert "NO EXTERNAL DRAFT" in item["draft_preview"]
        assert item["approval_state"] == "PENDING_APPROVAL"

    def test_e012_small_commercial_leasehold(self, pipeline_run_data):
        item = next(it for it in pipeline_run_data["items"] if it["email_id"] == "E012")
        assert item["classification"]["category"] == BusinessCategory.SMALL_COMMERCIAL_LEASEHOLD
        assert "landlord_roof_consent" in item["extracted_fields"]["missing_prerequisites"]
        assert any("landlord" in u.lower() or "lease" in u.lower() for u in item["uncertainties"])
        assert "Zidane Mouldino" in item["assigned_staff_summary"]
        assert "landlord" in item["draft_text"].lower()
        assert item["approval_state"] == "PENDING_APPROVAL"


# ==============================================================================
# 2. INVARIANT TESTS
# ==============================================================================

def test_pipeline_invariants():
    data = run_pipeline()
    for item in data["items"]:
        # Every email produces non-null core metadata
        assert item["classification"]["category"] is not None
        assert item["assigned_staff_summary"] is not None
        assert item["priority"] in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
        assert item["recommended_action"].startswith("RECOMMENDATION:")
        assert item["audit_correlation_id"] is not None

        # Human approval requirements
        if item["requires_human_approval"]:
            assert item["approval_state"] in ("PENDING_APPROVAL", "MOCK_DISPATCHED")
        else:
            assert item["approval_state"] == "AUTO_ARCHIVED"


# ==============================================================================
# 3. GENERALIZATION / ANTI-OVERFITTING TESTS (3 Unseen Items)
# ==============================================================================

def test_generalization_industrial_lead():
    """Unseen commercial customer with GWh, multiple sites, and large spend."""
    raw = {
        "id": "SYNTH_01",
        "sender_name": "Elena Rostova",
        "sender_email": "elena@apexmanufacturing.example",
        "subject": "Commercial solar for Newcastle facility",
        "body": (
            "We operate a high-energy facility in Newcastle consuming 3.8 GWh per year. "
            "Our power bills average $65,000 a month. Please let us know feasibility next week."
        ),
    }
    extracted = extract_from_inbound_item(raw)
    assert extracted.annual_consumption_gwh.value == 3.8
    assert extracted.monthly_spend_usd.value == 65000
    assert any(loc.value == "Newcastle" for loc in extracted.locations)

    classification = classify_inbound_item(raw, extracted)
    assert classification.category in (
        BusinessCategory.COMMERCIAL_SOLAR_LEAD,
        BusinessCategory.COMMERCIAL_SOLAR_MULTI_SITE,
    )

    staff = load_staff_directory()
    routing = route_inbound_inquiry(classification, extracted, None, staff)
    assert any(o.name == "Matt Cooper" for o in routing.assigned_owners)
    assert routing.requires_human_approval is True


def test_generalization_subcontractor_operations():
    """Unseen subcontractor coordinating Sydney installation crew."""
    raw = {
        "id": "SYNTH_02",
        "sender_name": "Dave Miller",
        "sender_email": "dave@contractorcrew.example",
        "subject": "Crew availability for Sydney commercial install",
        "body": "Can you confirm crew availability? We have a 6 person installation crew on hold before Tuesday.",
    }
    extracted = extract_from_inbound_item(raw)
    classification = classify_inbound_item(raw, extracted)
    assert classification.category == BusinessCategory.SUBCONTRACTOR_OPERATIONS

    staff = load_staff_directory()
    routing = route_inbound_inquiry(classification, extracted, None, staff)
    assert any(o.name == "Ties Rahardjo" for o in routing.assigned_owners)
    assert routing.action_type == ActionType.EXTERNAL_REPLY_DRAFT


def test_generalization_invoice_dispute():
    """Unseen customer flagging billing variance against PO."""
    raw = {
        "id": "SYNTH_03",
        "sender_name": "Karen Patel",
        "sender_email": "karen@pacificlogistics.example",
        "subject": "Invoice 4921 does not match purchase order",
        "body": (
            "Invoice 4921 is $4,500 higher than approved PO PO 9901. "
            "We require reconciliation before payment before Friday."
        ),
    }
    extracted = extract_from_inbound_item(raw)
    assert extracted.discrepancy_amount_usd.value == 4500
    assert any(inv.value == "4921" for inv in extracted.invoice_numbers)
    assert any("9901" in po.value for po in extracted.po_numbers)

    classification = classify_inbound_item(raw, extracted)
    assert classification.category == BusinessCategory.BILLING_INVOICE_DISPUTE

    staff = load_staff_directory()
    routing = route_inbound_inquiry(classification, extracted, None, staff)
    assert routing.action_type == ActionType.PAYMENT_HOLD
    assert any(o.name == "Ali Pratama" for o in routing.assigned_owners)


# ==============================================================================
# 4. APPROVAL GATE & TAMPERING TESTS
# ==============================================================================

def test_approval_and_mock_dispatch_gate(tmp_path: Path):
    """Prove end-to-end local mock approval, payload hash binding, and replay rejection."""
    sink = AuditSink(tmp_path / "test_approval_audit.jsonl")

    decision = RoutingDecision(
        event_id=uuid4(),
        triage_id=uuid4(),
        idempotency_key="unique_dispatch_key_101",
        action=RoutingAction.ESCALATE_TO_HUMAN_SALES,
        target_queue="sales_queue",
        requires_human_approval=True,
        reason_code=ReasonCode.ENTERPRISE_SALES_QUALIFIED,
        reason_detail="Founder approved high-value enterprise lead",
    )

    draft = "Dear Amelia, thank you for reaching out. Let us schedule a discovery call."
    payload_hash = hashlib.sha256(draft.encode()).hexdigest()
    recipient = "amelia@humelogistics.example"

    # Issue verified command
    command = approve_and_send(
        decision=decision,
        approved_draft=draft,
        recipient_email=recipient,
        approver_identity="Matt Cooper <matt@wearebeda.com>",
        expected_payload_hash=payload_hash,
    )

    # 1. Successful Dispatch
    res = mock_dispatch(command, audit_sink=sink)
    assert res.success is True

    # 2. Replay rejection on same command
    res_replay = mock_dispatch(command, audit_sink=sink)
    assert res_replay.success is False
    assert "replayed" in res_replay.detail.lower()

    # 3. Payload mutation detection
    command_tampered = command.model_copy(update={"payload_hash": "tampered_hash_value"})
    with pytest.raises(ApprovalVerificationError, match="Signature mismatch"):
        verify_approval(command_tampered)


# ==============================================================================
# 5. AUDIT LOG TAMPERING & CHAIN VERIFICATION
# ==============================================================================

def test_audit_log_detects_tampering(tmp_path: Path):
    audit_path = tmp_path / "audit_chain.jsonl"
    sink = AuditSink(audit_path)

    sink.log(AuditEvent(
        event_type=AuditEventType.ENVELOPE_RECEIVED,
        correlation_id="corr-1",
        actor="ingress",
        payload_hash="hash1",
    ))
    sink.log(AuditEvent(
        event_type=AuditEventType.POLICY_DECISION,
        correlation_id="corr-1",
        actor="router",
        payload_hash="hash2",
    ))

    # Verify intact chain
    valid, count, error = sink.verify_chain()
    assert valid is True
    assert count == 2
    assert not error

    # Corrupt a line in the middle
    lines = audit_path.read_text(encoding="utf-8").strip().split("\n")
    corrupted = lines[0].replace("hash1", "tampered_hash")
    lines[0] = corrupted
    audit_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    sink2 = AuditSink(audit_path)
    valid2, _line, error2 = sink2.verify_chain()
    assert valid2 is False
    assert "mismatch" in error2
