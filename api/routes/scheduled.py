from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from api.database import get_db
from api.deps import require_api_user
from api.schemas.analysis import AnalyzeResponse
from api.services import portfolio_import_service, reports_service, scheduled_service, watchlist_service

router = APIRouter(prefix="/v1", tags=["Scheduled"])


@router.get("/scheduled")
def list_scheduled_analyses(current_user=Depends(require_api_user), db: Session = Depends(get_db)):
    from api import main as compat

    items = scheduled_service.list_scheduled(db, current_user.id)
    compat._attach_stock_names(items, compat._get_reverse_stock_map_cached_only())
    return {"items": compat._annotate_scheduled_with_imported_context(items, db, current_user.id)}


@router.get("/portfolio/overview")
def get_portfolio_overview(current_user=Depends(require_api_user), db: Session = Depends(get_db)):
    from api import main as compat

    code_to_name = compat._get_reverse_stock_map()
    watchlist_items = watchlist_service.list_watchlist(db, current_user.id)
    compat._attach_stock_names(watchlist_items, code_to_name)
    scheduled_items = scheduled_service.list_scheduled(db, current_user.id)
    compat._attach_stock_names(scheduled_items, code_to_name)
    compat._annotate_scheduled_with_imported_context(scheduled_items, db, current_user.id)
    latest_reports = reports_service.get_latest_reports_by_symbols(
        db,
        user_id=current_user.id,
        symbols=[item["symbol"] for item in watchlist_items],
    )
    for report in latest_reports:
        report["name"] = code_to_name.get(report["symbol"], report["symbol"])
    return {
        "watchlist": watchlist_items,
        "scheduled": scheduled_items,
        "latest_reports": latest_reports,
        "portfolio_import": portfolio_import_service.get_import_state(db, current_user.id),
    }


@router.post("/scheduled", status_code=201)
def create_scheduled_analysis(body: dict = Body(...), current_user=Depends(require_api_user), db: Session = Depends(get_db)):
    from api import main as compat

    symbol = str(body.get("symbol") or "").strip().upper()
    horizon = str(body.get("horizon") or "short")
    trigger_time = str(body.get("trigger_time") or "20:00")
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required")
    code_to_name = compat._get_reverse_stock_map()
    if code_to_name and symbol not in code_to_name:
        raise HTTPException(status_code=400, detail=f"未知的股票代码: {symbol}")
    try:
        item = scheduled_service.create_scheduled(db, current_user.id, symbol, horizon, trigger_time)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    item["name"] = code_to_name.get(symbol, symbol)
    compat._annotate_scheduled_with_imported_context([item], db, current_user.id)
    return item


