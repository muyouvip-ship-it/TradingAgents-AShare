from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.core.stock_map import get_reverse_stock_map
from api.database import SessionLocal, ScheduledAnalysisDB, WatchlistItemDB


logger = logging.getLogger(__name__)

POSITIVE_KEYWORDS = ("利好", "增长", "突破", "中标", "回购", "增持", "涨价", "扩产", "创新高", "超预期", "获批", "签约")
NEGATIVE_KEYWORDS = ("利空", "下滑", "亏损", "减持", "处罚", "调查", "暴跌", "下调", "违约", "风险", "退市", "低于预期")
SECTOR_KEYWORDS = (
    "算力",
    "人工智能",
    "半导体",
    "芯片",
    "新能源",
    "锂电池",
    "光伏",
    "机器人",
    "低空经济",
    "医药",
    "银行",
    "证券",
    "地产",
    "煤炭",
    "有色",
    "军工",
    "汽车",
    "消费电子",
)

_TASK: asyncio.Task | None = None
_STOP_EVENT: asyncio.Event | None = None
_POLL_SECONDS = max(int(os.getenv("NEWS_EYE_POLL_SECONDS", "45")), 15)
_BACKGROUND_LIMIT = max(int(os.getenv("NEWS_EYE_BACKGROUND_LIMIT", "120")), 20)
_MANUAL_LIMIT = max(int(os.getenv("NEWS_EYE_MANUAL_LIMIT", "160")), 20)
_WATCHLIST_SYMBOL_LIMIT = max(int(os.getenv("NEWS_EYE_WATCHLIST_SYMBOL_LIMIT", "12")), 0)
_SYMBOL_SOURCE_LIMIT = max(int(os.getenv("NEWS_EYE_SYMBOL_SOURCE_LIMIT", "6")), 1)
_SYNC_STATE_KEY = "news_eye"


@dataclass(frozen=True)
class NewsSourceSpec:
    label: str
    func_name: str
    kwargs: dict[str, Any] = field(default_factory=dict)
    symbol_param: str | None = None
    symbol_transform: Any | None = None


GENERAL_SOURCE_SPECS: tuple[NewsSourceSpec, ...] = (
    NewsSourceSpec("财联社电报", "stock_info_global_cls", {"symbol": "全部"}),
    NewsSourceSpec("东方财富全球快讯", "stock_info_global_em"),
    NewsSourceSpec("同花顺全球直播", "stock_info_global_ths"),
    NewsSourceSpec("新浪7x24", "stock_info_global_sina"),
    NewsSourceSpec("富途快讯", "stock_info_global_futu"),
    NewsSourceSpec("东方财富财经早餐", "stock_info_cjzc_em"),
)
SYMBOL_SOURCE_SPECS: tuple[NewsSourceSpec, ...] = (
    NewsSourceSpec(
        "东方财富个股新闻",
        "stock_news_em",
        symbol_param="symbol",
        symbol_transform=lambda symbol: str(symbol).split(".", 1)[0],
    ),
)


async def start_background_worker() -> None:
    global _TASK, _STOP_EVENT
    if _TASK and not _TASK.done():
        return
    _STOP_EVENT = asyncio.Event()
    _TASK = asyncio.create_task(_run_loop(), name="news-eye-sync")


async def stop_background_worker() -> None:
    global _TASK, _STOP_EVENT
    if _STOP_EVENT is not None:
        _STOP_EVENT.set()
    if _TASK is not None:
        try:
            await _TASK
        except Exception:
            logger.exception("[news-eye] stop worker failed")
    _TASK = None
    _STOP_EVENT = None


async def _run_loop() -> None:
    logger.info("[news-eye] background worker started")
    while _STOP_EVENT is not None and not _STOP_EVENT.is_set():
        try:
            await asyncio.to_thread(_scan_and_refresh_once)
        except Exception:
            logger.exception("[news-eye] background refresh failed")
        try:
            await asyncio.wait_for(_STOP_EVENT.wait(), timeout=_POLL_SECONDS)
        except asyncio.TimeoutError:
            pass
    logger.info("[news-eye] background worker stopped")


