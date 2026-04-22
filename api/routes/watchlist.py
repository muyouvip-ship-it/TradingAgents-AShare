from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from api.database import get_db
from api.deps import require_api_user
from api.services import watchlist_service

router = APIRouter(prefix="/v1", tags=["Watchlist"])


@router.get("/watchlist")
def list_watchlist(current_user=Depends(require_api_user), db: Session = Depends(get_db)):
    from api import main as compat

    items = watchlist_service.list_watchlist(db, current_user.id)
    return {"items": compat._attach_stock_names(items, compat._get_reverse_stock_map_cached_only())}


@router.post("/watchlist")
def add_to_watchlist(
    body: dict = Body(...),
    current_user=Depends(require_api_user),
    db: Session = Depends(get_db),
):
    from api import main as compat

    text = str(body.get("text") or body.get("symbol") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text or symbol is required")
    tokens = compat.split_watchlist_batch_text(text)
    if not tokens:
        raise HTTPException(status_code=400, detail="至少提供一个股票代码或名称")

    name_to_code = compat._load_cn_stock_map()
    code_to_name = compat._get_reverse_stock_map()
    resolved_entries: list[dict] = []
    results: list[dict] = []
    for idx, token in enumerate(tokens):
        symbol, name, error = compat.resolve_watchlist_identifier(token, name_to_code, code_to_name)
        if error:
            results.append({"_order": idx, "input": token, "status": "invalid", "message": error})
            continue
        resolved_entries.append({"_order": idx, "input": token, "symbol": symbol, "name": name})

    add_results = watchlist_service.add_watchlist_items(db, current_user.id, [entry["symbol"] for entry in resolved_entries])
    for entry, result in zip(resolved_entries, add_results):
        item = result.get("item")
        if item:
            item["name"] = entry["name"]
            item["has_scheduled"] = False
        results.append(
            {
                "_order": entry["_order"],
                "input": entry["input"],
                "symbol": entry["symbol"],
                "name": entry["name"],
                "status": result["status"],
                "message": result["message"],
                "item": item,
            }
        )

    results.sort(key=lambda row: row["_order"])
    for row in results:
        row.pop("_order", None)
    summary = {
        "total": len(tokens),
        "added": sum(1 for row in results if row["status"] == "added"),
        "duplicate": sum(1 for row in results if row["status"] == "duplicate"),
        "failed": sum(1 for row in results if row["status"] in {"invalid", "failed"}),
    }
    return {"summary": summary, "results": results}


@router.delete("/watchlist/{item_id}", status_code=204)
def delete_from_watchlist(item_id: str, current_user=Depends(require_api_user), db: Session = Depends(get_db)):
    if not watchlist_service.delete_watchlist_item(db, current_user.id, item_id):
        raise HTTPException(status_code=404, detail="未找到该自选股")
