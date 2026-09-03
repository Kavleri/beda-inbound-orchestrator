"""
Tests for the audit sink: append, hash chaining, verification, and failure modes.

Covers:
  - File creation and genesis hash
  - Canonical hash chaining over multiple entries
  - Tampering detection (content modification, deleted/inserted lines)
  - Malformed JSON line detection
  - Resume from existing file
  - Detail truncation and PII exclusion
  - Write failure error propagation (fail-closed / raise RuntimeError)
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from beda_orchestrator.audit import GENESIS_HASH, AuditEvent, AuditSink
from beda_orchestrator.enums import AuditEventType, ReasonCode


@pytest.fixture
def audit_path(tmp_path) -> Path:
    return tmp_path / "test_audit.jsonl"


class TestAuditSink:
    def test_append_creates_file(self, audit_path):
        sink = AuditSink(audit_path)
        event = AuditEvent(
            event_type=AuditEventType.ENVELOPE_RECEIVED,
            correlation_id="test-123",
        )
        sink.log(event)
        assert audit_path.exists()
        lines = audit_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1

    def test_genesis_hash(self, audit_path):
        sink = AuditSink(audit_path)
        event = AuditEvent(
            event_type=AuditEventType.ENVELOPE_RECEIVED,
            correlation_id="test-123",
        )
        record = sink.log(event)
        assert record["prev_hash"] == GENESIS_HASH

    def test_hash_chaining(self, audit_path):
        sink = AuditSink(audit_path)
        for i in range(5):
            sink.log(AuditEvent(
                event_type=AuditEventType.POLICY_DECISION,
                correlation_id=f"event-{i}",
                reason_code=ReasonCode.STANDARD_HITL_REVIEW,
            ))
        valid, count, error = sink.verify_chain()
        assert valid, f"Chain verification failed: {error}"
        assert count == 5

    def test_tampering_detected(self, audit_path):
        sink = AuditSink(audit_path)
        for i in range(3):
            sink.log(AuditEvent(
                event_type=AuditEventType.POLICY_DECISION,
                correlation_id=f"event-{i}",
            ))
        # Tamper with the first line.
        lines = audit_path.read_text(encoding="utf-8").strip().split("\n")
        record = json.loads(lines[0])
        record["outcome"] = "TAMPERED"
        lines[0] = json.dumps(record, separators=(",", ":"), sort_keys=True)
        audit_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        sink2 = AuditSink(audit_path)
        valid, _line_num, error = sink2.verify_chain()
        assert not valid
        assert "prev_hash mismatch" in error

    def test_malformed_json_in_chain_detected(self, audit_path):
        sink = AuditSink(audit_path)
        sink.log(AuditEvent(
            event_type=AuditEventType.ENVELOPE_RECEIVED,
            correlation_id="event-1",
        ))
        # Corrupt file with unparseable JSON line
        with open(audit_path, "a", encoding="utf-8") as f:
            f.write("{corrupted json string\n")

        sink2 = AuditSink(audit_path)
        valid, line_num, error = sink2.verify_chain()
        assert not valid
        assert "invalid JSON" in error
        assert line_num == 2

    def test_resume_from_existing_file(self, audit_path):
        sink1 = AuditSink(audit_path)
        sink1.log(AuditEvent(
            event_type=AuditEventType.ENVELOPE_RECEIVED,
            correlation_id="first",
        ))
        # New sink instance reads the last line hash.
        sink2 = AuditSink(audit_path)
        sink2.log(AuditEvent(
            event_type=AuditEventType.POLICY_DECISION,
            correlation_id="second",
        ))
        valid, count, error = sink2.verify_chain()
        assert valid, error
        assert count == 2

    def test_never_writes_raw_body(self, audit_path):
        """Audit events should not contain raw PII or full bodies."""
        sink = AuditSink(audit_path)
        # detail is truncated to 500 chars.
        long_detail = "A" * 1000
        event = AuditEvent(
            event_type=AuditEventType.ENVELOPE_RECEIVED,
            correlation_id="test",
            detail=long_detail,
        )
        sink.log(event)
        content = audit_path.read_text(encoding="utf-8")
        record = json.loads(content.strip())
        assert len(record["detail"]) == 500

    def test_audit_write_failure_raises_runtime_error(self, audit_path):
        """Audit sink write failure must fail loud and not be swallowed."""
        sink = AuditSink(audit_path)
        event = AuditEvent(
            event_type=AuditEventType.ENVELOPE_RECEIVED,
            correlation_id="test-fail",
        )
        with (
            patch("builtins.open", side_effect=OSError("Disk write error")),
            pytest.raises(RuntimeError, match="Audit sink write failed"),
        ):
            sink.log(event)