@router.patch("/scheduled/batch")
def batch_update_scheduled_analyses(body: dict = Body(...), current_user=Depends(require_api_user), db: Session = Depends(get_db)):
    from api import main as compat

    kwargs = compat._extract_scheduled_update_kwargs(body)
    if not kwargs:
        raise HTTPException(status_code=400, detail="至少提供一个更新字段")
    try:
        items = scheduled_service.batch_update_scheduled(db, current_user.id, body.get("item_ids") or [], **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    code_to_name = compat._get_reverse_stock_map()
    for item in items:
        item["name"] = code_to_name.get(item["symbol"], item["symbol"])
    return {"items": compat._annotate_scheduled_with_imported_context(items, db, current_user.id)}


@router.post("/scheduled/batch/delete")
def batch_delete_scheduled_analyses(body: dict = Body(...), current_user=Depends(require_api_user), db: Session = Depends(get_db)):
    try:
        return scheduled_service.batch_delete_scheduled(db, current_user.id, body.get("item_ids") or [])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/scheduled/batch/trigger")
async def trigger_scheduled_analyses_batch(body: dict = Body(...), current_user=Depends(require_api_user), db: Session = Depends(get_db)):
    from api import main as compat

    item_ids = body.get("item_ids") or []
    if not item_ids:
        raise HTTPException(status_code=400, detail="请至少选择 1 个定时任务")
    available_tasks = {task["id"]: task for task in scheduled_service.list_scheduled(db, current_user.id)}
    code_to_name = compat._get_reverse_stock_map()
    requested_trade_date = compat.cn_today_str()
    actual_trade_date = compat._resolve_scheduled_trade_date(requested_trade_date)
    jobs: list[dict] = []
    with_position_context = 0
    for item_id in item_ids:
        task = available_tasks.get(str(item_id))
        if not task:
            continue
        task_snapshot = dict(task)
        task_snapshot["user_id"] = current_user.id
        task_snapshot["manual_user_context"] = compat._build_manual_imported_user_context(db, current_user.id, task["symbol"])
        if task_snapshot["manual_user_context"].get("current_position") is not None:
            with_position_context += 1
        job_id = f"{datetime.now().timestamp():.0f}".replace(".", "")[-16:] + task["id"][-8:]
        compat._set_job(job_id, user_id=current_user.id, status="pending", symbol=task["symbol"], trade_date=actual_trade_date)
        compat._create_tracked_task(compat._run_scheduled_analysis_once(task_snapshot, requested_trade_date, job_id, mark_schedule_run=False))
        jobs.append(
            {
                "item_id": task["id"],
                "job_id": job_id,
                "symbol": task["symbol"],
                "name": code_to_name.get(task["symbol"], task["symbol"]),
                "status": "pending",
                "created_at": datetime.now().isoformat(),
                "current_position": task_snapshot["manual_user_context"].get("current_position"),
                "average_cost": task_snapshot["manual_user_context"].get("average_cost"),
            }
        )
    return {"summary": {"total": len(jobs), "with_position_context": with_position_context}, "jobs": jobs}


@router.post("/scheduled/{item_id}/trigger", response_model=AnalyzeResponse)
async def trigger_scheduled_analysis_once(item_id: str, current_user=Depends(require_api_user), db: Session = Depends(get_db)):
    from api import main as compat

    task = scheduled_service.get_scheduled(db, current_user.id, item_id)
    if task is None:
        raise HTTPException(status_code=404, detail="未找到该定时任务")
    requested_trade_date = compat.cn_today_str()
    actual_trade_date = compat._resolve_scheduled_trade_date(requested_trade_date)
    job_id = f"{datetime.now().timestamp():.0f}".replace(".", "")[-16:] + item_id[-8:]
    task_snapshot = dict(task)
    task_snapshot["user_id"] = current_user.id
    task_snapshot["manual_user_context"] = compat._build_manual_imported_user_context(db, current_user.id, task["symbol"])
    compat._set_job(job_id, user_id=current_user.id, status="pending", symbol=task["symbol"], trade_date=actual_trade_date)
    compat._create_tracked_task(compat._run_scheduled_analysis_once(task_snapshot, requested_trade_date, job_id, mark_schedule_run=False))
    return {"job_id": job_id, "status": "pending"}


@router.patch("/scheduled/{item_id}")
def update_scheduled_analysis(item_id: str, body: dict = Body(...), current_user=Depends(require_api_user), db: Session = Depends(get_db)):
    from api import main as compat

    kwargs = compat._extract_scheduled_update_kwargs(body)
    try:
        result = scheduled_service.update_scheduled(db, current_user.id, item_id, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="未找到该定时任务")
    code_to_name = compat._get_reverse_stock_map()
    result["name"] = code_to_name.get(result["symbol"], result["symbol"])
    compat._annotate_scheduled_with_imported_context([result], db, current_user.id)
    return result


@router.delete("/scheduled/{item_id}", status_code=204)
def delete_scheduled_analysis(item_id: str, current_user=Depends(require_api_user), db: Session = Depends(get_db)):
    if not scheduled_service.delete_scheduled(db, current_user.id, item_id):
        raise HTTPException(status_code=404, detail="未找到该定时任务")
