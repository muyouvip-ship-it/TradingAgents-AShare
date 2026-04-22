from __future__ import annotations

import os
import time
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field


app = FastAPI(title="QMT Bridge Server", version="1.0.0")
_SECURITY_NAME_CACHE: dict[str, str] = {}


def _log(message: str) -> None:
    print(f"[qmt-bridge] {message}", flush=True)


class OrderSubmitRequest(BaseModel):
    account_id: str = Field(..., min_length=1)
    account_type: str = Field(default="STOCK", min_length=1)
    account_key: str | None = None
    symbol: str = Field(..., min_length=1)
    side: str = Field(..., min_length=1)
    quantity: int = Field(..., gt=0)
    price: float | None = Field(default=None, gt=0)
    price_type: str = Field(default="limit", min_length=1)
    strategy_name: str | None = None
    order_remark: str | None = None


def _bridge_token() -> str:
    return str(os.getenv("QMT_BRIDGE_TOKEN") or "").strip()


def _require_token(authorization: str | None) -> None:
    expected = _bridge_token()
    if not expected:
        return
    token = str(authorization or "").removeprefix("Bearer ").strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="bridge token invalid")


def _symbol_for_xt(value: str) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required")
    return symbol


def _normalize_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol:
        return ""
    if "." in symbol:
        return symbol
    if len(symbol) == 6:
        if symbol.startswith("6"):
            return f"{symbol}.SH"
        if symbol.startswith(("0", "3")):
            return f"{symbol}.SZ"
        if symbol.startswith(("4", "8")):
            return f"{symbol}.BJ"
    return symbol


def _looks_like_symbol(value: Any) -> bool:
    text = str(value or "").strip().upper()
    return (len(text) == 6 and text.isdigit()) or (
        len(text) == 9 and text[:6].isdigit() and text[6:] in (".SH", ".SZ", ".BJ")
    )


def _query_security_name(symbol: str) -> str:
    normalized = _normalize_symbol(symbol)
    if not normalized:
        return ""
    if normalized in _SECURITY_NAME_CACHE:
        return _SECURITY_NAME_CACHE[normalized]
    name = ""
    try:
        from xtquant import xtdata

        detail = xtdata.get_instrument_detail(normalized) or {}
        if isinstance(detail, dict):
            for key in ("InstrumentName", "instrument_name", "StockName", "stock_name", "name"):
                value = str(detail.get(key) or "").strip()
                if value and not _looks_like_symbol(value):
                    name = value
                    break
    except Exception as exc:
        _log(f"query security name failed symbol={normalized}: {exc}")
    if name:
        _SECURITY_NAME_CACHE[normalized] = name
    return name


def _resolve_payload_symbol(payload: dict[str, Any]) -> str:
    return _normalize_symbol(
        payload.get("stockCode")
        or payload.get("stock_code")
        or payload.get("symbol")
        or payload.get("m_strStockCode")
    )


def _resolve_payload_name(payload: dict[str, Any], symbol: str) -> str:
    for key in (
        "stockName",
        "stock_name",
        "security_name",
        "name",
        "instrument_name",
        "InstrumentName",
        "m_strStockName",
        "m_strInstrumentName",
    ):
        value = str(payload.get(key) or "").strip()
        if value and not _looks_like_symbol(value):
            return value
    return _query_security_name(symbol) or symbol


