# Development and deployment

## Local Windows development

The supported initial path uses native Windows, Python 3.12+, Node.js 20.9+, SQLite, and npm. The API starts without Ollama; selecting `AI_PROVIDER=mock` keeps offline development independent of an AI service. Real local inference requires installing Ollama and explicitly downloading a model. See the exact commands in [README.md](./README.md).

Run the API on `127.0.0.1:8001` and the Next.js dev server on `localhost:3000`. From the project root, start the backend in one PowerShell terminal:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
alembic upgrade head
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

In another terminal:

```powershell
cd frontend
npm run dev
```

Open `http://localhost:3000/chat`. The API's `/api/v1/health` endpoint is a process check; `/api/v1/ready` checks database connectivity. Neither checks the AI provider. `/api/v1/chat/provider` reports selected-provider/model availability separately.

## Database operations

From `backend/`, activate the virtual environment before running:

```powershell
alembic upgrade head
alembic current
```

The default database is `backend/data/metamorphosis.db`. Back up a stopped local SQLite database by copying the database file and, if present, its `-wal` and `-shm` files together; a SQLite online backup is preferable while the service is running. To restore, stop the API, place the verified backup at the configured path, then run `alembic upgrade head`.

For PostgreSQL, configure a SQLAlchemy PostgreSQL URL and install a compatible driver. Migration, pooling, restore, and concurrent-write behavior against PostgreSQL have not yet been validated.

## Production status

No production deployment target, container image, TLS termination, persistent hosted database, monitoring, or cloud free-tier has been configured or verified. The current service has no authentication and must not be published publicly. Before deployment, complete the security and operations roadmap, choose persistent database storage, configure HTTPS and trusted origins, provide managed backups, and assess host uptime/storage/usage limits and costs.

No model is installed or downloaded by application startup. `qwen2.5:3b` is the documented configured model for this development setup; verify its presence with `ollama list` before using it. Model downloads require internet access and disk space; check the current Ollama library listing for the model's download size and license terms.
