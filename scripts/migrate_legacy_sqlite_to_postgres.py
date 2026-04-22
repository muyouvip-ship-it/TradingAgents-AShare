#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import Json, execute_values

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from api.core.env import load_project_env

load_project_env()

from sqlalchemy import create_engine

from api.database import Base as AppBase
from api.models.strategy_models import Base as StrategyBase


@dataclass(frozen=True)
class LegacySource:
    label: str
    path: Path
    tables: list[str]


TARGET_CONFLICT_COLUMNS: dict[str, list[str]] = {
    "users": ["id"],
    "email_verification_codes": ["id"],
    "user_llm_configs": ["user_id"],
    "user_tokens": ["id"],
    "version_stats": ["id"],
    "watchlist_items": ["user_id", "symbol"],
    "scheduled_analyses": ["user_id", "symbol"],
    "reports": ["id"],
    "sponsors": ["id"],
    "feedbacks": ["id"],
    "imported_portfolio_positions": ["user_id", "source", "symbol"],
    "strategies": ["id"],
    "backtest_jobs": ["id"],
    "backtest_results": ["id"],
    "trade_records": ["id"],
    "factors": ["id"],
    "index_daily_kline": ["symbol", "trade_date"],
    "stock_daily_kline": ["symbol", "trade_date"],
}

BOOLEAN_TYPES = {"boolean"}
JSON_TYPES = {"json", "jsonb"}
BATCH_SIZE = 1000


def _load_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL 未配置，无法迁移到 PostgreSQL。")
    if not database_url.startswith("postgresql"):
        raise RuntimeError(f"DATABASE_URL 不是 PostgreSQL: {database_url.split(':', 1)[0]}")
    return database_url


def ensure_target_schema(database_url: str) -> None:
    engine = create_engine(database_url)
    AppBase.metadata.create_all(engine)
    StrategyBase.metadata.create_all(engine)


def sqlite_connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def pg_connect(database_url: str):
    return psycopg2.connect(database_url)


def sqlite_tables(conn: sqlite3.Connection) -> set[str]:
    cur = conn.cursor()
    return {
        row[0]
        for row in cur.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")
    }


def count_sqlite_rows(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]


def count_pg_rows(conn, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM "{table}"')
        return cur.fetchone()[0]


def get_sqlite_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    cur = conn.cursor()
    cur.execute(f'PRAGMA table_info("{table}")')
    return [row[1] for row in cur.fetchall()]


def get_pg_columns(conn, table: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table,),
        )
        return [row[0] for row in cur.fetchall()]


def get_pg_column_types(conn, table: str) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            """,
            (table,),
        )
        return {row[0]: row[1] for row in cur.fetchall()}


def shared_columns(sqlite_cols: list[str], pg_cols: list[str]) -> list[str]:
    return [col for col in sqlite_cols if col in pg_cols]


def normalize_value(value: Any, pg_type: str) -> Any:
    if value is None:
        return None
    if pg_type in BOOLEAN_TYPES:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
    if pg_type in JSON_TYPES and isinstance(value, str):
        text_value = value.strip()
        if not text_value:
            return None
        try:
            return Json(json.loads(text_value))
        except json.JSONDecodeError:
            return value
    if pg_type in JSON_TYPES and isinstance(value, (dict, list)):
        return Json(value)
    return value


def build_insert_sql(table: str, columns: list[str]) -> str:
    conflict_columns = TARGET_CONFLICT_COLUMNS[table]
    column_sql = ", ".join(f'"{column}"' for column in columns)
    conflict_sql = ", ".join(f'"{column}"' for column in conflict_columns)
    return f'INSERT INTO "{table}" ({column_sql}) VALUES %s ON CONFLICT ({conflict_sql}) DO NOTHING'


def ensure_placeholder_strategies(sqlite_conn: sqlite3.Connection, pg_conn) -> int:
    if "backtest_jobs" not in sqlite_tables(sqlite_conn):
        return 0

    rows = sqlite_conn.execute(
        """
        SELECT DISTINCT b.strategy_id
        FROM backtest_jobs b
        LEFT JOIN strategies s ON s.id = b.strategy_id
        WHERE s.id IS NULL AND b.strategy_id IS NOT NULL
        """
    ).fetchall()
    if not rows:
        return 0

    now = datetime.now()
    placeholders = [
        (
            strategy_id,
            f"Legacy missing strategy {strategy_id[:8]}",
            "TRADING",
            "ARCHIVED",
            1,
            False,
            0,
            now,
            now,
        )
        for strategy_id, in rows
    ]
    with pg_conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO "strategies"
                ("id", "name", "strategy_type", "status", "version", "is_active", "run_count", "created_at", "updated_at")
            VALUES %s
            ON CONFLICT ("id") DO NOTHING
            """,
            placeholders,
            page_size=BATCH_SIZE,
        )
    pg_conn.commit()
    return len(placeholders)


