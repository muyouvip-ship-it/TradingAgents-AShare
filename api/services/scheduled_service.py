"""Scheduled analysis service for database operations."""

from __future__ import annotations

from typing import Iterable, List, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from api.database import ScheduledAnalysisDB

MAX_SCHEDULED_ITEMS = 10
VALID_HORIZONS = {"short", "medium"}


def _validate_trigger_time(t: str) -> str:
    parts = t.strip().split(":")
    if len(parts) != 2:
        raise ValueError("时间格式错误，请使用 HH:MM")
    try:
        hh, mm = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError("时间格式错误，请使用 HH:MM") from exc
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError("时间格式错误，请使用 HH:MM")
    time_val = hh * 60 + mm
    if 8 * 60 < time_val < 20 * 60:
        raise ValueError("定时时间仅允许 20:00~次日 08:00（避免影响白天使用）")
    return f"{hh:02d}:{mm:02d}"


def _normalize_item_ids(item_ids: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_id in item_ids:
        item_id = (raw_id or "").strip()
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        normalized.append(item_id)
    return normalized


def _validate_horizon(horizon: str) -> str:
    if horizon not in VALID_HORIZONS:
        raise ValueError("horizon 必须为 short 或 medium")
    return horizon


def _to_dict(item: ScheduledAnalysisDB) -> dict:
    return {
        "id": item.id,
        "user_id": item.user_id,
        "symbol": item.symbol,
        "horizon": item.horizon,
        "trigger_time": item.trigger_time,
        "is_active": bool(item.is_active),
        "last_run_date": item.last_run_date,
        "last_run_status": item.last_run_status,
        "last_report_id": item.last_report_id,
        "consecutive_failures": int(item.consecutive_failures or 0),
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _apply_scheduled_updates(item: ScheduledAnalysisDB, **kwargs) -> None:
    if "is_active" in kwargs:
        item.is_active = kwargs["is_active"]
        if kwargs["is_active"]:
            item.consecutive_failures = 0
    if "horizon" in kwargs:
        item.horizon = _validate_horizon(kwargs["horizon"])
    if "trigger_time" in kwargs:
        item.trigger_time = _validate_trigger_time(kwargs["trigger_time"])


def list_scheduled(db: Session, user_id: str) -> List[dict]:
    items = (
        db.query(ScheduledAnalysisDB)
        .filter(ScheduledAnalysisDB.user_id == user_id)
        .order_by(ScheduledAnalysisDB.created_at)
        .all()
    )
    return [_to_dict(item) for item in items]


def get_scheduled(db: Session, user_id: str, item_id: str) -> Optional[dict]:
    item = (
        db.query(ScheduledAnalysisDB)
        .filter(ScheduledAnalysisDB.user_id == user_id, ScheduledAnalysisDB.id == item_id)
        .first()
    )
    if not item:
        return None
    return _to_dict(item)


def get_scheduled_batch(db: Session, user_id: str, item_ids: Iterable[str]) -> List[dict]:
    normalized_ids = _normalize_item_ids(item_ids)
    if not normalized_ids:
        raise ValueError("请至少选择一个定时任务")

    items = (
        db.query(ScheduledAnalysisDB)
        .filter(
            ScheduledAnalysisDB.user_id == user_id,
            ScheduledAnalysisDB.id.in_(normalized_ids),
        )
        .all()
    )
    item_map = {item.id: item for item in items}
    missing_ids = [item_id for item_id in normalized_ids if item_id not in item_map]
    if missing_ids:
        raise ValueError("部分定时任务不存在或已失效，请刷新后重试")
    return [_to_dict(item_map[item_id]) for item_id in normalized_ids]


def create_scheduled(
    db: Session,
    user_id: str,
    symbol: str,
    horizon: str = "short",
    trigger_time: str = "20:00",
) -> dict:
    count = db.query(ScheduledAnalysisDB).filter(ScheduledAnalysisDB.user_id == user_id).count()
    if count >= MAX_SCHEDULED_ITEMS:
        raise ValueError(f"定时分析数量已达上限 ({MAX_SCHEDULED_ITEMS})")

    existing = (
        db.query(ScheduledAnalysisDB)
        .filter(ScheduledAnalysisDB.user_id == user_id, ScheduledAnalysisDB.symbol == symbol)
        .first()
    )
    if existing:
        raise ValueError(f"{symbol} 已有定时分析任务")

    item = ScheduledAnalysisDB(
        id=uuid4().hex,
        user_id=user_id,
        symbol=symbol,
        horizon=_validate_horizon(horizon),
        trigger_time=_validate_trigger_time(trigger_time),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _to_dict(item)


def ensure_scheduled_for_symbols(
    db: Session,
    user_id: str,
    symbols: Iterable[str],
    horizon: str = "short",
    trigger_time: str = "20:00",
) -> dict:
    horizon = _validate_horizon(horizon)
    trigger_time = _validate_trigger_time(trigger_time)

    existing_items = (
        db.query(ScheduledAnalysisDB)
        .filter(ScheduledAnalysisDB.user_id == user_id)
        .order_by(ScheduledAnalysisDB.created_at)
        .all()
    )
    existing_symbols = {item.symbol for item in existing_items}
    remaining_slots = max(0, MAX_SCHEDULED_ITEMS - len(existing_items))

    created: list[str] = []
    existing: list[str] = []
    skipped_limit: list[str] = []
    seen: set[str] = set()

    for raw_symbol in symbols:
        symbol = (raw_symbol or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)

        if symbol in existing_symbols:
            existing.append(symbol)
            continue

        if remaining_slots <= 0:
            skipped_limit.append(symbol)
            continue

        db.add(
            ScheduledAnalysisDB(
                id=uuid4().hex,
                user_id=user_id,
                symbol=symbol,
                horizon=horizon,
                trigger_time=trigger_time,
            )
        )
        existing_symbols.add(symbol)
        created.append(symbol)
        remaining_slots -= 1

    if created:
        db.commit()

    return {"created": created, "existing": existing, "skipped_limit": skipped_limit}


def update_scheduled(db: Session, user_id: str, item_id: str, **kwargs) -> Optional[dict]:
    item = (
        db.query(ScheduledAnalysisDB)
        .filter(ScheduledAnalysisDB.id == item_id, ScheduledAnalysisDB.user_id == user_id)
        .first()
    )
    if not item:
        return None

    _apply_scheduled_updates(item, **kwargs)
    db.commit()
    db.refresh(item)
    return _to_dict(item)


def batch_update_scheduled(db: Session, user_id: str, item_ids: Iterable[str], **kwargs) -> List[dict]:
    normalized_ids = _normalize_item_ids(item_ids)
    if not normalized_ids:
        raise ValueError("请至少选择一个定时任务")
    if not kwargs:
        raise ValueError("至少提供一个更新字段")

    items = (
        db.query(ScheduledAnalysisDB)
        .filter(
            ScheduledAnalysisDB.user_id == user_id,
            ScheduledAnalysisDB.id.in_(normalized_ids),
        )
        .all()
    )
    item_map = {item.id: item for item in items}
    missing_ids = [item_id for item_id in normalized_ids if item_id not in item_map]
    if missing_ids:
        raise ValueError("部分定时任务不存在或已失效，请刷新后重试")

    for item_id in normalized_ids:
        _apply_scheduled_updates(item_map[item_id], **kwargs)

    db.commit()
    for item in items:
        db.refresh(item)
    return [_to_dict(item_map[item_id]) for item_id in normalized_ids]


def get_pending_tasks(db: Session, today: str, current_hhmm: str) -> List[ScheduledAnalysisDB]:
    all_active = (
        db.query(ScheduledAnalysisDB)
        .filter(
            ScheduledAnalysisDB.is_active == True,
            (ScheduledAnalysisDB.last_run_date != today) | (ScheduledAnalysisDB.last_run_date == None),
        )
        .all()
    )
    return [task for task in all_active if (task.trigger_time or "20:00") <= current_hhmm]


def mark_run_success(db: Session, item_id: str, trade_date: str, report_id: str):
    item = db.query(ScheduledAnalysisDB).filter(ScheduledAnalysisDB.id == item_id).first()
    if item:
        item.last_run_date = trade_date
        item.last_run_status = "success"
        item.last_report_id = report_id
        item.consecutive_failures = 0
        db.commit()


def mark_run_failed(db: Session, item_id: str, trade_date: str):
    item = db.query(ScheduledAnalysisDB).filter(ScheduledAnalysisDB.id == item_id).first()
    if item:
        item.last_run_date = trade_date
        item.last_run_status = "failed"
        item.consecutive_failures = int(item.consecutive_failures or 0) + 1
        if item.consecutive_failures >= 3:
            item.is_active = False
        db.commit()


def record_manual_test_result(db: Session, item_id: str, status: str, report_id: str):
    item = db.query(ScheduledAnalysisDB).filter(ScheduledAnalysisDB.id == item_id).first()
    if item:
        item.last_run_status = status
        item.last_report_id = report_id
        item.last_run_date = None
        db.commit()


def delete_scheduled(db: Session, user_id: str, item_id: str) -> bool:
    item = (
        db.query(ScheduledAnalysisDB)
        .filter(ScheduledAnalysisDB.id == item_id, ScheduledAnalysisDB.user_id == user_id)
        .first()
    )
    if not item:
        return False
    db.delete(item)
    db.commit()
    return True


def batch_delete_scheduled(db: Session, user_id: str, item_ids: Iterable[str]) -> dict:
    normalized_ids = _normalize_item_ids(item_ids)
    if not normalized_ids:
        raise ValueError("请至少选择一个定时任务")

    items = (
        db.query(ScheduledAnalysisDB)
        .filter(
            ScheduledAnalysisDB.user_id == user_id,
            ScheduledAnalysisDB.id.in_(normalized_ids),
        )
        .all()
    )
    item_map = {item.id: item for item in items}
    deleted_ids: list[str] = []
    missing_ids: list[str] = []

    for item_id in normalized_ids:
        item = item_map.get(item_id)
        if item is None:
            missing_ids.append(item_id)
            continue
        db.delete(item)
        deleted_ids.append(item_id)

    if deleted_ids:
        db.commit()

    return {"deleted_ids": deleted_ids, "missing_ids": missing_ids}
