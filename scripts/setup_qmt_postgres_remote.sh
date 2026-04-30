#!/usr/bin/env bash
set -euo pipefail

PASS_VALUE="${1:?password is required}"
PGDATA_DIR="/opt/homebrew/var/postgresql@16"
PG_HBA_FILE="$PGDATA_DIR/pg_hba.conf"
PG_CONF_FILE="$PGDATA_DIR/postgresql.conf"

psql -h /tmp -d trading_agents <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'qmt_sync') THEN
    CREATE ROLE qmt_sync WITH LOGIN PASSWORD '${PASS_VALUE}';
  ELSE
    ALTER ROLE qmt_sync WITH LOGIN PASSWORD '${PASS_VALUE}';
  END IF;
END
\$\$;
GRANT CONNECT ON DATABASE trading_agents TO qmt_sync;
GRANT USAGE ON SCHEMA public TO qmt_sync;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO qmt_sync;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO qmt_sync;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO qmt_sync;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO qmt_sync;
SQL

cp "$PG_CONF_FILE" "$PG_CONF_FILE.codex.bak"
cp "$PG_HBA_FILE" "$PG_HBA_FILE.codex.bak"

perl -0pi -e "s/#listen_addresses = 'localhost'/listen_addresses = '*'/g" "$PG_CONF_FILE"

if ! grep -q "host    trading_agents    qmt_sync    192.168.10.1/32    scram-sha-256" "$PG_HBA_FILE"; then
  printf "\nhost    trading_agents    qmt_sync    192.168.10.1/32    scram-sha-256\n" >> "$PG_HBA_FILE"
fi

brew services restart postgresql@16
sleep 2

psql -h /tmp -d trading_agents -c "select rolname from pg_roles where rolname = 'qmt_sync';"
grep -n "listen_addresses = '\\*'" "$PG_CONF_FILE" || true
grep -n "qmt_sync" "$PG_HBA_FILE" || true