def migrate_table(sqlite_conn: sqlite3.Connection, pg_conn, table: str) -> tuple[int, int, int]:
    sqlite_count = count_sqlite_rows(sqlite_conn, table)
    if sqlite_count == 0:
        return 0, count_pg_rows(pg_conn, table), count_pg_rows(pg_conn, table)

    sqlite_cols = get_sqlite_columns(sqlite_conn, table)
    pg_cols = get_pg_columns(pg_conn, table)
    columns = shared_columns(sqlite_cols, pg_cols)
    if not columns:
        raise RuntimeError(f"表 {table} 没有可迁移的共享列")

    pg_types = get_pg_column_types(pg_conn, table)
    sqlite_cur = sqlite_conn.cursor()
    sqlite_cur.execute(f'SELECT {", ".join(f"""\"{column}\"""" for column in columns)} FROM "{table}"')
    rows = sqlite_cur.fetchall()
    converted_rows = [
        tuple(normalize_value(value, pg_types.get(column, "")) for column, value in zip(columns, row))
        for row in rows
    ]

    before_count = count_pg_rows(pg_conn, table)
    insert_sql = build_insert_sql(table, columns)
    with pg_conn.cursor() as cur:
        for start in range(0, len(converted_rows), BATCH_SIZE):
            batch = converted_rows[start:start + BATCH_SIZE]
            execute_values(cur, insert_sql, batch, page_size=BATCH_SIZE)
    pg_conn.commit()
    after_count = count_pg_rows(pg_conn, table)
    return sqlite_count, before_count, after_count


def main() -> None:
    database_url = _load_database_url()
    ensure_target_schema(database_url)

    sources = [
        LegacySource(
            label="app",
            path=project_root / "app.db",
            tables=[
                "users",
                "email_verification_codes",
                "user_llm_configs",
                "user_tokens",
                "reports",
                "watchlist_items",
                "scheduled_analyses",
                "feedbacks",
                "sponsors",
                "imported_portfolio_positions",
                "version_stats",
            ],
        ),
        LegacySource(
            label="strategy",
            path=project_root / "data" / "strategy_management.db",
            tables=[
                "strategies",
                "backtest_jobs",
                "backtest_results",
                "trade_records",
                "factors",
                "index_daily_kline",
            ],
        ),
    ]

    with pg_connect(database_url) as pg_conn:
        for source in sources:
            if not source.path.exists():
                print(f"[skip] {source.label} source missing: {source.path}")
                continue
            with sqlite_connect(source.path) as sqlite_conn:
                existing_tables = sqlite_tables(sqlite_conn)
                print(f"[source] {source.label}: {source.path}")
                for table in source.tables:
                    if table not in existing_tables:
                        print(f"  - [skip] {table}: source table missing")
                        continue
                    if table == "backtest_jobs":
                        placeholder_count = ensure_placeholder_strategies(sqlite_conn, pg_conn)
                        if placeholder_count:
                            print(f"  - strategies: placeholder_orphans={placeholder_count}")
                    sqlite_count, before_count, after_count = migrate_table(sqlite_conn, pg_conn, table)
                    print(
                        f"  - {table}: sqlite={sqlite_count} pg_before={before_count} pg_after={after_count}"
                    )


if __name__ == "__main__":
    main()