def _enrich_security_names(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in items:
        payload = dict(item)
        symbol = _resolve_payload_symbol(payload)
        if symbol:
            payload.setdefault("symbol", symbol)
            payload.setdefault("stock_code", symbol)
            payload["security_name"] = _resolve_payload_name(payload, symbol)
            payload.setdefault("stockName", payload["security_name"])
        enriched.append(payload)
    return enriched


def _resolve_order_params(side: str, price_type: str, symbol: str) -> tuple[int, int]:
    try:
        from xtquant import xtconstant
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"xtconstant unavailable: {exc}") from exc

    side_key = str(side or "").strip().lower()
    if side_key in {"buy", "long_buy", "b"}:
        order_type = getattr(xtconstant, "STOCK_BUY", 23)
    elif side_key in {"sell", "long_sell", "s"}:
        order_type = getattr(xtconstant, "STOCK_SELL", 24)
    else:
        raise HTTPException(status_code=400, detail=f"unsupported side: {side}")

    price_key = str(price_type or "limit").strip().lower()
    exchange = symbol.split(".")[-1] if "." in symbol else ""
    price_type_map = {
        "limit": getattr(xtconstant, "FIX_PRICE", 11),
        "latest": getattr(xtconstant, "LATEST_PRICE", getattr(xtconstant, "FIX_PRICE", 11)),
        "opponent": getattr(xtconstant, "MARKET_PEER_PRICE_FIRST", getattr(xtconstant, "FIX_PRICE", 11)),
        "self_best": getattr(xtconstant, "MARKET_MINE_PRICE_FIRST", getattr(xtconstant, "FIX_PRICE", 11)),
        "best5_cancel": getattr(
            xtconstant,
            "MARKET_SH_CONVERT_5_CANCEL" if exchange == "SH" else "MARKET_SZ_CONVERT_5_CANCEL",
            getattr(xtconstant, "FIX_PRICE", 11),
        ),
    }
    if price_key not in price_type_map:
        raise HTTPException(status_code=400, detail=f"unsupported price_type: {price_type}")
    return order_type, price_type_map[price_key]


def _create_trader(account_id: str, account_type: str):
    try:
        from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
        from xtquant.xttype import StockAccount
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"xtquant unavailable: {exc}") from exc

    userdata_path = str(os.getenv("QMT_USERDATA_PATH") or "").strip()
    if not userdata_path:
        raise HTTPException(status_code=400, detail="QMT_USERDATA_PATH is required")

    session_id = int(time.time() * 1000) % 100000000
    _log(f"create trader session={session_id} account_id={account_id} account_type={account_type}")
    trader = XtQuantTrader(userdata_path, session_id)
    account = StockAccount(account_id, account_type)

    class _Callback(XtQuantTraderCallback):
        def on_disconnected(self):
            _log("xttrader disconnected")

        def on_account_status(self, status):
            status_value = getattr(status, "status", None)
            _log(f"account status update: {status_value}")

    register_callback = getattr(trader, "register_callback", None)
    if callable(register_callback):
        _log("register callback")
        register_callback(_Callback())

    start = getattr(trader, "start", None)
    if callable(start):
        _log("start trader thread")
        start()
    _log("connect trader")
    connect_result = getattr(trader, "connect")()
    _log(f"connect result={connect_result}")
    if connect_result not in (0, None):
        raise HTTPException(status_code=502, detail=f"connect failed: {connect_result}")
    subscribe = getattr(trader, "subscribe", None)
    if callable(subscribe):
        _log("subscribe account")
        subscribe_result = subscribe(account)
        _log(f"subscribe result={subscribe_result}")
    return trader, account


def _stop_trader(trader: Any) -> None:
    stop = getattr(trader, "stop", None)
    if callable(stop):
        try:
            _log("stop trader")
            stop()
        except Exception:
            pass


def _query_snapshot(account_id: str, account_type: str) -> dict[str, Any]:
    trader, account = _create_trader(account_id, account_type)

    positions = None
    asset = None
    orders = None
    trades = None
    try:
        _log("query stock asset")
        asset = trader.query_stock_asset(account)
        _log("query stock positions")
        if positions in (None, []):
            positions = trader.query_stock_positions(account)
        _log("query stock orders")
        query_stock_orders = getattr(trader, "query_stock_orders", None)
        if callable(query_stock_orders):
            orders = query_stock_orders(account)
        _log("query stock trades")
        query_stock_trades = getattr(trader, "query_stock_trades", None)
        if callable(query_stock_trades):
            trades = query_stock_trades(account)
    finally:
        _stop_trader(trader)

    def normalize(item: Any) -> dict[str, Any]:
        if isinstance(item, dict):
            return item
        data: dict[str, Any] = {}
        for key in dir(item):
            if key.startswith("_"):
                continue
            value = getattr(item, key, None)
            if callable(value):
                continue
            if isinstance(value, (str, int, float, bool, list, dict)) or value is None:
                data[key] = value
        return data

    normalized_positions = [normalize(item) for item in (positions or [])]
    normalized_orders = [normalize(item) for item in (orders or [])]
    normalized_trades = [normalize(item) for item in (trades or [])]

    return {
        "asset": normalize(asset),
        "positions": _enrich_security_names(normalized_positions),
        "orders": _enrich_security_names(normalized_orders),
        "trades": _enrich_security_names(normalized_trades),
    }


