#!/usr/bin/env bash
set -euo pipefail

WOLF_PASS="${1:?wolf password is required}"
QMT_PASS="${2:?qmt password is required}"
PGDATA_DIR="/opt/homebrew/var/postgresql@16"
PG_HBA_FILE="$PGDATA_DIR/pg_hba.conf"
PG_CONF_FILE="$PGDATA_DIR/postgresql.conf"

cp "$PG_CONF_FILE" "$PG_CONF_FILE.codex.repair.bak"
cp "$PG_HBA_FILE" "$PG_HBA_FILE.codex.repair.bak"

perl -0pi -e "s/listen_addresses = '\\*'/listen_addresses = 'localhost'/g; s/#listen_addresses = 'localhost'/listen_addresses = 'localhost'/g" "$PG_CONF_FILE"
perl -0pi -e "s/^host\\s+all\\s+all\\s+127\\.0\\.0\\.1\\/32\\s+trust\$/host    all             all             127.0.0.1\\/32            scram-sha-256/gm" "$PG_HBA_FILE"
perl -0pi -e "s/^host\\s+all\\s+all\\s+::1\\/128\\s+trust\$/host    all             all             ::1\\/128                 scram-sha-256/gm" "$PG_HBA_FILE"

brew services restart postgresql@16
sleep 2

psql -h /tmp -d trading_agents <<SQL
ALTER ROLE wolf WITH LOGIN PASSWORD '${WOLF_PASS}';
ALTER ROLE qmt_sync WITH LOGIN PASSWORD '${QMT_PASS}';
SQL

psql -h /tmp -d trading_agents -c "select current_user, current_database();"
grep -n "listen_addresses = 'localhost'" "$PG_CONF_FILE" || true
grep -n "127.0.0.1/32" "$PG_HBA_FILE" || true
