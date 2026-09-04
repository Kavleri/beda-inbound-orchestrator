# BEDA Inbound Inquiry Router & Orchestrator

A dependency-light reference implementation of an inbound business inquiry router with deterministic policy evaluation, cryptographic human approval enforcement, and verifiable audit logging. Evaluated against 12 synthetic inbound items, 5 CRM seed records, 4 staff ownership domains, and document attachments. Runs completely offline without external network or paid API services. **109 passing tests.**

```bash
git clone https://github.com/Kavleri/beda-inbound-orchestrator.git
cd beda-inbound-orchestrator
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
export BEDA_APPROVAL_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"

# Run test suite and lint checks
pytest -q              # 109 passed in ~2.5s
ruff check .           # All checks passed!

# Run synthetic data pack pipeline (Test 2)
python3 -m beda_orchestrator.pipeline

# Optional: Run interactive operator console
python3 -m beda_orchestrator.app
```

---

## Deliverables & Truthful Disclosures

- **Runnable repository:** Fully functional, locally executable Python 3.12+ package.
- **Inspectable outputs:** Generates `test2_results.json`, `test2_report.html`, and cryptographically chained `test2_audit.jsonl`.
- **Test matrix:** 113 passing unit, regression, invariant, adversarial attachment, and tampering tests.
- **Recording status:** **Recording is explicitly OUT OF SCOPE for this task.** No screen recording, video file, or animated demonstration was generated or claimed.

---

## Submission: Challenge Response

The following sections directly address the eight submission prompts.

### 1. Architecture: Main Components and Data Flow

The system enforces a strict pipeline of trust with four domain boundaries. Each boundary is a separate Pydantic model; untrusted parser output cannot bypass policy or mutate downstream state.

```
  Ingress Validation        Untrusted Extraction       Deterministic Policy         Human Approval Gate
 ┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
 │   InboundEnvelope    │  │ InboundTriageResult  │  │   RoutingDecision    │  │   ApprovalCommand    │
 │                      │  │                      │  │                      │  │                      │
 │ • sender_email       │─>│ • intent             │─>│ • action             │─>│ • payload_hash       │
 │ • subject, body      │  │ • confidence_score   │  │ • reason_code        │  │ • recipient_hash     │
 │ • source_channel     │  │ • extracted_budget   │  │ • requires_approval  │  │ • nonce (single-use) │
 │ • idempotency_key    │  │ • draft_response     │  │ • policy_version     │  │ • HMAC signature     │
 └──────────────────────┘  └──────────────────────┘  └──────────────────────┘  └──────────┬───────────┘
                                                                                          │
                                                                               ┌──────────▼───────────┐
                                                                               │   Mock Dispatcher    │
                                                                               │ (accepts only signed │
                                                                               │   ApprovalCommand)   │
                                                                               └──────────┬───────────┘
                                                                                          │
                                                                               ┌──────────▼───────────┐
                                                                               │   Audit Sink         │
                                                                               │ (append-only JSONL   │
                                                                               │  + SHA-256 chaining) │
                                                                               └──────────────────────┘
```

**Data flow:**
1. `InboundEnvelope`: Enforces syntactic boundaries (email format normalization, channel enum, timezone-aware UTC received timestamp, deterministic payload hashing).
2. `StructuredExtraction`: Reusable rule-based parsing extracts business entities, locations, financial figures, and deadlines while preserving source provenance (`email_body`, `subject`, `attachment`, `sender`) and explicit uncertainty lists.
3. `classify_inbound_item`: Natural language pattern and evidence scoring categorize items into explicit enums (`commercial_solar_multi_site`, `billing_invoice_dispute`, etc.).
4. `check_inbound_relationship` & `find_crm_match`: Separates duplicate detection from CRM record matching (exact email, normalized phone, stemmed company similarity).
5. `route_inbound_inquiry`: Dynamically queries `data/staff.json` by ownership domains to assign staff owners and determine recommended actions.
6. `generate_draft_response`: Composes entity-grounded draft suggestions without hallucinating absent facts or completed actions.
7. `approve_and_send` & `mock_dispatch`: Cryptographic gate requiring an authenticated HMAC-SHA256 signature bound to the draft hash and single-use nonce before any outbound delivery can occur.
8. `AuditSink`: Records SHA-256 chained events to `test2_audit.jsonl` where every event verifies the hash of the preceding line.

