#!/usr/bin/env python3
"""
补齐 SQLite -> PostgreSQL 的缺失数据，不覆盖已存在记录。
主要处理：reports / email_verification_codes / stock_daily_kline
"""

import sqlite3
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime

SQLITE_PATH = "tradingagents.db"
PG_DSN = "postgresql://localhost/trading_agents"
BATCH_SIZE = 5000

TABLE_PK = {
    "reports": ["id"],
    "email_verification_codes": ["id"],
    "stock_daily_kline": ["symbol", "trade_date"],
}


def sqlite_conn():
    return sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)


def pg_conn():
    return psycopg2.connect(PG_DSN)


def get_sqlite_columns(conn, table):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cur.fetchall()]


def get_pg_columns(conn, table):
    cur = conn.cursor()
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


def shared_columns(sqlite_columns, pg_columns, *, drop=None):
    drop = set(drop or [])
    return [c for c in sqlite_columns if c in pg_columns and c not in drop]


def count_rows_sqlite(conn, table):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    return cur.fetchone()[0]


def count_rows_pg(conn, table):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    return cur.fetchone()[0]


def build_insert_sql(table, columns, pk_columns):
    col_sql = ", ".join([f'"{c}"' for c in columns])
    conflict_sql = ", ".join([f'"{c}"' for c in pk_columns])
    return f"INSERT INTO {table} ({col_sql}) VALUES %s ON CONFLICT ({conflict_sql}) DO NOTHING"


def sync_small_table(table, sqlite, pg):
    s_cols = get_sqlite_columns(sqlite, table)
    p_cols = get_pg_columns(pg, table)
    cols = shared_columns(s_cols, p_cols)
    pk = TABLE_PK[table]

    s_cur = sqlite.cursor()
    s_cur.execute(f"SELECT {', '.join(cols)} FROM {table}")
    rows = s_cur.fetchall()

    sql = build_insert_sql(table, cols, pk)
    inserted = 0
    with pg.cursor() as cur:
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]
            before = cur.rowcount
            execute_values(cur, sql, batch, page_size=min(BATCH_SIZE, 1000))
            inserted += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    pg.commit()
    return len(rows), inserted


def sync_stock_daily_kline(sqlite, pg):
    table = "stock_daily_kline"
    s_cols = get_sqlite_columns(sqlite, table)
    p_cols = get_pg_columns(pg, table)
    # PG没有data_source列，且id走自增，避免冲突
    cols = shared_columns(s_cols, p_cols, drop={"id", "data_source"})
    pk = TABLE_PK[table]
    sql = build_insert_sql(table, cols, pk)

    s_cur = sqlite.cursor()
    total = count_rows_sqlite(sqlite, table)
    inserted = 0
    offset = 0

    with pg.cursor() as cur:
        while True:
            s_cur.execute(
                f"SELECT {', '.join(cols)} FROM {table} ORDER BY symbol, trade_date LIMIT ? OFFSET ?",
                (BATCH_SIZE, offset),
            )
            rows = s_cur.fetchall()
            if not rows:
                break
            execute_values(cur, sql, rows, page_size=1000)
            inserted += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            offset += len(rows)
            if offset % 100000 == 0 or offset == total:
                print(f"[stock_daily_kline] scanned={offset}/{total} inserted~={inserted}", flush=True)
                pg.commit()
    pg.commit()
    return total, inserted


def main():
    print(f"[start] {datetime.now().isoformat()} sync sqlite -> postgres")
    sqlite = sqlite_conn()
    pg = pg_conn()

    for table in ["reports", "email_verification_codes"]:
        s_count_before = count_rows_sqlite(sqlite, table)
        p_count_before = count_rows_pg(pg, table)
        total, inserted = sync_small_table(table, sqlite, pg)
        p_count_after = count_rows_pg(pg, table)
        print(
            f"[{table}] sqlite={s_count_before} pg_before={p_count_before} pg_after={p_count_after} inserted~={inserted}",
            flush=True,
        )

    s_count_before = count_rows_sqlite(sqlite, "stock_daily_kline")
    p_count_before = count_rows_pg(pg, "stock_daily_kline")
    total, inserted = sync_stock_daily_kline(sqlite, pg)
    p_count_after = count_rows_pg(pg, "stock_daily_kline")
    print(
        f"[stock_daily_kline] sqlite={s_count_before} pg_before={p_count_before} pg_after={p_count_after} inserted~={inserted}",
        flush=True,
    )

    sqlite.close()
    pg.close()
    print(f"[done] {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
