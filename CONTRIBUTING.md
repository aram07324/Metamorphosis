# Contributing

## Development setup

Use the native Windows commands in [README.md](./README.md). Keep backend and frontend changes scoped to their respective folders. Do not commit `.env` files, local databases, model files, or credentials.

## Quality checks

Before submitting backend changes:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
```

Before submitting frontend changes:

```powershell
cd frontend
npm test
npm run typecheck
npm run build
```

Add focused offline tests for behavior changes. Update the roadmap and docs to describe only behavior that is actually implemented and verified. Database schema changes must include an Alembic migration.

## Design principles

Prefer typed boundaries, explicit errors, server-side authorization, bounded resource use, and minimal dependencies. Do not silently route data to another AI provider. Never use frontend-only checks as access control. Treat generated and externally supplied data as untrusted.
