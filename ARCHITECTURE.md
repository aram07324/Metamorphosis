# Architecture

## Current foundation

Metamorphosis is organized as a small monorepo. The Next.js App Router application is in `frontend/`; the FastAPI service, SQLAlchemy models, and Alembic migrations are in `backend/`. The frontend calls the versioned backend API directly from the browser. The backend owns persistence and business rules; frontend state is not an authorization boundary.

The backend uses Pydantic Settings for environment-based configuration, SQLAlchemy 2.x for database access, and Alembic for schema changes. SQLite is the local default, with foreign keys enabled and WAL mode enabled for file-backed databases. The initial `workspaces` table is a foundation model only; workspace membership and tenant authorization are not implemented.

The health endpoint reports process health without requiring a model provider. Readiness checks database connectivity. Neither endpoint probes Ollama. `/api/v1/chat/provider` reports the explicitly selected provider and performs a bounded local Ollama tag/model availability check when Ollama is selected.

## Chat engine

Conversation, message, and chat-turn records are persisted using the existing SQLAlchemy engine and Alembic migrations. A unique per-conversation idempotency key tracks each user turn. The user message and turn status are committed before provider generation; the assistant message is committed only on successful completion. Failed or cancelled turns can be retried with the same key without adding a second user message; completed turns replay their saved response.

`AIProvider` separates ordinary `generate`, synchronous `stream`, cancellable asynchronous `astream`, and optional embedding capability. The static provider registry selects `ollama` for new configurations or deterministic `mock` when explicitly requested. Ollama generation sends the selected conversation's system prompt and budgeted history to `/api/chat`; streaming must include a valid completion frame before the assistant response is persisted. Provider failures are mapped to stable, non-sensitive error messages; there are no automatic generation retries, and no silent provider fallback.

SSE emits JSON-formatted `meta`, incremental `delta`, and terminal `done` or `error` events. Client disconnection closes the provider iterator and marks an unfinished turn cancelled. Context selection reserves system-prompt and expected-output tokens, includes the most recent messages first, and preserves the tail of an oversized latest message. Token estimation uses a documented, conservative character-based approximation rather than claiming exact tokenizer counts.

The `/chat` client uses React Markdown with GFM but does not enable raw HTML. It persists only through the backend, supports conversation history and CRUD, aborts active streaming when navigating, and sends an idempotency key on each turn.

## Planned boundaries

- **Repositories:** workspace ownership and authorized resource queries after authentication/tenancy are implemented.
- **Workflows:** validated declarative graph schemas, static action registry, and bounded execution.
- **Integrations:** approval-gated adapters and hardened outbound networking.
- **Frontend:** visual workflow authoring and future account/workspace experiences.

These are roadmap boundaries, not claims that the corresponding features exist today. Provider credentials and other secrets must remain server-side.

## Database and migrations

Apply schema changes with Alembic from `backend/`. Never use application startup to silently create or alter production tables. SQLite is intended for local development. PostgreSQL compatibility is a design goal, but requires installing a PostgreSQL driver and verifying migrations, concurrency, and transaction behavior before deployment.

## Runtime shape

During local development, run the API and frontend as separate processes. The frontend is served on port 3000 and the API on port 8001 to avoid conflicts with other local projects. The mock provider requires no external service. No message broker, cache, scheduler, or container runtime is required.

## Future data flow

Chat currently flows browser → versioned API → persisted turn and conversation history → explicitly selected provider → persisted response/SSE stream. The API does not yet authenticate users or isolate tenants; keep it bound to local development. The planned automation flow is browser → API validation → persisted versioned graph → bounded executor → approval-gated integrations, with authorization required before public use.
