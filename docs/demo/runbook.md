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

Use [the current local DeepSeek trial guide](../development/deepseek-agent-trial.md).
It runs API, database Worker and web console against the same SQLite file, so
Docker and Redis are optional. Enter a new key only in the Worker terminal via
the masked prompt; do not save it to the repository. The four guided synthetic
buttons show the note → lab gap → clinician acknowledgement → dependency flow.

For a reproducible online measurement of the database Worker, see
[the evaluation guide](../../eval/README.md#database-backed-online-evaluation).
Its default MOCK row does not measure DeepSeek; real inference requires explicit
`--provider deepseek` opt-in and a locally set key.

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
