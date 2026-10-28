# Implementation plan

Status reflects code present and checks run; a roadmap item is not complete merely because its design is documented.

## Milestone 1 — Foundation (complete)

- [x] Inspect the provided workspace and available runtimes.
- [x] Add the FastAPI application shell and versioned health/readiness endpoints.
- [x] Add settings, basic logging, SQLite connection configuration, SQLAlchemy metadata, and the initial Alembic migration.
- [x] Add a Next.js App Router shell and a live backend health indicator.
- [x] Add Windows startup instructions and offline backend tests.
- [x] Verify backend tests and migration upgrade.
- [x] Verify frontend typecheck and production build.
- [x] Verify both services together with API health/readiness and frontend HTTP response.

**Acceptance:** Backend tests and migration drift check pass; frontend typecheck, production build, and dependency audit pass; both development servers returned expected responses in a local smoke test.

## Milestone 2 — Chat engine (complete)

- [x] Conversation/message persistence and conversation CRUD/pagination API. User ownership authorization remains for milestone 5 because authentication is not yet implemented.
- [x] Deterministic mock provider and optional local Ollama provider; no automatic model download or fallback.
- [x] SSE streaming, idempotency/replay, cancellation handling, provider errors/timeouts, and context budgeting.
- [x] Chat UI, history management, streaming controls, retry, and Markdown/GFM rendering without raw HTML.
- [x] Offline tests for persistence, streaming, retries, provider failures, migrations, and context limits; frontend SSE parser tests.

**Acceptance:** Mock chat is usable without Ollama or paid APIs; conversation/message data persists in SQLite; streaming and retries are tested; the `/chat` UI works against the API on port 8001. Authentication and tenant isolation are explicitly deferred to milestone 5, so keep local development bound to loopback.

## Milestone 3 — Automation engine

- [ ] Declarative workflow schemas, CRUD, and independent server-side graph validation.
- [ ] Visual editor, explicit trigger/action registry, and DAG validation.
- [ ] Bounded execution, progress/history, retries, cancellation, and idempotency.
- [ ] Lightweight persistent scheduler and restart/missed-run behavior.
- [ ] Tests for invalid graphs, branching, limits, and failure handling.

## Milestone 4 — Integrations and approvals

- [ ] Webhook receiver, development-safe notification/email adapters, and integration status.
- [ ] Approval queue with exact-action binding, expiration, replay protection, and audit history.
- [ ] Encrypted integration-secret storage with externally supplied key and rotation guidance.
- [ ] Hardened outbound request service or disable arbitrary destinations until DNS/connection validation is reliable.
- [ ] Focused tests for approval enforcement, secret handling, webhooks, and SSRF boundaries.

## Milestone 5 — Production hardening

- [ ] Authentication, secure sessions, workspace membership, and server-side tenant isolation.
- [ ] Rate limiting, security headers, CORS policy, input/output protections, and audit events.
- [ ] PostgreSQL migration/transaction compatibility and operational monitoring.
- [ ] Deployment, backup/restore, dependency checks, and recovery verification.
- [ ] Security regression tests and explicit residual-risk review.

## Constraints

Keep the basic Windows development path independent of Docker, WSL2, Redis, paid APIs, and external AI services. Verify licensing and compatibility before adopting major dependencies. Do not claim production readiness, complete SSRF protection, or zero vulnerabilities without evidence.
