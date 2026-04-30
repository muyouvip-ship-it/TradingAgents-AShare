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
