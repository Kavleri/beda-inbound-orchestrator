"""
Automated unit and regression tests for Test 2 components.

Tests:
1. Fuzzy matching & CRM resolution
2. Entity extraction & uncertainty preservation
3. Business classification across 12 items
4. End-to-end pipeline execution and audit integrity
"""

import pytest
from pathlib import Path
from beda_orchestrator.classifier import classify_inquiry
from beda_orchestrator.extractor import extract_structured_info
from beda_orchestrator.matcher import compute_token_similarity, find_crm_match
from beda_orchestrator.pipeline import run_pipeline


def test_fuzzy_matcher_hume_logistics():
    """Hume Logistic without 's' should match Hume Logistics Pty Ltd."""
    sim = compute_token_similarity("Hume Logistic", "Hume Logistics Pty Ltd")
    assert sim >= 0.5, f"Similarity {sim} expected to be >= 0.5"


def test_crm_fuzzy_match():
    crm_records = [
        {"id": "C001", "company": "Hume Logistics Pty Ltd", "email": "amelia.grant@humelogistics.example"}
    ]
    # Sender with slightly different company and different email
    match = find_crm_match("Hume Logistic", "different.email@domain.com", crm_records)
    assert match is not None
    assert match["record"]["id"] == "C001"
    assert match["match_type"] == "fuzzy_company"


def test_extractor_preserves_uncertainty_northbank():
    item = {
        "subject": "Government school lighting upgrade",
        "body": "I manage facilities at Northbank College. I do not have our latest electricity bill with me.",
        "sender_name": "Melissa Tran",
        "sender_email": "melissa.tran@northbankcollege.example",
    }
    extracted = extract_structured_info(item)
    assert "electricity_bill" in extracted["missing_critical_fields"]
    assert any("electricity bill" in u.lower() for u in extracted["uncertainties"])


def test_extractor_discrepancy_amount():
    item = {
        "subject": "Invoice 1847 does not match PO",
        "body": "invoice 1847 is $2,640 higher than the purchase order.",
        "sender_name": "Rohan Lee",
        "sender_email": "rohan@greenfieldsfoods.example",
    }
    extracted = extract_structured_info(item)
    assert extracted["discrepancy_amount_usd"] == 2640


def test_classifier_system_alert():
    item = {
        "subject": "CRM sync failed overnight",
        "body": "HubSpot sync job failed at 02:14. Error: OAuth token expired.",
        "sender_email": "alerts@beda.example",
    }
    extracted = extract_structured_info(item)
    classification = classify_inquiry(item, extracted)
    assert classification == "INTERNAL_SYSTEM_ALERT"


def test_classifier_spam():
    item = {
        "subject": "Buy 50,000 Australian CEO leads today",
        "body": "Special price expires in 24 hours. Reply now for cryptocurrency payment instructions.",
        "sender_email": "sales@megaleadlists.example",
    }
    extracted = extract_structured_info(item)
    classification = classify_inquiry(item, extracted)
    assert classification == "SPAM_SOLICITATION"


def test_pipeline_execution():
    res = run_pipeline()
    assert res["processed_count"] == 12
    assert res["audit_valid"] is True
