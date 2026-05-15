from __future__ import annotations

from datetime import date

from api import backtest_data_api as target


def test_daily_kline_calendar_min_max_uses_physical_tables(monkeypatch) -> None:
    seen_tables: list[str] = []
    ranges = {
        "stock_daily_kline": (date(2025, 1, 2), date(2026, 1, 1)),
        "pub_stock_daily_kline": (date(2024, 1, 3), date(2026, 5, 14)),
    }

    monkeypatch.setattr(
        target,
        "_relation_exists",
        lambda _db, table_name: table_name
        in {"stock_daily_kline", "pub_stock_daily_kline", "market_stock_daily_kline"},
    )
    monkeypatch.setattr(target, "preferred_daily_kline_table", lambda: "market_stock_daily_kline")

    def fake_min_max(_db, table_name: str, _date_column: str):
        seen_tables.append(table_name)
        return ranges[table_name]

    monkeypatch.setattr(target, "_fast_min_max_date", fake_min_max)

    min_date, max_date, source_tables = target._daily_kline_calendar_min_max(db=object())

    assert min_date == date(2024, 1, 3)
    assert max_date == date(2026, 5, 14)
    assert source_tables == ["stock_daily_kline", "pub_stock_daily_kline"]
    assert seen_tables == ["stock_daily_kline", "pub_stock_daily_kline"]


def test_daily_kline_calendar_rows_do_not_query_unified_view() -> None:
    class FakeResult:
        def fetchall(self):
            return []

    class FakeSession:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def execute(self, statement, _params=None):
            self.queries.append(str(statement))
            return FakeResult()

    db = FakeSession()

    rows = target._daily_kline_calendar_rows(
        db,
        start_date=date(2026, 1, 1),
        end_date=date(2027, 1, 1),
        source_tables=["stock_daily_kline", "pub_stock_daily_kline"],
    )

    assert rows == []
    query = "\n".join(db.queries)
    assert "stock_daily_kline" in query
    assert "pub_stock_daily_kline" in query
    assert "market_stock_daily_kline" not in query


def test_daily_kline_calendar_rest_day_uses_trade_calendar(monkeypatch) -> None:
    monkeypatch.setattr(target, "is_cn_trading_day", lambda value: value != "2026-05-01")

    assert target._daily_kline_calendar_is_rest_day(date(2026, 5, 1)) is True
    assert target._daily_kline_calendar_is_rest_day(date(2026, 5, 4)) is False