Mermaid diagrams: [`docs/architecture-local.mmd`](docs/architecture-local.mmd) (implemented), [`docs/architecture-target.mmd`](docs/architecture-target.mmd) (design-only adapters), [`docs/failure-paths.mmd`](docs/failure-paths.mmd) (failure decision tree).

#### Adversarial Document & Attachment Trust Boundary

Attachments (`.pdf` and `.txt`) are strictly treated as **untrusted data plane content**, never as instruction-bearing control signals:
- **Policy Invariance:** Directives attempting system overrides, prompt injection, or forced approval (`approval_state=APPROVED`, `bypass human approval`) are detected at ingress, flagged in uncertainties, and routed to `ActionType.QUARANTINE`. The requirement for human approval (`requires_human_approval = True`) is an immutable security invariant that cannot be altered or relaxed by document text.
- **Data Disclosure Prevention:** Even if document text commands the system to exfiltrate internal staff directory records or credentials, the drafter operates strictly on grounded templates and suppresses outbound drafts for quarantined items, guaranteeing zero leakage of private staff emails or roles.
- **Tool Permission & Execution Invariance:** Outbound tools and dispatch adapters accept only verified `ApprovalCommand` objects bearing valid HMAC-SHA256 signatures generated by the operator's secret key. Quarantined items are classified as `INELIGIBLE_ACTIONS` and rejected from approval creation, guaranteeing zero unapproved outbound actions.

### 2. Model and Tool Choices

| Choice | What | Why |
|---|---|---|
| **Language** | Python 3.12+ | Fastest path to a working reference implementation with strong typing (`from __future__ import annotations`, union types). Zero compiled C extensions needed. |
| **Validation** | Pydantic v2 | `extra="forbid"` rejects unexpected fields from untrusted parsers. `frozen=True` prevents post-creation mutation. Enforces timezone-aware UTC timestamps. |
| **Parsing & Classification** | Regex, token stemming, and heuristics | Pure deterministic logic running locally. Eliminates external API dependencies, recurring token costs, and rate limits. Guarantees 100% reproducible sub-second test runs. |
| **Policy Engine** | Pure Python function | Pure function with no I/O, network, or clock calls. Deterministic precedence table recomputes tier from budget and enforces strict security gates. |
| **Approval Tokens** | `hmac` + `hashlib` (stdlib) | HMAC-SHA256 over canonical fields provides tamper detection. Binds to draft content and recipient hash; mutating either invalidates the signature. Consumes single-use nonces to reject replayed commands. |
| **Audit Log** | JSON Lines + SHA-256 hash chaining | Each line includes `prev_hash = SHA256(previous_line_bytes)`. Tampering with any earlier event breaks the cryptographic chain. Runs offline with zero infrastructure. |
| **Test Runner & Linter** | pytest + ruff | 109 automated tests running in ~2.5s. Ruff enforces PEP 8, import sorting, and code cleanliness with zero warnings. |

### 3. What Uses an LLM vs. What Remains Deterministic Code

| Step | LLM / Agent (Optional/Target) | Deterministic Code (Current Reference) | Rationale |
|---|---|---|---|
| **Entity Extraction** | Optional: May assist in extracting unstructured messy notes | ✅ Rule-based regex & provenance tracking (`extractor.py`) | Keeps extraction auditable and free of external API fees. |
| **Inquiry Classification** | Optional: Can suggest category tags | ✅ Evidence-scored pattern rules (`classifier.py`) | Fast, reproducible, and verifiable against fixed enum definitions. |
| **Duplicate & CRM Matching** | Not recommended for state mutations | ✅ Idempotency hashing & token Jaccard similarity (`matcher.py`) | Entity resolution must follow strict priority (exact email → phone → company). |
| **Routing & Action Decision** | ❌ Strictly forbidden | ✅ Precedence engine & staff resolution (`router.py`, `policy.py`) | Routing decisions carry legal and financial consequences; they must be deterministic. |
| **Prompt Injection Defense** | ❌ Cannot trust LLM to self-police | ✅ Compiled regex markers (`policy.py`) | Unsanitized input is quarantined before any business evaluation. |
| **Approval Token Issuance** | ❌ Strictly forbidden | ✅ HMAC-SHA256 signing (`approval.py`) | Cryptographic tokens require authorized human operator consent. |
| **Outbound Dispatch** | ❌ Strictly forbidden | ✅ Mock dispatcher with signature verification (`dispatch.py`) | Outbound communication must never occur autonomously. |
| **Audit Logging** | ❌ Strictly forbidden | ✅ Hash-chained append-only JSONL (`audit.py`) | Tamper-evident record keeping must be deterministic and verifiable. |

