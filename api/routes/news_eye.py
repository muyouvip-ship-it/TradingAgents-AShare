from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.core.stock_map import get_reverse_stock_map
from api.database import get_db
from api.deps import require_api_user

router = APIRouter(prefix="/v1/news-eye", tags=["News Eye"])

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


@router.get("/items")
def list_news_items(
    limit: int = Query(50, ge=1, le=200),
    source: str | None = Query(None),
    sentiment: str | None = Query(None),
    symbol: str | None = Query(None),
    sector: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_api_user),
) -> dict[str, Any]:
    del current_user
    _ensure_news_tables(db)
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
                   positive_sectors_json, negative_sectors_json, positive_symbols_json, negative_symbols_json, related_symbols_json,
                   fetched_at
            FROM market_news_items
            WHERE {' AND '.join(clauses)}
            ORDER BY published_at DESC, fetched_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    return {
        "items": [_row_to_news_item(row) for row in rows],
        "total": len(rows),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "cache:market_news_items",
        "fallback": False,
    }


@router.post("/refresh")
def refresh_news_items(
    limit: int = Query(80, ge=10, le=300),
    db: Session = Depends(get_db),
    current_user=Depends(require_api_user),
) -> dict[str, Any]:
    del current_user
    _ensure_news_tables(db)
    items, source, fallback_reason = _fetch_external_news(limit)
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
    db.commit()
    return {
        "saved": saved,
        "source": source,
        "fallback": bool(fallback_reason),
        "message": fallback_reason or "资讯刷新完成",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _ensure_news_tables(db: Session) -> None:
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
    db.commit()


def _fetch_external_news(limit: int) -> tuple[list[dict[str, Any]], str, str | None]:
    try:
        import akshare as ak

        candidates = [
            ("财联社电报", "stock_info_global_cls", {}),
            ("东方财富财经", "stock_info_cjzc_em", {}),
        ]
        for source_name, func_name, kwargs in candidates:
            func = getattr(ak, func_name, None)
            if func is None:
                continue
            try:
                frame = func(**kwargs)
                items = _normalize_news_frame(frame, source_name, limit)
                if items:
                    return items, source_name, None
            except Exception:
                continue
        return [], "external", "外部资讯源暂无可用数据，已保留缓存列表。"
    except Exception as exc:
        return [], "external", f"外部资讯源不可用：{exc}"


def _normalize_news_frame(frame: Any, source_name: str, limit: int) -> list[dict[str, Any]]:
    if frame is None:
        return []
    data = pd.DataFrame(frame)
    if data.empty:
        return []
    items = []
    for _, row in data.head(limit).iterrows():
        content = _first_text(row, ("内容", "标题", "新闻标题", "摘要", "title", "content"))
        if not content:
            continue
        published_at = _parse_time(_first_text(row, ("发布时间", "时间", "发布日期", "datetime", "time", "date")))
        source = _first_text(row, ("来源", "媒体", "source")) or source_name
        url = _first_text(row, ("链接", "url", "URL"))
        items.append({"content": content, "published_at": published_at, "source": source, "url": url})
    return items


def _first_text(row: Any, keys: tuple[str, ...]) -> str:
    for key in keys:
        if key in row and pd.notna(row[key]):
            value = str(row[key]).strip()
            if value and value.lower() != "nan":
                return value
    return ""


def _parse_time(value: str) -> str:
    if not value:
        return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    return parsed.to_pydatetime().replace(tzinfo=None).isoformat()


def _enrich_news_item(item: dict[str, Any]) -> dict[str, Any]:
    content = str(item.get("content") or "").strip()
    sentiment = _classify_sentiment(content)
    sectors = [sector for sector in SECTOR_KEYWORDS if sector in content]
    symbols = _extract_symbols(content)
    positive_sectors = sectors if sentiment == "positive" else []
    negative_sectors = sectors if sentiment == "negative" else []
    positive_symbols = symbols if sentiment == "positive" else []
    negative_symbols = symbols if sentiment == "negative" else []
    digest = hashlib.sha256(f"{item.get('source')}|{item.get('published_at')}|{content}".encode("utf-8")).hexdigest()
    return {
        "digest": digest,
        "content": content,
        "published_at": item.get("published_at") or datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        "source": item.get("source") or "未知来源",
        "url": item.get("url"),
        "sentiment": sentiment,
        "positive_sectors_json": json.dumps(positive_sectors, ensure_ascii=False),
        "negative_sectors_json": json.dumps(negative_sectors, ensure_ascii=False),
        "positive_symbols_json": json.dumps(symbols_to_payload(positive_symbols), ensure_ascii=False),
        "negative_symbols_json": json.dumps(symbols_to_payload(negative_symbols), ensure_ascii=False),
        "related_symbols_json": json.dumps(symbols_to_payload(symbols), ensure_ascii=False),
        "fetched_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
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


def symbols_to_payload(symbols: list[str]) -> list[dict[str, str]]:
    code_to_name = get_reverse_stock_map()
    return [{"symbol": symbol, "name": code_to_name.get(symbol, symbol)} for symbol in symbols]


def _row_to_news_item(row: Any) -> dict[str, Any]:
    return {
        "id": row["digest"],
        "content": row["content"],
        "published_at": row["published_at"].isoformat() if hasattr(row["published_at"], "isoformat") else str(row["published_at"]),
        "source": row["source"],
        "url": row["url"],
        "sentiment": row["sentiment"],
        "positive_sectors": _loads(row["positive_sectors_json"]),
        "negative_sectors": _loads(row["negative_sectors_json"]),
        "positive_symbols": _loads(row["positive_symbols_json"]),
        "negative_symbols": _loads(row["negative_symbols_json"]),
        "related_symbols": _loads(row["related_symbols_json"]),
        "fetched_at": row["fetched_at"].isoformat() if hasattr(row["fetched_at"], "isoformat") else str(row["fetched_at"]),
    }


def _loads(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []
