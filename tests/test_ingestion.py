"""
Unit tests for data ingestion layer.

Tests:
1. Successful loading of emails, CRM records, staff directory, and attachments.
2. Handling of missing attachment reference (records warning, does not crash).
3. Rejection of malformed JSON / missing required fields.
4. Deterministic content hashing and idempotency key derivation.
5. Attachment text linkage to combined_text property.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from beda_orchestrator.ingestion import (
    build_inbound_item,
    load_attachments,
    load_crm_records,
    load_emails,
    load_staff_directory,
)


def test_load_attachments(tmp_path: Path):
    att_dir = tmp_path / "attachments"
    att_dir.mkdir()
    (att_dir / "sample1.txt").write_text("Customer: Acme\nBill: $100", encoding="utf-8")
    (att_dir / "sample2.txt").write_text("Site notes: 50 fittings", encoding="utf-8")

    atts = load_attachments(att_dir)
    assert len(atts) == 2
    assert "Customer: Acme" in atts["sample1.txt"]
    assert "Site notes" in atts["sample2.txt"]


def test_load_staff_directory():
    staff = load_staff_directory()
    assert len(staff) == 4
    names = [s.name for s in staff]
    assert "Matt Cooper" in names
    assert "Ties Rahardjo" in names
    assert "Zidane Mouldino" in names
    assert "Ali Pratama" in names


def test_load_crm_records():
    crm = load_crm_records()
    assert len(crm) == 5
    ids = [c.id for c in crm]
    assert "C001" in ids
    assert "C005" in ids


def test_load_emails_and_attachments():
    items = load_emails()
    assert len(items) == 12
    # Verify E001 has attached Truganina bill
    e001 = next(item for item in items if item.id == "E001")
    assert len(e001.attachments) == 1
    assert e001.attachments[0].filename == "01_hume_energy_bill.txt"
    assert e001.attachments[0].is_loaded is True
    assert "68,420 kWh" in e001.attachments[0].content
    assert "--- Attachment: 01_hume_energy_bill.txt ---" in e001.combined_text

    # Verify E007 missing attachment warning
    e007 = next(item for item in items if item.id == "E007")
    assert len(e007.attachments) == 1
    assert e007.attachments[0].is_loaded is False
    assert len(e007.warnings) == 1
    assert "portfolio.pdf" in e007.warnings[0]


def test_deterministic_reloading():
    items1 = load_emails()
    items2 = load_emails()
    for it1, it2 in zip(items1, items2, strict=True):
        assert it1.content_hash == it2.content_hash
        assert it1.idempotency_key == it2.idempotency_key


def test_build_inbound_item_missing_required_field():
    raw = {
        "id": "E999",
        "sender_email": "test@example.com",
        "sender_name": "Test",
        # Missing subject and body
    }
    with pytest.raises(ValueError, match="Missing required field"):
        build_inbound_item(raw)


def test_build_inbound_item_invalid_email():
    raw = {
        "id": "E999",
        "sender_email": "not-a-valid-email",
        "sender_name": "Test",
        "subject": "Hello",
        "body": "World",
    }
    with pytest.raises(ValidationError):
        build_inbound_item(raw)


def test_malformed_json_handling(tmp_path: Path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{not valid json}", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_emails(emails_file=bad_file)