def _scan_and_refresh_once() -> None:
    with SessionLocal() as db:
        ensure_news_tables(db)
        symbols = _load_global_focus_symbols(db, limit=_WATCHLIST_SYMBOL_LIMIT)
        result = refresh_news_cache(
            db,
            limit=_BACKGROUND_LIMIT,
            symbols=symbols,
            trigger="background",
        )
        logger.info(
            "[news-eye] background refresh saved=%s sources=%s symbols=%s warnings=%s",
            result.get("saved", 0),
            ",".join(result.get("active_sources", [])[:8]) or "none",
            ",".join(result.get("tracked_symbols", [])[:8]) or "none",
            len(result.get("warnings", [])),
        )


def ensure_news_tables(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS market_news_items (
                digest VARCHAR(64) PRIMARY KEY,
                content TEXT NOT NULL,
                published_at TIMESTAMP NOT NULL,
                source VARCHAR(80) NOT NULL,
                url TEXT,
                sentiment VARCHAR(20) DEFAULT 'neutral',
                positive_sectors_json TEXT DEFAULT '[]',
                negative_sectors_json TEXT DEFAULT '[]',
                positive_symbols_json TEXT DEFAULT '[]',
                negative_symbols_json TEXT DEFAULT '[]',
                related_symbols_json TEXT DEFAULT '[]',
                fetched_at TIMESTAMP NOT NULL
            )
            """
        )
    )
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_market_news_items_published_at ON market_news_items (published_at DESC)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_market_news_items_source ON market_news_items (source)"))
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS market_news_sync_state (
                worker_name VARCHAR(32) PRIMARY KEY,
                status VARCHAR(20) NOT NULL,
                last_run_at TIMESTAMP,
                last_success_at TIMESTAMP,
                last_error TEXT,
                active_sources_json TEXT DEFAULT '[]',
                tracked_symbols_json TEXT DEFAULT '[]',
                saved_count INTEGER DEFAULT 0,
                updated_at TIMESTAMP NOT NULL
            )
            """
        )
    )
    db.commit()


