from datetime import date

from api.services import qmt_market_data_service


def test_sync_index_minute_history_persists_rows_by_trade_day(monkeypatch):
    inserted_tables = []
    progress = []

    monkeypatch.setattr(
        qmt_market_data_service,
        "_load_cn_trade_dates",
        lambda: ([date(2026, 4, 27), date(2026, 4, 28)], None),
    )
    monkeypatch.setattr(
        qmt_market_data_service,
        "_fetch_intraday_payload_safe",
        lambda symbols, trade_date, period, account_key: {
            "items": [
                {
                    "symbol": symbols[0],
                    "trade_time": f"{trade_date} 09:31:00",
                    "open": 1.0,
                    "high": 1.1,
                    "low": 0.9,
                    "close": 1.0,
                    "volume": 100,
                    "amount": 1000.0,
                },
                {
                    "symbol": symbols[1],
                    "trade_time": f"{trade_date} 09:31:00",
                    "open": 2.0,
                    "high": 2.1,
                    "low": 1.9,
                    "close": 2.0,
                    "volume": 200,
                    "amount": 2000.0,
                },
            ],
            "symbol_errors": {},
        },
    )
    monkeypatch.setattr(
        qmt_market_data_service,
        "_upsert_intraday_rows",
        lambda table_name, rows: inserted_tables.append((table_name, len(rows))) or len(rows),
    )

    result = qmt_market_data_service.sync_index_minute_history(
        start_date="2026-04-27",
        end_date="2026-04-28",
        symbols=["000300.SH", "399001.SZ"],
        progress_callback=lambda value, message: progress.append((value, message)),
    )

    assert result["success"] is True
    assert result["rows"] == 4
    assert result["day_rows"] == {"2026-04-27": 2, "2026-04-28": 2}
    assert result["missing_symbols"] == []
    assert inserted_tables == [("index_minute_kline", 2), ("index_minute_kline", 2)]
    assert progress[-1][0] == 100


def test_sync_index_minute_history_reports_missing_index_symbols(monkeypatch):
    monkeypatch.setattr(
        qmt_market_data_service,
        "_load_cn_trade_dates",
        lambda: ([date(2026, 4, 28)], None),
    )
    monkeypatch.setattr(
        qmt_market_data_service,
        "_fetch_intraday_payload_safe",
        lambda symbols, trade_date, period, account_key: {
            "items": [
                {
                    "symbol": "000300.SH",
                    "trade_time": f"{trade_date} 09:31:00",
                    "open": 1.0,
                    "high": 1.1,
                    "low": 0.9,
                    "close": 1.0,
                    "volume": 100,
                    "amount": 1000.0,
                }
            ],
            "symbol_errors": {},
        },
    )
    monkeypatch.setattr(qmt_market_data_service, "_upsert_intraday_rows", lambda table_name, rows: len(rows))

    result = qmt_market_data_service.sync_index_minute_history(
        start_date="2026-04-28",
        end_date="2026-04-28",
        symbols=["000300.SH", "399001.SZ", "000001.SZ"],
    )

    assert result["success"] is True
    assert result["rows"] == 1
    assert result["symbols"] == ["000300.SH", "399001.SZ"]
    assert result["missing_symbols"] == ["399001.SZ"]
