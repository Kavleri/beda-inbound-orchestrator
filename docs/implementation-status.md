# Implementation Status

Status of each component relative to the reference implementation scope and design targets.

| Component | Status | Location | Test |
|---|---|---|---|
| **InboundEnvelope** (transport model) | Implemented and tested | `src/beda_orchestrator/models.py` | `tests/test_models.py::TestInboundEnvelope` (13 tests) |
| **InboundTriageResult** (untrusted LLM extraction) | Implemented and tested | `src/beda_orchestrator/models.py` | `tests/test_models.py::TestInboundTriageResult` (8 tests) |
| **RoutingDecision** (policy output model) | Implemented and tested | `src/beda_orchestrator/models.py` | `tests/test_models.py::TestRoutingDecisionModel`, `tests/test_policy.py` |
| **ApprovalCommand** (HITL authorization model) | Implemented and tested | `src/beda_orchestrator/models.py` | `tests/test_models.py::TestApprovalCommandModel`, `tests/test_approval.py` |
| **Deterministic policy engine** | Implemented and tested | `src/beda_orchestrator/policy.py` | `tests/test_policy.py` (19 tests) |
| **Lead tier recomputation** | Implemented and tested | `src/beda_orchestrator/policy.py` | `tests/test_policy.py::TestEnterpriseSalesRouting` |
| **Prompt injection detection** | Implemented and tested | `src/beda_orchestrator/policy.py` | `tests/test_policy.py::TestInjectionDetection` |
| **Contradictory field detection** | Implemented and tested | `src/beda_orchestrator/policy.py` | `tests/test_policy.py::TestContradictoryFields` |
| **HMAC-SHA256 approval issuance** | Implemented and tested | `src/beda_orchestrator/approval.py` | `tests/test_approval.py` (23 tests) |
| **Payload hash internal binding** | Implemented and tested | `src/beda_orchestrator/approval.py` | `tests/test_approval.py::TestApprovalIssuance::test_payload_hash_computed_internally_invariant`, `test_draft_modification_invalidates_binding` |
| **Approval eligibility gate** | Implemented and tested | `src/beda_orchestrator/approval.py` | `tests/test_approval.py::TestApprovalEligibility` (8 tests) |
| **Constant-time signature verification** | Implemented and tested | `src/beda_orchestrator/approval.py` | `tests/test_approval.py::TestWrongSecret` |
| **Timezone-aware expiry enforcement** | Implemented and tested | `src/beda_orchestrator/approval.py` | `tests/test_approval.py::TestExpiry` |
| **Single-use nonce replay prevention** | Implemented and tested | `src/beda_orchestrator/approval.py` | `tests/test_approval.py::TestReplay` |
| **Append-only JSONL audit sink** | Implemented and tested | `src/beda_orchestrator/audit.py` | `tests/test_audit.py` (8 tests) |
| **Hash-chain tampering detection** | Implemented and tested | `src/beda_orchestrator/audit.py` | `tests/test_audit.py::TestAuditSink::test_tampering_detected` |
| **Audit write failure error propagation** | Implemented and tested | `src/beda_orchestrator/audit.py` | `tests/test_audit.py::TestAuditSink::test_audit_write_failure_raises_runtime_error` |
| **Mock dispatcher** | Implemented and tested | `src/beda_orchestrator/dispatch.py` | `tests/test_e2e.py` |
| **Idempotency / duplicate check (in-memory)** | Implemented and tested | `src/beda_orchestrator/dispatch.py` | `tests/test_e2e.py::TestDuplicateEvent` |
| **Local demo (5 scenarios + audit verification)** | Implemented and tested | `src/beda_orchestrator/demo.py` | Verified via runner |
| **End-to-end vertical slice** | Implemented and tested | `tests/test_e2e.py` | `tests/test_e2e.py` (6 test classes / 15 tests) |

## Design-Only (Not Implemented)

| Component | Nature of Limitation |
|---|---|
| **FastAPI HTTP gateway** | Inbound requests are instantiated directly as `InboundEnvelope` objects. No HTTP listener is running. |
| **Celery + Redis task queue** | All execution is synchronous. No asynchronous workers or distributed brokers are running. |
| **PostgreSQL / pgvector database** | State and idempotency keys are maintained in-memory. Audit logs write to local JSONL. |
| **CRM reconciliation (fuzzy matching)** | No `pg_trgm` or embedding similarity lookups against existing accounts are performed. |
| **Presidio / NER PII redaction** | PII is handled by audit-level hashing and field truncation, not an NLP redaction pipeline. |
| **External LLM inference API** | Triage inputs are mocked objects. No network calls to Anthropic or OpenAI occur. |
| **Slack Interactive UI** | Approvals are issued via Python API calls (`approve_and_send`), not webhook payloads. |
| **SMTP / SendGrid dispatch** | Dispatches print summary logs to stdout and record audit events. |
| **Distributed replay store** | Nonce registry is a process-local Python set. A process restart clears seen nonces. |
| **WORM filesystem enforcement** | Audit log integrity relies on hash chaining; OS-level write-once protection is not enforced. |
