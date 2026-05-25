from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.market import router, search_stocks


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_market_quote_endpoint_uses_formal_qmt_service(monkeypatch):
    monkeypatch.setattr(
        "api.routes.market.fetch_realtime_quotes",
        lambda symbols: {
            "000001.SH": {
                "symbol": "000001.SH",
                "price": 3123.45,
                "change_pct": 0.56,
                "quote_time": "2026-04-28 10:31:00",
                "source": "qmt_realtime",
            }
        },
    )

    client = _client()
    response = client.get("/v1/market/quote", params={"symbol": "000001.SH"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "000001.SH"
    assert payload["quote"]["price"] == 3123.45
    assert payload["source"] == "qmt_realtime"


def test_market_intraday_endpoint_returns_qmt_intraday_payload(monkeypatch):
    monkeypatch.setattr(
        "api.routes.market.fetch_intraday_bars",
        lambda symbol, trade_date, period, include_latest_quote, account_key=None, persist=True: {
            "symbol": symbol,
            "trade_date": trade_date,
            "period": period,
            "items": [
                {
                    "symbol": symbol,
                    "trade_time": "2026-04-28 09:31:00",
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10.1,
                    "volume": 1234,
                    "amount": 12345.6,
                }
            ],
            "latest_quote": {
                "symbol": symbol,
                "price": 10.1,
                "quote_time": "2026-04-28 09:31:30",
            },
            "source": "qmt_intraday+postgresql_cache",
        },
    )

    client = _client()
    response = client.get(
        "/v1/market/intraday",
        params={"symbol": "000001.SZ", "trade_date": "2026-04-28", "period": "1m", "include_latest_quote": "true"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "000001.SZ"
    assert payload["source"] == "qmt_intraday+postgresql_cache"
    assert payload["items"][0]["trade_time"] == "2026-04-28 09:31:00"


def test_stock_search_uses_authenticated_user_for_quote_lookup(monkeypatch):
    seen = {}

    monkeypatch.setattr("api.routes.market.get_reverse_stock_map", lambda: {"600000.SH": "浦发银行"})
    monkeypatch.setattr("api.routes.market.search_cn_stock_by_name", lambda query: None)
    monkeypatch.setattr("api.routes.market._load_latest_stock_changes", lambda db, symbols: {})

    def fake_load_quote_map(symbols, *, timeout_seconds=None, db=None, user_id=None):
        seen["symbols"] = symbols
        seen["user_id"] = user_id
        return {"600000.SH": {"price": 8.88, "change_pct": 1.23}}

    monkeypatch.setattr("api.routes.market._load_quote_map", fake_load_quote_map)

    payload = search_stocks(q="浦发", db=object(), current_user=SimpleNamespace(id="user-123"))

    assert seen == {"symbols": ["600000.SH"], "user_id": "user-123"}
    assert payload["results"][0]["symbol"] == "600000.SH"
    assert payload["results"][0]["current_price"] == 8.88