### 4. Handling Incomplete Information, Hallucination, Duplicates, and Failures

**Incomplete Information & Uncertainty Preservation:**
- When an inquiry lacks required data (e.g. E005 lacks electricity bills and lighting fixture schedules), the system does **not** invent or estimate values.
- It records explicit missing prerequisites (`missing_prerequisites: ["electricity_bill", "fixture_schedule"]`) and uncertainty warnings (`"Electricity bill/interval data missing; government incentive subsidy and sizing cannot be computed."`).
- The draft response explicitly asks the prospect for these items without promising specific dollar subsidies.

**Hallucination Prevention:**
- Response drafts are constructed strictly from extracted facts, verified attachments, and routing recommendations.
- If an attachment is referenced but not loaded (e.g. E007 `portfolio.pdf`), the system emits a warning and does not falsely claim the attachment was reviewed.
- Technical inquiries (e.g. E006 harmonics) route to electrical engineering specialists without asserting an unsupported pass/fail conclusion on inverter THD limits.
- Leased premises (e.g. E012 cafe) explicitly highlight landlord consent requirements without giving legal advice.
- Disputed billing items (e.g. E003) do not claim an invoice payment has been placed on hold unless an approved action is executed.

**Duplicate Submissions vs. CRM Record Matching:**
- **Inbound duplicate / related submissions:** Evaluated by `check_inbound_relationship()`. Exact content hashes flag `EXACT_DUPLICATE`. Items sharing identical phone numbers, domains, or correction phrasing (e.g. E001/E002 Hume Logistics, E009/E010 Harbour Coldstores) are classified as `PROBABLE_RELATED_SUBMISSION`. Records are preserved without premature auto-merging.
- **CRM matching:** Evaluated by `find_crm_match()` using strict priority: Exact Email (1.0) → Normalized Phone (0.95) → Normalized Company (0.90) → Stemmed Token Jaccard (0.50–0.89) → Domain Match (0.75).

**Failures & Tampering:**
- Malformed inputs failing Pydantic schema validation fail safe into quarantine.
- Approval commands with modified drafts, expired timestamps, or reused nonces fail verification and are logged.
- Cryptographic hash-chain tampering on audit logs is detected immediately by `verify_chain()`.

### 5. Permissions, Secrets, and Sensitive Business Data

**Least Privilege:**
- Parsers and models have zero access to the HMAC secret, zero permission to issue approval commands, and zero direct network dispatch access.

**Secret Management:**
- Signing secret (`BEDA_APPROVAL_SECRET`) is read from environment variables. Missing secrets raise `RuntimeError` in production mode.

**Data Privacy in Audit Logs:**
- Audit records store event types, correlation IDs, reason codes, actor identities, and SHA-256 payload hashes. Raw email bodies, full message texts, and customer credentials are never written to audit sinks.

### 6. Cost and Latency Control

- **Zero API Dependency:** The reference engine runs offline locally with zero per-token inference charges.
- **Sub-Second Execution:** Processes the entire 12-item synthetic dataset in under 100 milliseconds.
- **Bounded Payloads:** Field lengths are constrained via Pydantic validators.

### 7. One Thing Deliberately Refused to Automate

**Outbound commercial communication and external state mutations.**

The orchestrator explicitly refuses to autonomously send emails, issue invoice holds, or mutate CRM records without human approval. Every consequential action starts in `PENDING_APPROVAL`. Only an authenticated human operator can sign an `ApprovalCommand` with HMAC-SHA256 to authorize dispatch.

### 8. Code: How the Deterministic Policy Gate Works