def _submit_order(request: OrderSubmitRequest) -> dict[str, Any]:
    symbol = _symbol_for_xt(request.symbol)
    order_type, price_mode = _resolve_order_params(request.side, request.price_type, symbol)
    if str(request.price_type or "limit").strip().lower() == "limit" and request.price is None:
        raise HTTPException(status_code=400, detail="limit order requires price")

    trader, account = _create_trader(request.account_id, request.account_type)
    try:
        order_stock = getattr(trader, "order_stock", None)
        if not callable(order_stock):
            raise HTTPException(status_code=500, detail="xttrader.order_stock unavailable")
        _log(
            f"submit order symbol={symbol} side={request.side} qty={request.quantity} price={request.price} price_type={request.price_type}"
        )
        result = order_stock(
            account,
            symbol,
            order_type,
            int(request.quantity),
            price_mode,
            float(request.price or 0.0),
            str(request.strategy_name or "CodexQmtBridge"),
            str(request.order_remark or ""),
        )
        _log(f"submit order result={result}")
        return {
            "success": True,
            "order_id": str(result),
            "result": result,
            "request": request.model_dump(),
        }
    finally:
        _stop_trader(trader)


def _cancel_order(account_id: str, account_type: str, order_id: str) -> dict[str, Any]:
    trader, account = _create_trader(account_id, account_type)
    try:
        cancel_order_stock = getattr(trader, "cancel_order_stock", None)
        if not callable(cancel_order_stock):
            raise HTTPException(status_code=500, detail="xttrader.cancel_order_stock unavailable")
        cancel_arg: Any = int(order_id) if str(order_id).isdigit() else order_id
        _log(f"cancel order order_id={order_id}")
        result = cancel_order_stock(account, cancel_arg)
        _log(f"cancel order result={result}")
        return {
            "success": True,
            "order_id": str(order_id),
            "result": result,
        }
    finally:
        _stop_trader(trader)


@app.get("/health")
def health(authorization: str | None = Header(default=None)):
    _require_token(authorization)
    return {"status": "ok", "bridge": "qmt", "userdata_path": str(os.getenv("QMT_USERDATA_PATH") or "")}


@app.get("/snapshot")
def snapshot(
    account_id: str = Query(...),
    account_type: str = Query("STOCK"),
    account_key: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
):
    _require_token(authorization)
    payload = _query_snapshot(account_id, account_type)
    payload["bridge"] = {
        "mode": "http_bridge",
        "account_key": account_key,
        "account_id": account_id,
    }
    return payload


@app.post("/orders")
def submit_order(body: OrderSubmitRequest, authorization: str | None = Header(default=None)):
    _require_token(authorization)
    payload = _submit_order(body)
    payload["bridge"] = {
        "mode": "http_bridge",
        "account_key": body.account_key,
        "account_id": body.account_id,
    }
    return payload


@app.post("/orders/{order_id}/cancel")
def cancel_order(
    order_id: str,
    account_id: str = Query(...),
    account_type: str = Query("STOCK"),
    account_key: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
):
    _require_token(authorization)
    payload = _cancel_order(account_id, account_type, order_id)
    payload["bridge"] = {
        "mode": "http_bridge",
        "account_key": account_key,
        "account_id": account_id,
    }
    return payload


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("QMT_BRIDGE_HOST", "0.0.0.0")
    port = int(os.getenv("QMT_BRIDGE_PORT", "8710"))
    uvicorn.run(app, host=host, port=port, reload=False)
