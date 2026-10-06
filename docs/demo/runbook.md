# ClinLoop MVP demo runbook

All records in this runbook are synthetic. The canonical patient is `P-1001`
and the canonical encounter is `ENC-2001`.

## Clean local run

```powershell
git switch main
git pull --ff-only origin main
uv sync --group dev
$env:DATABASE_URL = "sqlite+pysqlite:///demo.sqlite3"
python -m packages.fixtures.seed
python scripts/run_demo.py --patient P-1001 --database-url sqlite+pysqlite:///demo.sqlite3
```

The command publishes four fixture events and prints each `event_id`, `run_id`,
loop association, finding IDs and final action. The normal run reviews the
synthetic workflow gap and seals a handoff. Add `--no-review` to leave the
finding pending and demonstrate that sealing is blocked until review.

## Web console

In a second terminal:

```powershell
$env:DATABASE_URL = "sqlite+pysqlite:///demo.sqlite3"
uv run uvicorn apps.api.app.main:app --host 127.0.0.1 --port 8000
```

In a third terminal:

```powershell
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
npm --prefix apps/web ci
npm --prefix apps/web run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173/?patient=P-1001` and choose **最近 720 小时（30
天）** so the fixed 2026-09-28 trajectory is visible from the current date.

## DeepSeek Agent run

The default provider is the deterministic `mock`. To exercise the model-backed
path, copy `.env.example` to `.env` and set the following values locally. Never
commit the file or paste the key into a shell transcript that will be shared.

```dotenv
AGENT_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的本机密钥
DEEPSEEK_MODEL=deepseek-chat
EVENT_BUS=redis
```

Start the durable stack in separate terminals:

```powershell
docker compose up -d postgres redis
$env:AGENT_PROVIDER = "deepseek"
$env:EVENT_BUS = "redis"
$env:DEEPSEEK_API_KEY = "你的本机密钥"
uv run uvicorn apps.api.app.main:app --host 127.0.0.1 --port 8000
```

In another terminal, start the worker:

```powershell
$env:AGENT_PROVIDER = "deepseek"
$env:EVENT_BUS = "redis"
$env:DEEPSEEK_API_KEY = "你的本机密钥"
uv run python scripts/run_worker.py
```

Keep the frontend terminal from the previous section running. Submit a synthetic
event through `http://127.0.0.1:8000/docs`, then refresh the patient workspace.
The Agent trace shows provider, model, proposal reference, confidence and any
safe error code. A model error stops the current run and is persisted as
`MODEL_ERROR`; it is acknowledged by the worker after the error run is stored so
one poison message cannot block the stream forever.

For a no-Docker local smoke test, use the SQLite demo with `AGENT_PROVIDER=mock`;
the real provider requires Redis because the durable worker consumes the event
stream asynchronously.

## Docker run

```powershell
docker compose up -d postgres redis
docker compose --profile full up
```

The `worker` profile runs the synthetic demo once after PostgreSQL and Redis
are healthy. The API remains available at `http://127.0.0.1:8000`.

## Expected observations

- `EVT-1001` creates or reuses the `FOLLOW_RESULT` loop.
- `EVT-1002` produces `RESULT_WITHOUT_ACKNOWLEDGEMENT` with `LAB-8821` evidence.
- `EVT-1003` keeps the susceptibility dependency open.
- `EVT-1004` includes both high-priority loops in the handoff draft.
- No high-risk loop becomes `RESOLVED` without clinician review.