`src/beda_orchestrator/policy.py::evaluate_triage_decision()` enforces a 7-rule deterministic precedence hierarchy:
1. **Prompt injection signals** → `QUARANTINE` (Highest priority)
2. **Spam intent** → `AUTO_ARCHIVE_SPAM`
3. **Contradictory extraction** → `QUARANTINE`
4. **Low confidence (< 0.85)** → `QUEUE_FOR_HITL_DRAFT_REVIEW`
5. **Enterprise sales with verified budget (≥ $50,000)** → `ESCALATE_TO_HUMAN_SALES` (Budget recomputed from numeric fields, not model text)
6. **Missing critical fields (≥ 2)** → `TRIGGER_CLARIFICATION`
7. **Default** → `QUEUE_FOR_HITL_DRAFT_REVIEW`

---

## Test 2: Synthetic Data Pack Evaluation (E001–E012)

### Ingested Dataset Summary

Located in `data/`:
- **12 Emails** (`data/emails.json`): E001 through E012 covering multi-site solar leads, billing disputes, spam, school lighting, harmonics questions, internship applications, subcontractor crew reservations, contact corrections, system alerts, and leased cafe solar.
- **5 CRM Seeds** (`data/crm_seeds.json`): C001 to C005 (Hume Logistics, Greenfields Foods, Northbank College, Solara Installations).
- **4 Staff Members** (`data/staff.json`): Matt Cooper (Founder), Ties Rahardjo (Operations), Zidane Mouldino (Growth), Ali Pratama (Systems/Analyst).
- **3 Attachments** (`data/attachments/`):
  - `01_hume_energy_bill.txt`: Truganina 68,420 kWh monthly bill.
  - `02_northbank_site_notes.txt`: Northbank College site walkthrough notes.
  - `03_greenfields_invoice_query.txt`: Greenfields Foods billing reconciliation ($49,940 invoice vs $47,300 PO).

### Inspection Outputs

Running `python -m beda_orchestrator.pipeline` produces:
1. `test2_results.json`: Comprehensive structured export with classification evidence, extracted fields, uncertainties, duplicate relations, CRM matches, assigned staff, priority, and draft previews.
2. `test2_report.html`: Visual HTML inspection dashboard with clear status badges and critical safety legends.
3. `test2_audit.jsonl`: Cryptographically chained audit trail (26 events) with zero tampering.

### Safety Legend

| Status | Meaning |
|---|---|
| **RECOMMENDATION** | Proposed next step only. Work is not performed until authorized by an authenticated human operator. |
| **PENDING_APPROVAL** | Held at cryptographic trust boundary. No external email, API call, or CRM mutation has occurred. |
| **MOCK_DISPATCHED** | Verified through local single-use HMAC-SHA256 approval command. Simulated delivery logged to audit sink. |
| **AUTO_ARCHIVED** | High-confidence unsolicited spam safely archived without human interruption. |

---

## Known Weaknesses & Production Improvements

1. **Entity Resolution & Phonetics:** Current matching uses token-stemmed Jaccard similarity. In production with thousands of records, phonetics (Double Metaphone) and vector embeddings (`pgvector` / HNSW) would handle misspellings and corporate parent/subsidiary relationships.
2. **Multimodal Attachment Ingestion:** Attachments are currently ingested as text files. Production deployments require a pipeline with PDF text extraction and OCR (Tesseract / AWS Textract) for scanned utility bills.
3. **Distributed Approval Nonce Registry:** Nonces are currently tracked in process memory. A clustered environment would use Redis (`SET key NX EX <ttl>`) or a PostgreSQL ACID transaction table to prevent distributed race replays.
4. **Key Management Service (KMS):** The HMAC secret is currently read from environment variables. Production deployments should use AWS KMS or HashiCorp Vault with automated secret rotation.

---

## Author

**Muhammad Hisyam Alfaris**
*Informatics Engineering (STT Terpadu Nurul Fikri) · Cyber Security & Defensive Systems*
- Portfolio: [aboutsyem.web.id](https://aboutsyem.web.id)
- GitHub: [@Kavleri](https://github.com/Kavleri)
- Email: [muhammadhisyamalfaris50@gmail.com](mailto:muhammadhisyamalfaris50@gmail.com)
