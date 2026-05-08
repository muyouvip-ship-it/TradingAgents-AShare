from datetime import date, datetime
from zoneinfo import ZoneInfo

from api.services import qmt_market_sync_service


CN_TZ = ZoneInfo("Asia/Shanghai")


def test_should_run_eod_sync_at_1535_on_trading_day(monkeypatch):
    moment = datetime(2026, 4, 28, 15, 35, tzinfo=CN_TZ)
    monkeypatch.setattr(qmt_market_sync_service, "_is_trading_day", lambda local_now: True)

    assert qmt_market_sync_service._should_run_eod_sync(moment, None) is True


def test_should_run_eod_sync_only_once_per_day(monkeypatch):
    moment = datetime(2026, 4, 28, 15, 40, tzinfo=CN_TZ)
    monkeypatch.setattr(qmt_market_sync_service, "_is_trading_day", lambda local_now: True)

    assert qmt_market_sync_service._should_run_eod_sync(moment, date(2026, 4, 28)) is False


def test_should_run_repair_sync_at_1830_on_trading_day(monkeypatch):
    moment = datetime(2026, 4, 28, 18, 30, tzinfo=CN_TZ)
    monkeypatch.setattr(qmt_market_sync_service, "_is_trading_day", lambda local_now: True)

    assert qmt_market_sync_service._should_run_repair_sync(moment, None) is True


def test_extract_stock_codes_skips_indices():
    codes = qmt_market_sync_service._extract_stock_codes(
        ["000001.SZ", "000300.SH", "399001.SZ", "600000.SH", "430001.BJ", "899050.BJ"]
    )

    assert codes == ["000001", "600000", "430001"]


def test_run_stock_daily_sync_prefers_auto_update(monkeypatch):
    monkeypatch.setattr(qmt_market_sync_service, "_trigger_stock_daily_auto_updates", lambda: [101, 102])
    monkeypatch.setattr(
        qmt_market_sync_service,
        "_run_targeted_stock_daily_sync",
        lambda trade_day, stock_codes: {"success": True, "mode": "targeted_daily_sync", "records": 99},
    )

    payload = qmt_market_sync_service._run_stock_daily_sync(
        datetime(2026, 4, 28, 15, 35, tzinfo=CN_TZ),
        ["000001.SZ", "000300.SH"],
    )

    assert payload["success"] is True
    assert payload["mode"] == "backtest_auto_update"
    assert payload["task_ids"] == [101, 102]


def test_capture_intraday_for_target_uses_user_db_context(monkeypatch):
    fake_db = object()
    captured = {}

    class FakeSessionLocal:
        def __enter__(self):
            return fake_db

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_capture(symbols, *, trade_date, period, account_key, db, user_id):
        captured.update(
            {
                "symbols": symbols,
                "trade_date": trade_date,
                "period": period,
                "account_key": account_key,
                "db": db,
                "user_id": user_id,
            }
        )
        return {"success": True, "rows": 1}

    monkeypatch.setattr(qmt_market_sync_service, "SessionLocal", FakeSessionLocal)
    monkeypatch.setattr(qmt_market_sync_service, "capture_intraday_symbols", fake_capture)

    target = qmt_market_sync_service._MarketSyncTarget(
        user_id="user-1",
        account_key="paper_sim",
        symbols=["300520.SZ"],
    )
    result = qmt_market_sync_service._capture_intraday_for_target(target, trade_date="2026-05-08")

    assert result == {"success": True, "rows": 1}
    assert captured["symbols"] == ["300520.SZ"]
    assert captured["trade_date"] == "2026-05-08"
    assert captured["period"] == "1m"
    assert captured["account_key"] == "paper_sim"
    assert captured["db"] is fake_db
    assert captured["user_id"] == "user-1"
