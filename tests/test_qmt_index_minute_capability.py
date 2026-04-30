import sys
import types

import pandas as pd

from api.services import qmt_market_data_service


def test_sync_index_minute_history_fails_fast_when_bridge_lacks_capability(monkeypatch):
    monkeypatch.setattr(
        qmt_market_data_service,
        "_resolve_trade_dates",
        lambda start, end: [start],
    )
    monkeypatch.setattr(
        qmt_market_data_service,
        "_fetch_intraday_payload_safe",
        lambda symbols, trade_date, period, account_key: {
            "items": [],
            "rows": 0,
            "symbol_errors": {
                symbol: {
                    "message": '当前客户端未支持此功能 func:commonControl error {"ErrorID":300000,"ErrorMsg":"function not realize"}',
                    "unsupported": True,
                }
                for symbol in symbols
            },
        },
    )

    payload = qmt_market_data_service.sync_index_minute_history(
        start_date="2026-04-27",
        end_date="2026-04-27",
        symbols=["000300.SH", "399001.SZ"],
    )

    assert payload["success"] is False
    assert "function not realize" in payload["symbol_errors"]["000300.SH"]["message"]
    assert "不支持指数分钟历史接口" in payload["error"]


def test_sync_index_minute_history_falls_back_to_akshare_recent_window(monkeypatch):
    monkeypatch.setattr(
        qmt_market_data_service,
        "_recent_trade_dates",
        lambda limit: [
            qmt_market_data_service.date(2026, 4, 22),
            qmt_market_data_service.date(2026, 4, 23),
            qmt_market_data_service.date(2026, 4, 24),
            qmt_market_data_service.date(2026, 4, 27),
            qmt_market_data_service.date(2026, 4, 28),
        ],
    )
    monkeypatch.setattr(qmt_market_data_service, "_upsert_intraday_rows", lambda table_name, rows: len(rows))
    fake_ak = types.SimpleNamespace(
        index_zh_a_hist_min_em=lambda symbol, period, start_date, end_date: pd.DataFrame(
            [
                {
                    "时间": "2026-04-27 09:31:00",
                    "开盘": 1.0,
                    "最高": 1.1,
                    "最低": 0.9,
                    "收盘": 1.0,
                    "成交量": 100,
                    "成交额": 1000.0,
                }
            ]
        )
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_ak)

    payload = qmt_market_data_service.sync_index_minute_history(
        start_date="2026-04-27",
        end_date="2026-04-27",
        symbols=["000300.SH"],
        data_source="akshare",
    )

    assert payload["success"] is True
    assert payload["rows"] == 1
    assert payload["source"] == "akshare_index_minute"


def test_sync_index_minute_history_rejects_akshare_old_range(monkeypatch):
    monkeypatch.setattr(
        qmt_market_data_service,
        "_recent_trade_dates",
        lambda limit: [
            qmt_market_data_service.date(2026, 4, 22),
            qmt_market_data_service.date(2026, 4, 23),
            qmt_market_data_service.date(2026, 4, 24),
            qmt_market_data_service.date(2026, 4, 27),
            qmt_market_data_service.date(2026, 4, 28),
        ],
    )

    payload = qmt_market_data_service.sync_index_minute_history(
        start_date="2026-04-01",
        end_date="2026-04-27",
        symbols=["000300.SH"],
        data_source="akshare",
    )

    assert payload["success"] is False
    assert "仅能正式补最近 5 个交易日" in payload["error"]
