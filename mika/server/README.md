# Mika-sama server (Mac M1)

The orchestrator: LLM, state, memory, database and output filter
([implementation plan](../../docs/implementation_plan.md)). So far (Phase 2) it has the configuration,
the PostgreSQL + pgvector database layer and a `/health` endpoint.

Commands below run from the repo root unless they `cd` first, inside the project's `.conda` env.

## Settings

Copy `.env.example` to `.env` (git-ignored) and fill it in. `TEST_DB_NAME` names a separate database that the
tests are allowed to wipe; leave it empty to skip the database tests. Never point it at the real database.

## Setup on the Mac

Not yet tried on the Mac. If a step fails, note the error and adjust.

1. PostgreSQL and pgvector with Homebrew. `brew info pgvector` lists the PostgreSQL versions its formula
   supports; use one of those (17 below).

   ```bash
   brew install postgresql@17 pgvector
   brew services start postgresql@17
   export PATH="$(brew --prefix postgresql@17)/bin:$PATH"
   ```

2. A login for the app, its database and a test database. `createuser` asks for a password: use the one you put
   in `.env` as `DB_PASSWORD`.

   ```bash
   createuser --pwprompt mika
   createdb --owner mika mika
   createdb --owner mika mika_test
   psql -d mika -c "CREATE EXTENSION IF NOT EXISTS vector"
   psql -d mika_test -c "CREATE EXTENSION IF NOT EXISTS vector"
   ```

3. Python packages, then the tables, the tests and the server:

   ```bash
   pip install -e "mika/shared[dev]"
   pip install -r mika/server/requirements-dev.txt
   cd mika/server
   python -m app.db.schema
   pytest
   uvicorn app.main:app --port 8000
   ```

   `curl http://localhost:8000/health` should answer `{"status":"ok","database":"ok"}`.

## Test database on the Acer (WSL)

The Acer runs the database tests against PostgreSQL + pgvector inside WSL Ubuntu, on port 5433 (its Windows
PostgreSQL on 5432 belongs to other projects). `scripts/setup_wsl_test_db.sh` sets it up from the values in
`.env`:

```bash
wsl -d Ubuntu -- sudo bash /mnt/e/learncode/AI/projects/mika_sama_project_v1/mika/server/scripts/setup_wsl_test_db.sh
```

WSL Ubuntu must be running when the tests run (open an Ubuntu terminal, or run `wsl -d Ubuntu -e true`).

On Windows, psycopg's async mode needs the selector event loop. The tests and `python -m app.db.schema` set it
themselves; the server itself is meant to run on the Mac.
