# Mika-sama server (Mac M1)

The orchestrator: LLM, state, memory, database and output filter
([implementation plan](../../docs/implementation_plan.md)). The Acer connects to `/ws/runtime` and sends
Pandora's messages; for each one the server builds the prompt (personality, recent turns, recalled memories),
streams Mika's reply from Ollama, sends her emotion, runs every sentence through the output filter, sends the
approved sentences, and saves the turn.

**Run it** from `mika/server`, with PostgreSQL and Ollama running:

```bash
python -m app
```

It listens on port 8000 on every network interface, so the Acer can reach it (macOS may ask whether Python
may accept incoming connections: allow it). It logs to `server.log` (git-ignored) and the console, and Ctrl+C
stops it, even in the middle of a turn. Startup takes a few seconds: it loads the embedding model, and has
Ollama load `llama3.1:8b` and read Mika's prompt. It stops with an error if the database or Ollama can't be
reached. `curl http://localhost:8000/health` reports the database, Ollama, the embeddings and the Acer's parts.

The first start downloads the embedding model (0.13 GB) into `mika/server/.cache/fastembed` (git-ignored).
`MIKA_TEST_EMBEDDINGS=1 pytest` also runs the test that uses the real model.

Try things from `mika/server`, with Ollama running:
- a live reply: `python -m app.llm.live "Hi Mika!"` (add `--show-prompt` to see the system prompt, `--cold` to
  measure re-reading the whole prompt);
- the output filter: `python -m app.filter.check "a sentence" "another sentence"` (`--mode shared` for the
  other way of asking, see below);
- whole turns, timed: `python -m app.turn.bench` (below).

The files in `data/` are Pandora's to edit; the server reads them at startup. So does the `personality_traits`
table: restart the server after adding a trait.

## The output filter experiment (Phase 6)

The output filter's LLM calls can see the turn in two ways (`FilterSettings.context_mode` in `app/config.py`):
- `separate` (the default for now): the classifier and the replacer have their own short prompts, as in Phase 4;
- `shared`: they continue Mika's own conversation (her prompt, her reply so far, then a check request), so
  Ollama reuses the prompt it has just read for her reply instead of reading a new one.

`python -m app.turn.bench` plays the same five-turn conversation in both modes on the real model (about 6
minutes on the Mac; it writes nothing to the database) and prints, per turn, when the avatar would react and
when each sentence would be approved, then how each mode judges 12 labeled sentences, then a summary. Its
output decides which mode the server keeps.

Commands below run from the repo root unless they `cd` first, inside the project's `.conda` env.

## Settings

Copy `.env.example` to `.env` (git-ignored) and fill it in. `TEST_DB_NAME` names a separate database that the
tests are allowed to wipe; leave it empty to skip the database tests. Never point it at the real database.

## Setup on the Mac

Verified 2026-09-30. The Mac uses **PostgreSQL 18 from the EnterpriseDB installer** (`/Library/PostgreSQL/18`,
port 5432, managed with pgAdmin 4), with **pgvector 0.8.6 built from source**. Homebrew's PostgreSQL is not used:
it can't share port 5432 with it, and one database server saves memory on the 8 GB Mac.

1. Build pgvector into PostgreSQL 18. This needs Apple's command-line tools (`xcode-select --install`). Run it all
   in one Terminal window; `make install` asks for your Mac login password.

   ```bash
   cd /tmp && git clone --branch v0.8.6 https://github.com/pgvector/pgvector.git && cd pgvector
   export PG_CONFIG=/Library/PostgreSQL/18/bin/pg_config
   make
   sudo --preserve-env=PG_CONFIG make install
   ```

   If `make` warns `no such sysroot directory: .../MacOSX14.sdk`: the EnterpriseDB build points at the macOS SDK
   it was built with. Rebuild against your own SDK with
   `make clean && make PG_SYSROOT="$(xcrun --show-sdk-path)"` and install with the same `PG_SYSROOT=...`
   added. If the compile lines still mention `MacOSX14.sdk`, link that path to your SDK while you build
   (`sudo ln -s "$(xcrun --show-sdk-path)" /Library/Developer/CommandLineTools/SDKs/MacOSX14.sdk`, then run
   `make clean && make` and the install again, and remove the link afterwards with `sudo rm`).

2. The app's login, its database, a test database, and pgvector in both. It asks first for the `postgres`
   password (set when PostgreSQL 18 was installed), then twice for a new `mika` password: use the one you put
   in `.env` as `DB_PASSWORD`. Safe to run again.

   ```bash
   /Library/PostgreSQL/18/bin/psql -U postgres -v ON_ERROR_STOP=1 <<'SQL'
   SELECT 'CREATE ROLE mika LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'mika') \gexec
   \password mika
   SELECT format('CREATE DATABASE %I OWNER mika', d) FROM unnest(ARRAY['mika', 'mika_test']) AS d
     WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = d) \gexec
   \c mika
   CREATE EXTENSION IF NOT EXISTS vector;
   \c mika_test
   CREATE EXTENSION IF NOT EXISTS vector;
   SQL
   ```

   The `.env.example` defaults (`mika`, port 5432, `mika_test`) match this; only `DB_PASSWORD` needs setting.

3. Python packages, then the tables, the tests and the server:

   ```bash
   pip install -e "mika/shared[dev]"
   pip install -r mika/server/requirements-dev.txt
   cd mika/server
   python -m app.db.schema
   pytest
   python -m app
   ```

   `curl http://localhost:8000/health` should answer with `"status":"ok"` and `"database":"ok"`.

## Test database on the Acer (WSL)

The Acer runs the database tests against PostgreSQL + pgvector inside WSL Ubuntu, on port 5433 (its Windows
PostgreSQL on 5432 belongs to other projects). `scripts/setup_wsl_test_db.sh` sets it up from the values in
`.env`:

```bash
wsl -d Ubuntu -- sudo bash /mnt/e/learncode/AI/projects/mika_sama_project_v1/mika/server/scripts/setup_wsl_test_db.sh
```

WSL Ubuntu must be running when the tests run (open an Ubuntu terminal, or run `wsl -d Ubuntu -e true`).

On Windows, psycopg's async mode needs the selector event loop. The tests, `python -m app.db.schema` and
`python -m app` set it themselves; the server itself is meant to run on the Mac.
