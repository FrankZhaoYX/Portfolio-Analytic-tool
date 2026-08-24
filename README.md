# Portfolio Analytic Tool

Local, single-user portfolio analytics: FastAPI backend, KDB-X DB Service for storage/query,
Streamlit for visualization. Trades are entered manually; market data (EOD prices, quotes,
fundamentals) comes from [EODHD](https://eodhd.com/).

## Layout

- `db-service/` — vendored [kdbx-db-service](https://github.com/KxSystems/kdbx-db-service) (git submodule): the 6-container Docker Compose stack.
- `schemas/` — our table definitions and idempotent `create_tables.py`.
- `backend/` — FastAPI app (`backend/app/`).
- `frontend/` — Streamlit multipage app.
- `scripts/` — standalone CLI utilities (ingest, demo seed data).

## One-time setup

### 1. KDB-X DB Service

The DB Service images are on KX's private registry and require a free KX account + license.

```bash
docker login -u <your-email> -p <bearer-token-from-portal.dl.kx.com/auth/token> portal.dl.kx.com
```

Get a Community Edition license at https://developer.kx.com/products/kdb-x/install, then in
`db-service/.env` set `KDB_LICENSE_B64` to the base64-encoded license.

Install the compose override before starting. It moves the database onto Docker
named volumes; on the default bind mounts, macOS breaks the atomic directory
swaps the DB Service performs during ingest and hourly rollover, which
eventually corrupts the intraday database and wedges every query. The file
explains the failure in full.

```bash
cp deploy/docker-compose.override.yml db-service/
```

`db-service/` is a vendored checkout of someone else's repo, so nothing in it is
versioned here — `git reset --hard` or `git clean` inside the submodule deletes
that file. `deploy/` holds the source of truth; re-run the copy if it goes
missing. Check with `test -f db-service/docker-compose.override.yml`.

```bash
cd db-service
bash init-db.sh          # MUST run before docker compose up
docker compose up -d
docker compose ps        # all 6 containers should show Up
curl -s http://localhost:8080/api/v0/tables   # [] once licensed and ready
```

If queries later hang while `/api/v0/tables` still answers, the intraday
database has crash-looped. Check with:

```bash
docker logs kx-db-da --since 5m | grep -c "Error mounting database"
```

### 2. Create tables

```bash
python3 -m venv .venv-schemas && source .venv-schemas/bin/activate
pip install --pre --extra-index-url https://portal.dl.kx.com/assets/pypi/ kdbx_db_service_client
python schemas/create_tables.py
```

### 3. Configure environment

```bash
cp .env.example .env
# edit .env: set EODHD_API_KEY (from https://eodhd.com/), DB_SERVICE_IMPORTS_DIR (absolute path)
```

### 4. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt --extra-index-url https://portal.dl.kx.com/assets/pypi/
uvicorn app.main:app --reload --port 8000
```

Verify at http://localhost:8000/docs

### 5. Frontend

```bash
cd frontend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## First run

1. Enter a few trades via the Trade Entry page (or `python scripts/seed_demo_trades.py` with
   the backend running).
2. Click **Refresh Market Data** in the sidebar (or run `scripts/ingest_eodhd_eod.py` /
   `scripts/ingest_eodhd_fundamentals.py`).
3. Browse Positions & P&L, Performance, Risk, and Allocation.

See `.claude/plans/i-want-to-build-iterative-pie.md` (if present) for the full design rationale.
