# Security status

## Current controls

- Runtime configuration is externalized; `.env` files are ignored by Git.
- SQLite connections enable foreign-key enforcement; chat inputs and outputs use typed Pydantic response models and bounded message lengths.
- CORS is restricted to configured origins (local frontend origins by default).
- Health is independent of AI providers; readiness returns a generic unavailable response rather than database exception details.
- Chat requests use per-conversation idempotency keys; completed turns are replayed rather than generated twice. Provider error responses do not include prompts or provider exception details.
- Markdown is rendered without enabling raw HTML. New configurations select Ollama; the provider connects only to its configured endpoint. Ollama errors are reduced to stable public messages and never trigger mock fallback. The mock provider must be selected explicitly for offline, network-free use.

## Not implemented

There is no authentication, authorization, tenant isolation, rate limiting, CSRF/session handling, audit system, secret encryption, approval system, outbound HTTP action, or webhook authentication. Chat conversations and messages are stored as plaintext in the local SQLite database. The API currently exposes conversation data to any local client that can reach it. Do not expose this development service to an untrusted network or use it to store sensitive data.

The default SQLite database and development configuration are not a production security boundary. Production secrets, HTTPS, origin policy, backup protection, and database access controls must be designed and verified before deployment. No claim of production readiness or vulnerability-free operation is made.

## Reporting

Do not include credentials, tokens, private user data, or sensitive payloads in issue reports. Security review and remediation should precede any public deployment.
