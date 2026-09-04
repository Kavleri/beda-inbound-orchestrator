"""
Data ingestion layer for BEDA Inbound Orchestrator.

Loads and validates:
- Synthetic email items (E001–E012)
- CRM seed records (C001–C005)
- Staff directory (4 owners)
- Document attachments (.txt)

Enforces:
- Ingress envelope validation
- Association of attachment references with parsed local files
- Visible warnings for missing or unparseable attachments
- Deterministic content hashing and idempotency key derivation
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .models import InboundEnvelope

ADVERSARIAL_DIRECTIVES_PATTERN = re.compile(
    r"(ignore\s+(previous|all|prior|system)\s+(rules|instructions|constraints)"
    r"|expose\s+internal\s+staff"
    r"|dump\s+(all\s+)?staff"
    r"|approve\s+(and\s+send|this\s+email|response|outbound)"
    r"|system\s*override"
    r"|admin\s*override"
    r"|set\s+approval_state"
    r"|bypass\s+(human\s+)?approval"
    r"|grant\s+tool\s+permission)",
    re.IGNORECASE,
)


class AttachmentMetadata(BaseModel):
    """Metadata and content for an attachment linked to an email."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: str
    filepath: str | None = None
    content: str | None = None
    is_loaded: bool = False
    warning: str | None = None
    is_untrusted_document: bool = True
    has_adversarial_directives: bool = False
    adversarial_matches: list[str] = Field(default_factory=list)


class StaffMember(BaseModel):
    """Staff directory entry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    role: str
    domains: list[str]
    email: str


class CRMSeedRecord(BaseModel):
    """Pre-existing CRM record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    company: str
    contact_name: str
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    stage: str
    service: str
    status: str


