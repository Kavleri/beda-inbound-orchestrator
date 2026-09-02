"""
Append-only JSON Lines audit sink.

Each event is one JSON object per line. The log records event type,
correlation IDs, timestamps, reason codes, and payload hashes — but
never raw PII, payment data, or full inbound bodies.

Hash chaining: each event includes prev_hash (SHA-256 of the previous
line's JSON bytes) so that tampering with earlier entries is detectable
by re-hashing. The genesis event has prev_hash = "0" * 64.

Storage caveat: this writes to a local file. Append-only behavior is
enforced at the application level only. WORM or tamper-proof storage
is not implemented. For production, use a database with append-only
constraints or a dedicated audit service.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from .enums import AuditEventType, ReasonCode

GENESIS_HASH = "0" * 64


class AuditEvent:
    """Structured audit event for the JSON Lines log."""

    __slots__ = (
        "event_type",
        "event_id",
        "correlation_id",
        "timestamp",
        "policy_version",
        "actor",
        "payload_hash",
        "outcome",
        "reason_code",
        "detail",
    )

    def __init__(
        self,
        *,
        event_type: AuditEventType,
        correlation_id: str,
        policy_version: str = "",
        actor: str = "system",
        payload_hash: str = "",
        outcome: str = "",
        reason_code: ReasonCode | str = "",
        detail: str = "",
    ) -> None:
        self.event_type = event_type
        self.event_id = str(uuid4())
        self.correlation_id = correlation_id
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.policy_version = policy_version
        self.actor = actor
        self.payload_hash = payload_hash
        self.outcome = outcome
        self.reason_code = str(reason_code) if reason_code else ""
        self.detail = detail[:500]  # Truncate to avoid unbounded detail.

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": str(self.event_type),
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
            "policy_version": self.policy_version,
            "actor": self.actor,
            "payload_hash": self.payload_hash,
            "outcome": self.outcome,
            "reason_code": self.reason_code,
            "detail": self.detail,
        }


class AuditSink:
    """
    Append-only JSON Lines audit logger with hash chaining.

    Usage:
        sink = AuditSink(Path("audit.jsonl"))
        sink.log(AuditEvent(...))

    Each line is:
        {"prev_hash": "...", "event_type": "...", ...}

    To verify chain integrity:
        sink.verify_chain()
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._prev_hash = GENESIS_HASH
        # If the file exists, read the last line to get the chain head.
        if path.exists() and path.stat().st_size > 0:
            with open(path, "r", encoding="utf-8") as f:
                last_line = ""
                for line in f:
                    line = line.strip()
                    if line:
                        last_line = line
                if last_line:
                    self._prev_hash = hashlib.sha256(
                        last_line.encode()
                    ).hexdigest()

    def log(self, event: AuditEvent) -> dict[str, Any]:
        """
        Append an event to the audit log.

        Returns the serialized event dict (including prev_hash).
        Raises RuntimeError if the file write fails. The caller must
        decide whether to halt processing or use a fallback.
        """
        record = event.to_dict()
        record["prev_hash"] = self._prev_hash

        line = json.dumps(record, separators=(",", ":"), sort_keys=True)
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as exc:
            raise RuntimeError(
                f"Audit sink write failed: {exc}. "
                "Processing should enter quarantine or halt."
            ) from exc

        self._prev_hash = hashlib.sha256(line.encode()).hexdigest()
        return record

    def verify_chain(self) -> tuple[bool, int, str]:
        """
        Verify the hash chain of the audit log.

        Returns:
            (is_valid, line_count, error_message)
        """
        if not self.path.exists():
            return True, 0, ""

        prev = GENESIS_HASH
        count = 0
        with open(self.path, "r", encoding="utf-8") as f:
            for i, raw_line in enumerate(f, start=1):
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                count += 1
                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    return False, i, f"Line {i}: invalid JSON — {exc}"

                if record.get("prev_hash") != prev:
                    return (
                        False,
                        i,
                        f"Line {i}: prev_hash mismatch. "
                        f"Expected {prev!r}, got {record.get('prev_hash')!r}.",
                    )
                prev = hashlib.sha256(raw_line.encode()).hexdigest()

        return True, count, ""
