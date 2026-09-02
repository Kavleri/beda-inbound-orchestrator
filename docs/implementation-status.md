# Implementation Status

Status of each component relative to the README and design claims.

| Component | Status | Location | Test |
|---|---|---|---|
| **InboundEnvelope** (transport model) | Implemented and tested | `src/beda_orchestrator/models.py` | `tests/test_models.py::TestInboundEnvelope` |
| **InboundTriageResult** (untrusted LLM output model) | Implemented and tested | `src/beda_orchestrator/models.py` | `tests/test_models.py::TestInboundTriageResult` |
| **RoutingDecision** (policy output model) | Implemented and tested | `src/beda_orchestrator/models.py` | `tests/test_policy.py` |
| **ApprovalCommand** (HITL authorization) | Implemented and tested | `src/beda_orchestrator/models.py` | `tests/test_approval.py` |
| **Deterministic policy engine** | Implemented and tested | `src/beda_orchestrator/policy.py` | `tests/test_policy.py` (19 tests) |
| **Lead tier recomputation** | Implemented and tested | `src/beda_orchestrator/policy.py` | `tests/test_policy.py::TestEnterpriseSalesRouting` |
| **Prompt injection detection** | Implemented and tested | `src/beda_orchestrator/policy.py` | `tests/test_policy.py::TestInjectionDetection` |
| **Contradictory field detection** | Implemented and tested | `src/beda_orchestrator/policy.py` | `tests/test_policy.py::TestContradictoryFields` |
| **HMAC-SHA256 approval tokens** | Implemented and tested | `src/beda_orchestrator/approval.py` | `tests/test_approval.py` (8 tests) |
| **Constant-time signature comparison** | Implemented and tested | `src/beda_orchestrator/approval.py` | `tests/test_approval.py::TestWrongSecret` |
| **Token expiry enforcement** | Implemented and tested | `src/beda_orchestrator/approval.py` | `tests/test_approval.py::TestExpiry` |
| **Replay prevention (local in-memory)** | Implemented and tested | `src/beda_orchestrator/approval.py` | `tests/test_approval.py::TestReplay` |
| **Append-only JSONL audit sink** | Implemented and tested | `src/beda_orchestrator/audit.py` | `tests/test_audit.py` (6 tests) |
| **Hash chain verification** | Implemented and tested | `src/beda_orchestrator/audit.py` | `tests/test_audit.py::TestAuditSink::test_tampering_detected` |
| **Mock dispatcher** | Implemented and tested | `src/beda_orchestrator/dispatch.py` | `tests/test_e2e.py` |
| **Idempotency / duplicate detection (local in-memory)** | Implemented and tested | `src/beda_orchestrator/dispatch.py` | `tests/test_e2e.py::TestDuplicateEvent` |
| **Local demo (5 scenarios)** | Implemented and tested | `src/beda_orchestrator/demo.py` | Manual: `python -m beda_orchestrator.demo` |
| **End-to-end vertical slice test** | Implemented and tested | `tests/test_e2e.py` | `pytest tests/test_e2e.py` |

## Design-only (not implemented)

| Component | Notes |
|---|---|
| **FastAPI ingress gateway** | Design target. No HTTP server implemented. The envelope is constructed directly in code. |
| **Celery + Redis task queue** | Design target. Processing is synchronous in the local demo. |
| **PostgreSQL / pgvector storage** | Design target. State is in-memory dictionaries and local JSONL files. |
| **CRM reconciliation (fuzzy dedup)** | Design target. No `pg_trgm` or vector similarity implemented. |
| **Presidio PII redaction** | Design target. No NER or regex-based PII scrubbing before LLM dispatch. |
| **External LLM integration** | Design target. Triage results are mocked. |
| **Slack interactive approval UI** | Design target. Approval is a direct function call. |
| **SMTP / SendGrid outbound dispatch** | Design target. Dispatch prints to stdout. |
| **Distributed replay prevention** | Design target. Replay registry is in-memory, resets on process restart. |
| **WORM / tamper-proof audit storage** | Not implemented. Audit log is append-only at the application level only. |
| **Semantic caching (Redis + pgvector)** | Design target. No caching layer exists. |
| **Circuit breaker / retry with backoff** | Design target. No external API calls to protect. |
| **Rate limiting** | Design target. No ingress gateway exists. |
| **HMAC webhook signature verification** | Design target. No inbound webhook handling. |
| **Container / deployment configuration** | Not implemented. No Dockerfile, docker-compose, or k8s manifests. |

## Limitations

- **No external dependencies needed at runtime** beyond `pydantic>=2.7`. This is intentional for the reference implementation.
- **Replay prevention is per-process.** A production deployment needs Redis or a database-backed nonce registry.
- **Audit hash chain is verified in-memory.** The JSONL file is not protected against external modification by the filesystem.
- **Time-dependent tests** use explicit `now` parameters to avoid flakiness. No global clock mock is used.
- **The policy engine's injection detection** uses a small set of regex patterns. Production use should add more patterns and consider dedicated content filtering.
