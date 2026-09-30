#!/usr/bin/env bash
# Sets up PostgreSQL + pgvector inside WSL Ubuntu on the Acer, for running the database tests locally.
# The real database lives on the Mac; this one is only for development and tests.
#
# Reads DB_NAME, DB_USER, DB_PASSWORD, DB_PORT and TEST_DB_NAME from mika/server/.env.
# Safe to run again: it only creates what is missing and resets the role's password to the one in .env.
#
# Run from Windows:
#   wsl -d Ubuntu -- sudo bash /mnt/e/learncode/AI/projects/mika_sama_project_v1/mika/server/scripts/setup_wsl_test_db.sh
set -euo pipefail

ENV_FILE="$(dirname "$(readlink -f "$0")")/../.env"

if [[ $EUID -ne 0 ]]; then
  echo "Run this with sudo." >&2
  exit 1
fi
if [[ ! -f $ENV_FILE ]]; then
  echo "Missing $ENV_FILE (copy .env.example to .env and fill it in)." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source <(sed 's/\r$//' "$ENV_FILE")  # the file may have Windows line endings
set +a

for name in "$DB_USER" "$DB_NAME" "$TEST_DB_NAME"; do
  if [[ ! $name =~ ^[a-z_][a-z0-9_]*$ ]]; then
    echo "Invalid database or role name in .env: '$name'" >&2
    exit 1
  fi
done
if [[ ! $DB_PORT =~ ^[0-9]+$ ]]; then
  echo "Invalid DB_PORT in .env: '$DB_PORT'" >&2
  exit 1
fi

cd /tmp  # the postgres user can't read the Windows folder this script lives in

echo "==> Installing PostgreSQL"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q postgresql
PG_MAJOR="$(ls /usr/lib/postgresql | sort -V | tail -1)"

echo "==> Installing pgvector for PostgreSQL $PG_MAJOR"
apt-get install -y -q "postgresql-$PG_MAJOR-pgvector"

echo "==> Configuring the cluster: port $DB_PORT, reachable from Windows"
# Port 5432 is already taken on Windows by the other PostgreSQL install.
pg_conftool "$PG_MAJOR" main set port "$DB_PORT"
# Windows reaches WSL through its localhost forwarding, which may arrive on the WSL network interface.
pg_conftool "$PG_MAJOR" main set listen_addresses '*'
HBA="/etc/postgresql/$PG_MAJOR/main/pg_hba.conf"
if ! grep -q "mika-sama: WSL network" "$HBA"; then
  printf '\n# mika-sama: WSL network (Windows -> WSL), password required\nhost all all samenet scram-sha-256\n' >>"$HBA"
fi
pg_ctlcluster "$PG_MAJOR" main restart

psql_admin() { runuser -u postgres -- psql -p "$DB_PORT" -v ON_ERROR_STOP=1 -q "$@"; }

echo "==> Creating role $DB_USER and databases $DB_NAME, $TEST_DB_NAME"
# Fed through stdin so the password never appears in the process list.
psql_admin <<SQL
DO \$\$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = '$DB_USER') THEN
    ALTER ROLE $DB_USER LOGIN PASSWORD '$DB_PASSWORD';
  ELSE
    CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASSWORD';
  END IF;
END
\$\$;
SQL
for db in "$DB_NAME" "$TEST_DB_NAME"; do
  if [[ "$(psql_admin -tAc "SELECT 1 FROM pg_database WHERE datname = '$db'")" != 1 ]]; then
    psql_admin -c "CREATE DATABASE $db OWNER $DB_USER"
  fi
  # Creating the extension needs a superuser, so it happens here rather than in the app's schema script.
  psql_admin -d "$db" -c "CREATE EXTENSION IF NOT EXISTS vector"
done

echo "==> Checking a password login as $DB_USER"
VECTOR_VERSION="$(PGPASSWORD="$DB_PASSWORD" psql -h 127.0.0.1 -p "$DB_PORT" -U "$DB_USER" -d "$TEST_DB_NAME" \
  -tAc "SELECT extversion FROM pg_extension WHERE extname = 'vector'")"
echo "Done: PostgreSQL $PG_MAJOR with pgvector $VECTOR_VERSION on port $DB_PORT (databases $DB_NAME, $TEST_DB_NAME)."
