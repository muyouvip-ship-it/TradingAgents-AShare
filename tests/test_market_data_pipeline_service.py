from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import inspect, text

from api.database import engine, init_db
from api.services.market_data_pipeline_service import (
    ingest_raw_daily_rows,
    ingest_raw_minute_rows,
    preferred_daily_kline_table,
    preferred_minute_kline_table,
    publish_minute_trade_date,
    reconcile_daily_trade_dates,
)


def _reset_tables() -> None:
    init_db()
    tables = [
        "raw_stock_daily_kline_akshare",
        "raw_stock_daily_kline_quantclass",
        "raw_stock_daily_kline_baostock",
        "raw_stock_daily_kline_efinance",
        "norm_stock_daily_kline",
        "pub_stock_daily_kline",
        "daily_kline_reconciliation_runs",
        "daily_kline_reconciliation_items",
        "raw_stock_minute_kline_qmt",
        "raw_stock_minute_kline_tdx",
        "raw_stock_minute_kline_akshare",
        "norm_stock_minute_kline",
        "pub_stock_minute_kline",
        "minute_kline_reconciliation_runs",
        "minute_kline_reconciliation_items",
        "stock_daily_kline",
        "stock_minute_kline",
    ]
    with engine.begin() as conn:
        existing = inspect(conn)
        for table_name in tables:
            if existing.has_table(table_name):
                conn.execute(text(f"DELETE FROM {table_name}"))


def test_daily_reconcile_prefers_akshare_and_records_warning() -> None:
    _reset_tables()
    trade_day = date(2026, 5, 6)

    ingest_raw_daily_rows(
        source="akshare",
        rows=[{
            "symbol": "600000",
            "trade_date": trade_day,
            "open": 10.0,
            "high": 10.5,
            "low": 9.8,
            "close": 10.2,
            "volume": 1000,
            "amount": 10200,
        }],
    )
    ingest_raw_daily_rows(
        source="baostock",
        rows=[{
            "symbol": "600000",
            "trade_date": trade_day,
            "open": 10.0,
            "high": 10.6,
            "low": 9.8,
            "close": 10.4,
            "volume": 1400,
            "amount": 14560,
        }],
    )

    result = reconcile_daily_trade_dates(trade_dates=[trade_day], symbols=["600000"])
    assert result["success"] is True
    assert result["warning_count"] == 1

    with engine.begin() as conn:
        row = conn.execute(
            text(f"SELECT source, publish_status, close FROM {preferred_daily_kline_table()} WHERE symbol = :symbol AND trade_date = :trade_date"),
            {"symbol": "600000.SH", "trade_date": trade_day},
        ).mappings().one()
        recon = conn.execute(
            text(
                """
                SELECT publish_status, chosen_source
                FROM daily_kline_reconciliation_items
                WHERE symbol = :symbol AND trade_date = :trade_date
                """
            ),
            {"symbol": "600000.SH", "trade_date": trade_day},
        ).mappings().one()

    assert row["source"] == "akshare"
    assert row["publish_status"] == "published_with_warning"
    assert float(row["close"]) == 10.2
    assert recon["chosen_source"] == "akshare"


def test_minute_publish_uses_qmt_then_fills_with_akshare() -> None:
    _reset_tables()
    trade_day = date(2026, 5, 6)
    qmt_rows = [
        {
            "symbol": "000001",
            "trade_time": datetime(2026, 5, 6, 9, 31),
            "open": 10.0,
            "high": 10.1,
            "low": 9.9,
            "close": 10.0,
            "volume": 100,
            "amount": 1000,
        }
    ]
    akshare_rows = [
        {
            "symbol": "000001",
            "trade_time": datetime(2026, 5, 6, 9, 32),
            "open": 10.0,
            "high": 10.2,
            "low": 9.95,
            "close": 10.1,
            "volume": 120,
            "amount": 1212,
        }
    ]

    ingest_raw_minute_rows(source="qmt", rows=qmt_rows)
    ingest_raw_minute_rows(source="akshare", rows=akshare_rows)

    result = publish_minute_trade_date(trade_date=trade_day, symbols=["000001"], minimum_coverage_ratio=0.0)
    assert result["success"] is True
    assert result["warning_count"] == 1

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT trade_time, primary_source, source_mix, publish_status
                FROM {preferred_minute_kline_table()}
                WHERE symbol = :symbol AND trade_date = :trade_date
                ORDER BY trade_time
                """
            ),
            {"symbol": "000001.SZ", "trade_date": trade_day},
        ).mappings().all()
        recon = conn.execute(
            text(
                """
                SELECT actual_bars, chosen_source, source_summary
                FROM minute_kline_reconciliation_items
                WHERE symbol = :symbol AND trade_date = :trade_date
                """
            ),
            {"symbol": "000001.SZ", "trade_date": trade_day},
        ).mappings().one()

    assert len(rows) == 2
    assert rows[0]["primary_source"] == "qmt"
    assert rows[0]["publish_status"] == "published_with_warning"
    assert "qmt" in str(rows[0]["source_mix"])
    assert "akshare" in str(rows[0]["source_mix"])
    assert int(recon["actual_bars"]) == 2
    assert recon["chosen_source"] == "qmt"


def test_backtest_stats_reports_legacy_minute_table_without_view_estimate() -> None:
    _reset_tables()
    trade_time = datetime(2026, 5, 6, 9, 31)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO stock_minute_kline
                (symbol, trade_time, open, high, low, close, volume, amount)
                VALUES (:symbol, :trade_time, 10, 10.1, 9.9, 10, 100, 1000)
                """
            ),
            {"symbol": "000001.SZ", "trade_time": trade_time},
        )

    from api.backtest_data_api import _build_backtest_table_stat
    from api.database import SessionLocal

    with SessionLocal() as db:
        stat = _build_backtest_table_stat(
            db,
            data_type="minute_kline",
            table_name="stock_minute_kline",
            date_column="trade_time",
        )

    assert stat is not None
    assert stat.total_records == 1
    assert stat.date_range_start == trade_time.date()
    assert stat.date_range_end == trade_time.date()
    assert stat.coverage_source == "postgresql_estimate"
