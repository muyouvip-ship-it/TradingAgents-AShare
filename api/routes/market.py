from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from api.core.http_utils import get_real_ip
from api.core.stock_map import get_reverse_stock_map
from api.core.stock_utils import normalize_symbol, search_cn_stock_by_name
from api.deps import require_api_user

router = APIRouter(prefix="/v1/market", tags=["Market"])


@router.get("/stock-search")
def search_stocks(
    q: str = Query("", min_length=1, max_length=20),
    current_user=Depends(require_api_user),
):
    q = q.strip()
    if not q:
        return {"results": []}

    code_to_name = get_reverse_stock_map()
    results = []
    q_upper = q.upper()

    for code, name in code_to_name.items():
        if q in name or q_upper in code.upper() or q in code:
            results.append({"symbol": code, "name": name, "source": "cache"})

    if not results:
        found = search_cn_stock_by_name(q)
        if found:
            results.append({"symbol": found, "name": code_to_name.get(found, q), "source": "akshare"})

    return {"results": results[:20]}


@router.get("/kline")
def get_kline(symbol: str, start_date: str, end_date: str):
    normalized = normalize_symbol(symbol)
    return {
        "symbol": normalized,
        "start_date": start_date,
        "end_date": end_date,
        "candles": [],
        "source_ip": None,
    }


@router.get("/hot-stocks")
def get_hot_stocks(source: str = "em", limit: int = 30) -> Dict:
    if limit <= 0:
        raise HTTPException(status_code=400, detail="limit must be positive")
    return {"source": source, "limit": limit, "items": [], "fallback": True}