def list_news_items(
    db: Session,
    *,
    limit: int,
    source: str | None = None,
    sentiment: str | None = None,
    symbol: str | None = None,
    sector: str | None = None,
) -> dict[str, Any]:
    ensure_news_tables(db)
    clauses = ["1=1"]
    params: dict[str, Any] = {"limit": limit}
    if source:
        clauses.append("source = :source")
        params["source"] = source
    if sentiment and sentiment != "all":
        clauses.append("sentiment = :sentiment")
        params["sentiment"] = sentiment
    if symbol:
        clauses.append("related_symbols_json LIKE :symbol")
        params["symbol"] = f"%{symbol.strip().upper()}%"
    if sector:
        clauses.append("(positive_sectors_json LIKE :sector OR negative_sectors_json LIKE :sector)")
        params["sector"] = f"%{sector.strip()}%"

    rows = db.execute(
        text(
            f"""
            SELECT digest, content, published_at, source, url, sentiment,
                   positive_sectors_json, negative_sectors_json, positive_symbols_json, negative_symbols_json,
                   related_symbols_json, fetched_at
            FROM market_news_items
            WHERE {' AND '.join(clauses)}
            ORDER BY published_at DESC, fetched_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    latest_row = db.execute(text("SELECT MAX(fetched_at) AS latest_fetched_at FROM market_news_items")).mappings().first()
    state = _load_sync_state(db)
    updated_at = _iso_or_none(
        (latest_row or {}).get("latest_fetched_at")
        or state.get("last_success_at")
        or _utcnow_naive()
    )
    return {
        "items": [_row_to_news_item(row) for row in rows],
        "total": len(rows),
        "updated_at": updated_at,
        "source": "cache:market_news_items",
        "fallback": False,
        "background": {
            "enabled": True,
            "interval_seconds": _POLL_SECONDS,
            "status": state.get("status") or ("running" if _TASK and not _TASK.done() else "idle"),
            "last_run_at": _iso_or_none(state.get("last_run_at")),
            "last_success_at": _iso_or_none(state.get("last_success_at")),
            "last_error": state.get("last_error"),
            "active_sources": _loads(state.get("active_sources_json")),
            "tracked_symbols": _loads(state.get("tracked_symbols_json")),
            "saved_count": int(state.get("saved_count") or 0),
        },
    }


def refresh_news_cache(
    db: Session,
    *,
    limit: int,
    symbols: list[str] | None = None,
    trigger: str = "manual",
) -> dict[str, Any]:
    ensure_news_tables(db)
    run_started_at = _utcnow_naive()
    symbols = [str(symbol).strip().upper() for symbol in (symbols or []) if str(symbol).strip()]
    try:
        items, active_sources, warnings = _fetch_external_news(limit, symbols=symbols)
        saved = 0
        for item in items:
            enriched = _enrich_news_item(item)
            db.execute(
                text(
                    """
                    INSERT INTO market_news_items (
                        digest, content, published_at, source, url, sentiment,
                        positive_sectors_json, negative_sectors_json, positive_symbols_json, negative_symbols_json,
                        related_symbols_json, fetched_at
                    )
                    VALUES (
                        :digest, :content, :published_at, :source, :url, :sentiment,
                        :positive_sectors_json, :negative_sectors_json, :positive_symbols_json, :negative_symbols_json,
                        :related_symbols_json, :fetched_at
                    )
                    ON CONFLICT (digest) DO UPDATE SET
                        content = EXCLUDED.content,
                        published_at = EXCLUDED.published_at,
                        source = EXCLUDED.source,
                        url = EXCLUDED.url,
                        sentiment = EXCLUDED.sentiment,
                        positive_sectors_json = EXCLUDED.positive_sectors_json,
                        negative_sectors_json = EXCLUDED.negative_sectors_json,
                        positive_symbols_json = EXCLUDED.positive_symbols_json,
                        negative_symbols_json = EXCLUDED.negative_symbols_json,
                        related_symbols_json = EXCLUDED.related_symbols_json,
                        fetched_at = EXCLUDED.fetched_at
                    """
                ),
                enriched,
            )
            saved += 1
        _record_sync_state(
            db,
            status="success" if active_sources else "degraded",
            last_run_at=run_started_at,
            last_success_at=run_started_at if active_sources else None,
            last_error="；".join(warnings[:5]) if warnings else None,
            active_sources=active_sources,
            tracked_symbols=symbols,
            saved_count=saved,
        )
        db.commit()
        return {
            "saved": saved,
            "source": ", ".join(active_sources) if active_sources else "external",
            "fallback": not bool(active_sources),
            "message": "；".join(warnings[:3]) if warnings else f"资讯刷新完成（{trigger}）",
            "updated_at": _iso_or_none(run_started_at),
            "active_sources": active_sources,
            "tracked_symbols": symbols,
            "warnings": warnings,
        }
    except Exception as exc:
        _record_sync_state(
            db,
            status="error",
            last_run_at=run_started_at,
            last_success_at=None,
            last_error=str(exc),
            active_sources=[],
            tracked_symbols=symbols,
            saved_count=0,
        )
        db.commit()
        raise


def load_user_focus_symbols(db: Session, user_id: str, *, limit: int = _WATCHLIST_SYMBOL_LIMIT) -> list[str]:
    symbols: list[str] = []
    seen: set[str] = set()

    watchlist_rows = (
        db.query(WatchlistItemDB.symbol)
        .filter(WatchlistItemDB.user_id == user_id)
        .order_by(WatchlistItemDB.created_at.desc())
        .all()
    )
    scheduled_rows = (
        db.query(ScheduledAnalysisDB.symbol)
        .filter(ScheduledAnalysisDB.user_id == user_id)
        .order_by(ScheduledAnalysisDB.created_at.desc())
        .all()
    )
    for row in list(watchlist_rows) + list(scheduled_rows):
        symbol = str(row[0] or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
        if len(symbols) >= limit:
            break
    return symbols


def _load_global_focus_symbols(db: Session, *, limit: int) -> list[str]:
    if limit <= 0:
        return []
    symbols: list[str] = []
    seen: set[str] = set()
    rows = (
        db.query(WatchlistItemDB.symbol)
        .order_by(WatchlistItemDB.created_at.desc())
        .limit(limit * 3)
        .all()
    )
    scheduled_rows = (
        db.query(ScheduledAnalysisDB.symbol)
        .order_by(ScheduledAnalysisDB.created_at.desc())
        .limit(limit * 3)
        .all()
    )
    for row in list(rows) + list(scheduled_rows):
        symbol = str(row[0] or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
        if len(symbols) >= limit:
            break
    return symbols


def _fetch_external_news(limit: int, *, symbols: list[str]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    import akshare as ak

    items: list[dict[str, Any]] = []
    active_sources: list[str] = []
    warnings: list[str] = []
    per_source_limit = max(10, min(limit, 60))

    for spec in GENERAL_SOURCE_SPECS:
        func = getattr(ak, spec.func_name, None)
        if func is None:
            warnings.append(f"{spec.label} 接口不存在")
            continue
        try:
            frame = func(**spec.kwargs)
            normalized = _normalize_news_frame(frame, spec.label, limit=per_source_limit)
            if normalized:
                items.extend(normalized)
                active_sources.append(spec.label)
            else:
                warnings.append(f"{spec.label} 暂无数据")
        except Exception as exc:
            warnings.append(f"{spec.label} 拉取失败: {exc}")

    for symbol in symbols[:_WATCHLIST_SYMBOL_LIMIT]:
        for spec in SYMBOL_SOURCE_SPECS:
            func = getattr(ak, spec.func_name, None)
            if func is None or spec.symbol_param is None:
                continue
            call_kwargs = dict(spec.kwargs)
            transformed_symbol = spec.symbol_transform(symbol) if callable(spec.symbol_transform) else symbol
            call_kwargs[spec.symbol_param] = transformed_symbol
            try:
                frame = func(**call_kwargs)
                normalized = _normalize_news_frame(
                    frame,
                    spec.label,
                    limit=_SYMBOL_SOURCE_LIMIT,
                    seed_symbols=[symbol],
                )
                if normalized:
                    items.extend(normalized)
                    active_label = f"{spec.label}:{symbol}"
                    if active_label not in active_sources:
                        active_sources.append(active_label)
            except Exception as exc:
                warnings.append(f"{spec.label}({symbol}) 拉取失败: {exc}")

    return _dedupe_items(items)[: max(limit, 20)], active_sources, warnings


def _normalize_news_frame(
    frame: Any,
    source_name: str,
    *,
    limit: int,
    seed_symbols: list[str] | None = None,
) -> list[dict[str, Any]]:
    if frame is None:
        return []
    data = pd.DataFrame(frame)
    if data.empty:
        return []
    items: list[dict[str, Any]] = []
    for _, row in data.head(limit).iterrows():
        title = _first_text(row, ("标题", "title", "新闻标题"))
        body = _first_text(row, ("内容", "摘要", "summary", "digest", "rich_text", "content", "正文"))
        content = body or title
        if title and body and title not in body:
            content = f"{title}；{body}"
        if not content:
            continue
        published_at = _parse_time_from_row(row)
        source = _first_text(row, ("来源", "媒体", "source")) or source_name
        url = _first_text(row, ("链接", "url", "URL", "uniqueUrl", "detailUrl"))
        items.append(
            {
                "content": content,
                "published_at": published_at,
                "source": source,
                "url": url or None,
                "seed_symbols": list(seed_symbols or []),
            }
        )
    return items


def _first_text(row: Any, keys: tuple[str, ...]) -> str:
    for key in keys:
        if key in row and pd.notna(row[key]):
            value = str(row[key]).strip()
            if value and value.lower() != "nan":
                return value
    return ""


def _parse_time_from_row(row: Any) -> str:
    if "发布日期" in row and "发布时间" in row and pd.notna(row["发布日期"]) and pd.notna(row["发布时间"]):
        combined = f"{row['发布日期']} {row['发布时间']}"
        return _parse_time(str(combined))
    return _parse_time(
        _first_text(row, ("发布时间", "时间", "发布日期", "datetime", "time", "date", "showTime", "create_time"))
    )


def _parse_time(value: str) -> str:
    if not value:
        return _iso_or_none(_utcnow_naive())
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return _iso_or_none(_utcnow_naive())
    return parsed.to_pydatetime().replace(tzinfo=None).isoformat()


def _dedupe_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_key: dict[str, dict[str, Any]] = {}
    for item in items:
        key = _news_identity_key(item)
        existing = best_by_key.get(key)
        if existing is None:
            best_by_key[key] = item
            continue
        if str(item.get("published_at") or "") > str(existing.get("published_at") or ""):
            best_by_key[key] = item
    return sorted(
        best_by_key.values(),
        key=lambda item: (str(item.get("published_at") or ""), str(item.get("source") or "")),
        reverse=True,
    )


def _news_identity_key(item: dict[str, Any]) -> str:
    url = str(item.get("url") or "").strip()
    if url:
        return f"url:{url}"
    content = " ".join(str(item.get("content") or "").split())
    published_at = str(item.get("published_at") or "")[:16]
    return f"text:{hashlib.sha256(f'{content}|{published_at}'.encode('utf-8')).hexdigest()}"


def _enrich_news_item(item: dict[str, Any]) -> dict[str, Any]:
    content = str(item.get("content") or "").strip()
    sentiment = _classify_sentiment(content)
    sectors = [sector for sector in SECTOR_KEYWORDS if sector in content]
    symbols = _merge_symbols(_extract_symbols(content), item.get("seed_symbols") or [])
    positive_sectors = sectors if sentiment == "positive" else []
    negative_sectors = sectors if sentiment == "negative" else []
    positive_symbols = symbols if sentiment == "positive" else []
    negative_symbols = symbols if sentiment == "negative" else []
    digest = _make_news_digest(item)
    return {
        "digest": digest,
        "content": content,
        "published_at": item.get("published_at") or _iso_or_none(_utcnow_naive()),
        "source": item.get("source") or "未知来源",
        "url": item.get("url"),
        "sentiment": sentiment,
        "positive_sectors_json": json.dumps(positive_sectors, ensure_ascii=False),
        "negative_sectors_json": json.dumps(negative_sectors, ensure_ascii=False),
        "positive_symbols_json": json.dumps(symbols_to_payload(positive_symbols), ensure_ascii=False),
        "negative_symbols_json": json.dumps(symbols_to_payload(negative_symbols), ensure_ascii=False),
        "related_symbols_json": json.dumps(symbols_to_payload(symbols), ensure_ascii=False),
        "fetched_at": _iso_or_none(_utcnow_naive()),
    }


def _classify_sentiment(content: str) -> str:
    positive_count = sum(1 for keyword in POSITIVE_KEYWORDS if keyword in content)
    negative_count = sum(1 for keyword in NEGATIVE_KEYWORDS if keyword in content)
    if positive_count > negative_count:
        return "positive"
    if negative_count > positive_count:
        return "negative"
    return "neutral"


def _extract_symbols(content: str) -> list[str]:
    code_to_name = get_reverse_stock_map()
    hits: list[str] = []
    for symbol, name in code_to_name.items():
        code = symbol.split(".", 1)[0]
        if code in content or (name and name in content):
            hits.append(symbol)
        if len(hits) >= 8:
            break
    return hits


def _merge_symbols(primary: Iterable[str], extra: Iterable[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for raw in list(primary) + list(extra):
        symbol = str(raw or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        merged.append(symbol)
    return merged[:8]


def symbols_to_payload(symbols: list[str]) -> list[dict[str, str]]:
    code_to_name = get_reverse_stock_map()
    return [{"symbol": symbol, "name": code_to_name.get(symbol, symbol)} for symbol in symbols]


def _row_to_news_item(row: Any) -> dict[str, Any]:
    return {
        "id": row["digest"],
        "content": row["content"],
        "published_at": _iso_or_none(row["published_at"]),
        "source": row["source"],
        "url": row["url"],
        "sentiment": row["sentiment"],
        "positive_sectors": _loads(row["positive_sectors_json"]),
        "negative_sectors": _loads(row["negative_sectors_json"]),
        "positive_symbols": _loads(row["positive_symbols_json"]),
        "negative_symbols": _loads(row["negative_symbols_json"]),
        "related_symbols": _loads(row["related_symbols_json"]),
        "fetched_at": _iso_or_none(row["fetched_at"]),
    }


def _make_news_digest(item: dict[str, Any]) -> str:
    url = str(item.get("url") or "").strip()
    if url:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()
    normalized_content = " ".join(str(item.get("content") or "").split())
    published_at = str(item.get("published_at") or "")[:16]
    return hashlib.sha256(f"{normalized_content}|{published_at}".encode("utf-8")).hexdigest()


def _record_sync_state(
    db: Session,
    *,
    status: str,
    last_run_at: datetime | None,
    last_success_at: datetime | None,
    last_error: str | None,
    active_sources: list[str],
    tracked_symbols: list[str],
    saved_count: int,
) -> None:
    db.execute(
        text(
            """
            INSERT INTO market_news_sync_state (
                worker_name, status, last_run_at, last_success_at, last_error,
                active_sources_json, tracked_symbols_json, saved_count, updated_at
            )
            VALUES (
                :worker_name, :status, :last_run_at, :last_success_at, :last_error,
                :active_sources_json, :tracked_symbols_json, :saved_count, :updated_at
            )
            ON CONFLICT (worker_name) DO UPDATE SET
                status = EXCLUDED.status,
                last_run_at = EXCLUDED.last_run_at,
                last_success_at = COALESCE(EXCLUDED.last_success_at, market_news_sync_state.last_success_at),
                last_error = EXCLUDED.last_error,
                active_sources_json = EXCLUDED.active_sources_json,
                tracked_symbols_json = EXCLUDED.tracked_symbols_json,
                saved_count = EXCLUDED.saved_count,
                updated_at = EXCLUDED.updated_at
            """
        ),
        {
            "worker_name": _SYNC_STATE_KEY,
            "status": status,
            "last_run_at": last_run_at,
            "last_success_at": last_success_at,
            "last_error": last_error,
            "active_sources_json": json.dumps(active_sources, ensure_ascii=False),
            "tracked_symbols_json": json.dumps(tracked_symbols, ensure_ascii=False),
            "saved_count": int(saved_count or 0),
            "updated_at": _utcnow_naive(),
        },
    )


def _load_sync_state(db: Session) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            SELECT worker_name, status, last_run_at, last_success_at, last_error,
                   active_sources_json, tracked_symbols_json, saved_count, updated_at
            FROM market_news_sync_state
            WHERE worker_name = :worker_name
            """
        ),
        {"worker_name": _SYNC_STATE_KEY},
    ).mappings().first()
    return dict(row) if row else {}


def _loads(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