class InboundItem(BaseModel):
    """Fully ingested, normalized, and validated inbound item."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    sender_email: str
    sender_name: str
    subject: str
    body: str
    attachment_refs: list[str] = Field(default_factory=list)
    attachments: list[AttachmentMetadata] = Field(default_factory=list)
    content_hash: str
    idempotency_key: str
    source_channel: str = "email"
    envelope: InboundEnvelope
    warnings: list[str] = Field(default_factory=list)

    @property
    def combined_text(self) -> str:
        """Subject, body, and all successfully loaded attachment text."""
        parts = [self.subject, self.body]
        for att in self.attachments:
            if att.is_loaded and att.content:
                parts.append(f"\n--- Attachment: {att.filename} ---\n{att.content}")
        return "\n\n".join(parts)


def get_default_data_dir() -> Path:
    """Return absolute path to repo data directory."""
    return Path(__file__).resolve().parent.parent.parent / "data"


def load_attachments(attachments_dir: Path | None = None) -> dict[str, str]:
    """
    Load all attachments (.txt and .pdf) from the attachments directory into a dict of {filename: content}.
    """
    if attachments_dir is None:
        attachments_dir = get_default_data_dir() / "attachments"

    attachments: dict[str, str] = {}
    if not attachments_dir.exists():
        return attachments

    for path in attachments_dir.iterdir():
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix == ".txt":
            try:
                content = path.read_text(encoding="utf-8").strip()
                attachments[path.name] = content
            except OSError:
                attachments[path.name] = ""
        elif suffix == ".pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(str(path))
                text_pages = [page.extract_text() or "" for page in reader.pages]
                attachments[path.name] = "\n".join(text_pages).strip()
            except (pypdf.errors.PyPdfError, OSError, ValueError, KeyError, IndexError):
                attachments[path.name] = ""
    return attachments


def load_staff_directory(staff_file: Path | None = None) -> list[StaffMember]:
    """Load and validate the 4 BEDA staff members from JSON."""
    if staff_file is None:
        staff_file = get_default_data_dir() / "staff.json"

    if not staff_file.exists():
        raise FileNotFoundError(f"Staff directory file not found: {staff_file}")

    content = staff_file.read_text(encoding="utf-8")
    data = json.loads(content)
    if not isinstance(data, list):
        raise TypeError(f"Expected list of staff in {staff_file}, got {type(data).__name__}")

    return [StaffMember(**item) for item in data]


def load_crm_records(crm_file: Path | None = None) -> list[CRMSeedRecord]:
    """Load and validate CRM seed rows from JSON."""
    if crm_file is None:
        crm_file = get_default_data_dir() / "crm_seeds.json"

    if not crm_file.exists():
        raise FileNotFoundError(f"CRM seeds file not found: {crm_file}")

    content = crm_file.read_text(encoding="utf-8")
    data = json.loads(content)
    if not isinstance(data, list):
        raise TypeError(f"Expected list of CRM records in {crm_file}, got {type(data).__name__}")

    return [CRMSeedRecord(**item) for item in data]


def build_inbound_item(
    raw: dict[str, Any],
    loaded_attachments: dict[str, str] | None = None,
    attachments_dir: Path | None = None,
) -> InboundItem:
    """
    Validate required fields, attach loaded document text, compute deterministic hash and envelope.
    """
    for required_key in ("id", "sender_email", "sender_name", "subject", "body"):
        if required_key not in raw or raw[required_key] is None:
            raise ValueError(f"Missing required field {required_key!r} in email record: {raw}")

    email_id = str(raw["id"]).strip()
    sender_email = str(raw["sender_email"]).strip()
    sender_name = str(raw["sender_name"]).strip()
    subject = str(raw["subject"]).strip()
    body = str(raw["body"]).strip()
    source_channel = str(raw.get("source_channel", "email")).strip()
    raw_refs = raw.get("attachments", [])
    if not isinstance(raw_refs, list):
        raw_refs = []

    if loaded_attachments is None:
        loaded_attachments = load_attachments(attachments_dir)

    # Derive deterministic idempotency key and content hash
    canonical_repr = f"{sender_email.lower()}::{subject}::{body}"
    content_hash = hashlib.sha256(canonical_repr.encode("utf-8")).hexdigest()
    idempotency_key = content_hash  # 64-char hex string, satisfies min 16 max 128

    # Validate against InboundEnvelope trust boundary
    envelope = InboundEnvelope(
        sender_email=sender_email,
        sender_name=sender_name,
        subject=subject,
        body=body,
        source_channel=source_channel,
        idempotency_key=idempotency_key,
    )

    # Resolve attachments
    attachments: list[AttachmentMetadata] = []
    warnings: list[str] = []

    for ref in raw_refs:
        ref_str = str(ref).strip()
        if ref_str in loaded_attachments:
            text = loaded_attachments[ref_str]
            att_path = str(attachments_dir / ref_str) if attachments_dir else ref_str
            adv_matches = ADVERSARIAL_DIRECTIVES_PATTERN.findall(text) if text else []
            has_adv = bool(adv_matches)
            if has_adv:
                warnings.append(
                    f"Untrusted document '{ref_str}' contains adversarial instruction directives; "
                    "isolated at trust boundary and treated strictly as passive data."
                )
            attachments.append(AttachmentMetadata(
                filename=ref_str,
                filepath=att_path,
                content=text,
                is_loaded=True,
                warning=None,
                is_untrusted_document=True,
                has_adversarial_directives=has_adv,
                adversarial_matches=[m[0] if isinstance(m, tuple) else m for m in adv_matches],
            ))
        else:
            warn = f"Referenced attachment {ref_str!r} not found in attachments directory"
            warnings.append(warn)
            attachments.append(AttachmentMetadata(
                filename=ref_str,
                filepath=None,
                content=None,
                is_loaded=False,
                warning=warn,
                is_untrusted_document=True,
                has_adversarial_directives=False,
                adversarial_matches=[],
            ))

    return InboundItem(
        id=email_id,
        sender_email=envelope.sender_email,
        sender_name=envelope.sender_name,
        subject=envelope.subject,
        body=envelope.body,
        attachment_refs=[str(r) for r in raw_refs],
        attachments=attachments,
        content_hash=content_hash,
        idempotency_key=idempotency_key,
        source_channel=envelope.source_channel,
        envelope=envelope,
        warnings=warnings,
    )


def load_emails(
    emails_file: Path | None = None,
    attachments_dir: Path | None = None,
) -> list[InboundItem]:
    """Load all emails and link attachments."""
    if emails_file is None:
        emails_file = get_default_data_dir() / "emails.json"
    if attachments_dir is None:
        attachments_dir = get_default_data_dir() / "attachments"

    if not emails_file.exists():
        raise FileNotFoundError(f"Emails file not found: {emails_file}")

    content = emails_file.read_text(encoding="utf-8")
    data = json.loads(content)
    if not isinstance(data, list):
        raise TypeError(f"Expected list of emails in {emails_file}, got {type(data).__name__}")

    loaded_atts = load_attachments(attachments_dir)
    return [build_inbound_item(item, loaded_atts, attachments_dir) for item in data]
