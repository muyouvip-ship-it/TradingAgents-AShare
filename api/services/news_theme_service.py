from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session


logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")
SUPPORTED_WINDOWS = ("premarket", "24h", "72h", "7d")
SUPPORTED_HORIZONS = {"1d": 1, "3d": 3, "5d": 5}

POLICY_AUTHORITY_KEYWORDS = (
    "中共中央",
    "国务院",
    "国常会",
    "中央财经委",
    "发改委",
    "工信部",
    "财政部",
    "央行",
    "人民银行",
    "证监会",
    "商务部",
    "国资委",
)
POLICY_ACTION_KEYWORDS = (
    "印发",
    "行动方案",
    "指导意见",
    "实施方案",
    "专项",
    "试点",
    "补贴",
    "支持政策",
    "规划",
    "条例",
    "决定",
)
TIER_A_KEYWORDS = (
    "交易所",
    "上交所",
    "深交所",
    "北交所",
    "上市公司公告",
    "公告",
    "新华社",
    "人民日报",
    "证券时报",
    "中国证券报",
    "上海证券报",
    "财联社",
)
TIER_C_KEYWORDS = ("传闻", "网传", "小作文", "据传", "未经证实")
STRONG_POSITIVE_KEYWORDS = ("超预期", "大幅增长", "中标", "获批", "涨价", "补贴", "专项", "突破")
NEGATIVE_RISK_KEYWORDS = ("澄清", "减持", "监管", "处罚", "调查", "亏损", "不及预期", "退市", "风险")

THEME_CATALOG: dict[str, dict[str, Any]] = {
    "算力": {
        "parent_theme": "AI",
        "aliases": ("算力", "GPU", "英伟达", "服务器", "数据中心", "智算", "算力租赁", "液冷", "CPO", "光模块", "IDC"),
    },
    "人工智能": {
        "parent_theme": "AI",
        "aliases": ("人工智能", "AI", "AIGC", "大模型", "大语言模型", "LLM", "人工智能模型", "多模态", "智能体", "Agent"),
    },
    "半导体": {
        "parent_theme": "科技",
        "aliases": ("半导体", "芯片", "晶圆", "存储芯片", "先进封装", "封测", "EDA", "光刻机", "HBM"),
    },
    "机器人": {
        "parent_theme": "高端制造",
        "aliases": ("机器人", "人形机器人", "工业机器人", "减速器", "执行器", "灵巧手"),
    },
    "低空经济": {
        "parent_theme": "高端制造",
        "aliases": ("低空经济", "eVTOL", "飞行汽车", "无人机", "通航"),
    },
    "新能源": {
        "parent_theme": "新能源",
        "aliases": ("新能源", "锂电池", "固态电池", "动力电池", "储能", "光伏", "风电", "电力设备"),
    },
    "有色金属": {
        "parent_theme": "资源",
        "aliases": ("有色", "有色金属", "铜", "铝", "锂", "钴", "稀土", "黄金"),
    },
    "医药": {
        "parent_theme": "医药",
        "aliases": ("医药", "创新药", "CXO", "医疗器械", "疫苗", "中药"),
    },
    "消费电子": {
        "parent_theme": "消费科技",
        "aliases": ("消费电子", "苹果链", "MR", "XR", "智能手机", "折叠屏"),
    },
    "汽车": {
        "parent_theme": "汽车",
        "aliases": ("汽车", "智能驾驶", "自动驾驶", "新能源汽车", "整车", "零部件"),
    },
    "军工": {
        "parent_theme": "军工",
        "aliases": ("军工", "商业航天", "卫星", "航空发动机", "国防"),
    },
    "金融": {
        "parent_theme": "金融",
        "aliases": ("银行", "证券", "保险", "券商", "互金", "金融"),
    },
    "地产": {
        "parent_theme": "地产链",
        "aliases": ("地产", "房地产", "物业", "家居", "建材"),
    },
}

ALIAS_TO_THEME: list[tuple[str, str]] = sorted(
    ((alias, theme) for theme, config in THEME_CATALOG.items() for alias in config["aliases"]),
    key=lambda item: len(item[0]),
    reverse=True,
)


@dataclass
class ThemeEvent:
    digest: str
    theme: str
    raw_tags: list[str]
    sentiment: str
    source: str
    source_tier: str
    policy_boost: bool
    published_at: datetime
    content: str
    url: str | None
    related_symbols: list[dict[str, str]] = field(default_factory=list)
    event_score: float = 0.0


def ensure_theme_tables(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS market_news_theme_snapshots (
                snapshot_id VARCHAR(64) PRIMARY KEY,
                snapshot_date VARCHAR(10) NOT NULL,
                window_label VARCHAR(20) NOT NULL,
                window_start TIMESTAMP NOT NULL,
                window_end TIMESTAMP NOT NULL,
                theme VARCHAR(80) NOT NULL,
                parent_theme VARCHAR(80),
                rank INTEGER NOT NULL,
                score FLOAT NOT NULL,
                message_count INTEGER NOT NULL,
                positive_count INTEGER NOT NULL,
                negative_count INTEGER NOT NULL,
                consensus_rate FLOAT,
                source_tier VARCHAR(8) NOT NULL,
                policy_boost BOOLEAN NOT NULL DEFAULT FALSE,
                disagreement_level VARCHAR(20) NOT NULL,
                crowding_risk TEXT,
                related_symbols_json TEXT DEFAULT '[]',
                raw_tags_json TEXT DEFAULT '[]',
                evidence_items_json TEXT DEFAULT '[]',
                summary TEXT,
                catalyst TEXT,
                risk_note TEXT,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
            """
        )
    )
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_market_news_theme_snapshots_date ON market_news_theme_snapshots (snapshot_date, window_label, rank)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_market_news_theme_snapshots_theme ON market_news_theme_snapshots (theme)"))
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS market_news_theme_events (
                snapshot_id VARCHAR(64) NOT NULL,
                digest VARCHAR(64) NOT NULL,
                theme VARCHAR(80) NOT NULL,
                normalized_theme VARCHAR(80) NOT NULL,
                raw_tags_json TEXT DEFAULT '[]',
                sentiment VARCHAR(20) NOT NULL,
                source_tier VARCHAR(8) NOT NULL,
                policy_boost BOOLEAN NOT NULL DEFAULT FALSE,
                event_score FLOAT NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL,
                PRIMARY KEY (snapshot_id, digest, theme)
            )
            """
        )
    )
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_market_news_theme_events_digest ON market_news_theme_events (digest)"))
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS market_news_theme_performance (
                snapshot_date VARCHAR(10) NOT NULL,
                horizon VARCHAR(8) NOT NULL,
                theme VARCHAR(80) NOT NULL,
                start_date VARCHAR(10),
                end_date VARCHAR(10),
                change_pct FLOAT,
                source VARCHAR(120) NOT NULL,
                detail_json TEXT DEFAULT '{}',
                updated_at TIMESTAMP NOT NULL,
                PRIMARY KEY (snapshot_date, horizon, theme)
            )
            """
        )
    )
    db.commit()


def list_theme_rankings(
    db: Session,
    *,
    window: str = "premarket",
    limit: int = 20,
    include_evidence: bool = True,
) -> dict[str, Any]:
    rows = refresh_theme_rankings(db, windows=(window,), limit=limit, persist=True).get(window, [])
    if not include_evidence:
        rows = [{**row, "evidence_items": []} for row in rows]
    return {
        "window": _normalize_window(window),
        "items": rows[:limit],
        "updated_at": _iso(_now_cn_naive()),
        "source": "cache:market_news_items+theme_resonance",
        "message": "消息驱动主线观察，不构成直接买卖建议。",
    }


def refresh_theme_rankings(
    db: Session,
    *,
    windows: Iterable[str] = SUPPORTED_WINDOWS,
    limit: int = 20,
    persist: bool = True,
    now: datetime | None = None,
) -> dict[str, list[dict[str, Any]]]:
    ensure_theme_tables(db)
    current = _normalize_dt(now) or _now_cn_naive()
    market_confirmation = _load_market_confirmation(db)
    rankings_by_window: dict[str, list[dict[str, Any]]] = {}
    for raw_window in windows:
        window = _normalize_window(raw_window)
        window_start, window_end = _resolve_window_range(window, current)
        news_rows = _load_news_rows(db, window_start=window_start, window_end=window_end)
        ranking = _build_theme_ranking(
            news_rows,
            window=window,
            window_start=window_start,
            window_end=window_end,
            market_confirmation=market_confirmation,
            limit=limit,
        )
        if persist:
            _persist_ranking_snapshot(
                db,
                ranking,
                window=window,
                window_start=window_start,
                window_end=window_end,
                snapshot_date=window_end.date().isoformat(),
            )
        rankings_by_window[window] = ranking
    if persist:
        db.commit()
    return rankings_by_window


def list_theme_snapshots(db: Session, *, snapshot_date: str, window: str | None = None, limit: int = 50) -> dict[str, Any]:
    ensure_theme_tables(db)
    clauses = ["snapshot_date = :snapshot_date"]
    params: dict[str, Any] = {"snapshot_date": snapshot_date, "limit": int(limit)}
    if window:
        clauses.append("window_label = :window")
        params["window"] = _normalize_window(window)
    rows = db.execute(
        text(
            f"""
            SELECT *
            FROM market_news_theme_snapshots
            WHERE {' AND '.join(clauses)}
            ORDER BY window_label, rank
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    return {
        "snapshot_date": snapshot_date,
        "items": [_snapshot_row_to_payload(row, include_evidence=True) for row in rows],
        "updated_at": _iso(_now_cn_naive()),
    }


def get_theme_performance(db: Session, *, snapshot_date: str, horizon: str = "3d") -> dict[str, Any]:
    ensure_theme_tables(db)
    normalized_horizon = horizon if horizon in SUPPORTED_HORIZONS else "3d"
    snapshot_rows = db.execute(
        text(
            """
            SELECT DISTINCT theme
            FROM market_news_theme_snapshots
            WHERE snapshot_date = :snapshot_date
            ORDER BY theme
            """
        ),
        {"snapshot_date": snapshot_date},
    ).mappings().all()
    for row in snapshot_rows:
        theme = str(row["theme"])
        performance = _compute_theme_performance(db, theme=theme, snapshot_date=snapshot_date, horizon=normalized_horizon)
        db.execute(
            text(
                """
                INSERT INTO market_news_theme_performance (
                    snapshot_date, horizon, theme, start_date, end_date, change_pct, source, detail_json, updated_at
                )
                VALUES (
                    :snapshot_date, :horizon, :theme, :start_date, :end_date, :change_pct, :source, :detail_json, :updated_at
                )
                ON CONFLICT (snapshot_date, horizon, theme) DO UPDATE SET
                    start_date = EXCLUDED.start_date,
                    end_date = EXCLUDED.end_date,
                    change_pct = EXCLUDED.change_pct,
                    source = EXCLUDED.source,
                    detail_json = EXCLUDED.detail_json,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            {
                "snapshot_date": snapshot_date,
                "horizon": normalized_horizon,
                "theme": theme,
                "start_date": performance.get("start_date"),
                "end_date": performance.get("end_date"),
                "change_pct": performance.get("change_pct"),
                "source": performance.get("source") or "unavailable",
                "detail_json": json.dumps(performance.get("detail") or {}, ensure_ascii=False),
                "updated_at": _iso(_now_cn_naive()),
            },
        )
    db.commit()
    rows = db.execute(
        text(
            """
            SELECT p.*, s.rank, s.score, s.message_count, s.consensus_rate
            FROM market_news_theme_performance p
            LEFT JOIN market_news_theme_snapshots s
              ON s.snapshot_date = p.snapshot_date
             AND s.theme = p.theme
             AND s.window_label = 'premarket'
            WHERE p.snapshot_date = :snapshot_date
              AND p.horizon = :horizon
            ORDER BY COALESCE(s.rank, 999), p.theme
            """
        ),
        {"snapshot_date": snapshot_date, "horizon": normalized_horizon},
    ).mappings().all()
    return {
        "snapshot_date": snapshot_date,
        "horizon": normalized_horizon,
        "items": [_performance_row_to_payload(row) for row in rows],
        "updated_at": _iso(_now_cn_naive()),
    }


def normalize_theme_name(value: str, content: str = "") -> tuple[str | None, list[str]]:
    text_value = str(value or "").strip()
    text_blob = f"{text_value} {content or ''}"
    raw_tags: list[str] = []
    for alias, theme in ALIAS_TO_THEME:
        if alias and alias in text_blob:
            raw_tags.append(alias)
            return theme, _dedupe_strings(raw_tags)
    if text_value in THEME_CATALOG:
        return text_value, [text_value]
    return None, []


def classify_source_tier(source: str, content: str) -> tuple[str, bool]:
    haystack = f"{source or ''} {content or ''}"
    has_policy_authority = any(keyword in haystack for keyword in POLICY_AUTHORITY_KEYWORDS)
    has_policy_action = any(keyword in haystack for keyword in POLICY_ACTION_KEYWORDS)
    if has_policy_authority and has_policy_action:
        return "S", True
    if any(keyword in haystack for keyword in TIER_A_KEYWORDS) or has_policy_authority:
        return "A", False
    if any(keyword in haystack for keyword in TIER_C_KEYWORDS):
        return "C", False
    return "B", False


def _build_theme_ranking(
    rows: Iterable[Any],
    *,
    window: str,
    window_start: datetime,
    window_end: datetime,
    market_confirmation: dict[str, dict[str, float]],
    limit: int,
) -> list[dict[str, Any]]:
    events_by_theme: dict[str, list[ThemeEvent]] = defaultdict(list)
    for row in rows:
        for event in _row_to_theme_events(row, now=window_end):
            events_by_theme[event.theme].append(event)

    ranking: list[dict[str, Any]] = []
    for theme, events in events_by_theme.items():
        payload = _score_theme(theme, events, market_confirmation=market_confirmation)
        payload["window"] = window
        payload["window_start"] = _iso(window_start)
        payload["window_end"] = _iso(window_end)
        ranking.append(payload)

    ranking.sort(key=lambda item: (-float(item["score"]), not item["policy_boost"], -int(item["message_count"]), item["theme"]))
    for rank, item in enumerate(ranking[:limit], start=1):
        item["rank"] = rank
    return ranking[:limit]


def _score_theme(theme: str, events: list[ThemeEvent], *, market_confirmation: dict[str, dict[str, float]]) -> dict[str, Any]:
    positive_events = [event for event in events if event.sentiment == "positive"]
    negative_events = [event for event in events if event.sentiment == "negative"]
    neutral_events = [event for event in events if event.sentiment == "neutral"]
    message_count = len({event.digest for event in positive_events})
    negative_count = len({event.digest for event in negative_events})
    total_directional = message_count + negative_count
    consensus_rate = round(message_count / total_directional, 4) if total_directional else None

    source_tiers = [event.source_tier for event in events]
    top_tier = _top_source_tier(source_tiers)
    policy_boost = any(event.policy_boost for event in events)
    source_count = len({event.source for event in events if event.source})
    related_symbols = _collect_related_symbols(events)
    raw_tags = _dedupe_strings(tag for event in events for tag in event.raw_tags)
    positive_score = sum(event.event_score for event in positive_events)
    negative_score = sum(abs(event.event_score) for event in negative_events)
    strong_recent_count = sum(1 for event in positive_events if (_safe_datetime(event.published_at) and (_now_cn_naive() - event.published_at).total_seconds() <= 6 * 3600))
    resonance_multiplier = 1.0
    resonance_multiplier += min(1.2, math.log1p(max(message_count - 1, 0)) * 0.35)
    resonance_multiplier += min(0.8, math.log1p(max(source_count - 1, 0)) * 0.25)
    resonance_multiplier += min(0.6, math.log1p(len(related_symbols)) * 0.16)
    if strong_recent_count >= 3:
        resonance_multiplier += 0.18

    disagreement_level, crowding_risk, disagreement_multiplier = _classify_disagreement(consensus_rate, message_count, negative_count)
    confirmation = market_confirmation.get(theme) or {}
    market_score = float(confirmation.get("score") or 0.0)
    risk_adjustment = negative_score * 0.65
    score = (positive_score * resonance_multiplier * disagreement_multiplier) + market_score - risk_adjustment
    if policy_boost:
        score = max(score, 42.0 + market_score)
    score = max(score, 0.0)

    evidence = _build_evidence(events)
    summary = _build_summary(theme, message_count, negative_count, top_tier, policy_boost, consensus_rate)
    catalyst = _build_catalyst(evidence, raw_tags, confirmation)
    risk_note = _build_risk_note(crowding_risk, disagreement_level, negative_events)
    return {
        "theme": theme,
        "parent_theme": THEME_CATALOG.get(theme, {}).get("parent_theme"),
        "rank": 0,
        "score": round(score, 2),
        "message_count": message_count,
        "positive_count": message_count,
        "negative_count": negative_count,
        "neutral_count": len({event.digest for event in neutral_events}),
        "consensus_rate": consensus_rate,
        "source_tier": top_tier,
        "policy_boost": policy_boost,
        "disagreement_level": disagreement_level,
        "crowding_risk": crowding_risk,
        "related_symbols": related_symbols,
        "raw_tags": raw_tags,
        "summary": summary,
        "catalyst": catalyst,
        "risk_note": risk_note,
        "market_confirmation": confirmation,
        "evidence_items": evidence,
    }


def _row_to_theme_events(row: Any, *, now: datetime) -> list[ThemeEvent]:
    content = str(row["content"] or "")
    source = str(row["source"] or "未知来源")
    published_at = _safe_datetime(row["published_at"]) or now
    positive_sectors = _loads(row["positive_sectors_json"])
    negative_sectors = _loads(row["negative_sectors_json"])
    related_symbols = _loads(row["related_symbols_json"])
    sentiment = str(row["sentiment"] or "neutral")
    tier, policy_boost = classify_source_tier(source, content)

    theme_sentiments: dict[str, dict[str, Any]] = {}
    for raw in positive_sectors:
        theme, raw_tags = normalize_theme_name(str(raw), content)
        if theme:
            theme_sentiments.setdefault(theme, {"sentiment": "positive", "raw_tags": []})
            theme_sentiments[theme]["raw_tags"].extend(raw_tags or [str(raw)])
    for raw in negative_sectors:
        theme, raw_tags = normalize_theme_name(str(raw), content)
        if theme:
            current = theme_sentiments.setdefault(theme, {"sentiment": "negative", "raw_tags": []})
            if current["sentiment"] != "positive":
                current["sentiment"] = "negative"
            current["raw_tags"].extend(raw_tags or [str(raw)])
    for alias, theme in ALIAS_TO_THEME:
        if alias in content:
            current = theme_sentiments.setdefault(theme, {"sentiment": sentiment, "raw_tags": []})
            current["raw_tags"].append(alias)
            if current["sentiment"] == "neutral" and sentiment in {"positive", "negative"}:
                current["sentiment"] = sentiment

    events: list[ThemeEvent] = []
    for theme, data in theme_sentiments.items():
        event_sentiment = _normalize_sentiment(str(data.get("sentiment") or sentiment))
        if event_sentiment == "neutral" and policy_boost:
            event_sentiment = "positive"
        event_score = _event_score(
            content=content,
            sentiment=event_sentiment,
            tier=tier,
            policy_boost=policy_boost,
            published_at=published_at,
            now=now,
        )
        events.append(
            ThemeEvent(
                digest=str(row["digest"]),
                theme=theme,
                raw_tags=_dedupe_strings(data.get("raw_tags") or []),
                sentiment=event_sentiment,
                source=source,
                source_tier=tier,
                policy_boost=policy_boost,
                published_at=published_at,
                content=content,
                url=row.get("url"),
                related_symbols=related_symbols if isinstance(related_symbols, list) else [],
                event_score=event_score,
            )
        )
    return events


def _event_score(
    *,
    content: str,
    sentiment: str,
    tier: str,
    policy_boost: bool,
    published_at: datetime,
    now: datetime,
) -> float:
    tier_weight = {"S": 28.0, "A": 4.0, "B": 1.0, "C": 0.35}.get(tier, 1.0)
    age_hours = max((now - published_at).total_seconds() / 3600, 0.0)
    if age_hours <= 6:
        freshness = 1.35
    elif age_hours <= 24:
        freshness = 1.0
    elif age_hours <= 72:
        freshness = 0.75
    else:
        freshness = 0.45
    strength = 1.0
    if any(keyword in content for keyword in STRONG_POSITIVE_KEYWORDS):
        strength += 0.45
    if policy_boost:
        strength += 0.65
    if sentiment == "negative":
        strength = max(1.0, strength)
        return -tier_weight * freshness * strength
    if sentiment == "neutral":
        return tier_weight * freshness * 0.22
    return tier_weight * freshness * strength


def _classify_disagreement(consensus_rate: float | None, positive_count: int, negative_count: int) -> tuple[str, str | None, float]:
    if consensus_rate is None:
        return "none", None, 0.9
    if positive_count >= 8 and consensus_rate > 0.9:
        return "none", "消息预期较一致，需防范高开后兑现和后排分化。", 0.9
    if 0.65 <= consensus_rate <= 0.85 and positive_count >= 3 and negative_count > 0:
        return "healthy", None, 1.08
    if consensus_rate < 0.55:
        return "high", "分歧偏高，先观察澄清、减持或监管压力是否释放。", 0.65
    return "none", None, 1.0


def _build_summary(theme: str, positive_count: int, negative_count: int, source_tier: str, policy_boost: bool, consensus_rate: float | None) -> str:
    parts = [f"{theme}近窗口命中{positive_count}条利好线索"]
    if negative_count:
        parts.append(f"{negative_count}条风险或分歧线索")
    if policy_boost:
        parts.append("包含政策级催化")
    elif source_tier in {"S", "A"}:
        parts.append(f"最高来源层级{source_tier}")
    if consensus_rate is not None:
        parts.append(f"共识率{consensus_rate:.0%}")
    return "，".join(parts) + "。"


def _build_catalyst(evidence: list[dict[str, Any]], raw_tags: list[str], confirmation: dict[str, float]) -> str:
    if evidence:
        top = evidence[0]
        return str(top.get("content") or "")[:90]
    if raw_tags:
        return "关键词集中在：" + "、".join(raw_tags[:5])
    if confirmation:
        return "板块行情和资金流存在同步验证。"
    return "等待更多消息和资金面验证。"


def _build_risk_note(crowding_risk: str | None, disagreement_level: str, negative_events: list[ThemeEvent]) -> str:
    if crowding_risk:
        return crowding_risk
    if disagreement_level == "healthy":
        return "存在适度分歧，观察开盘承接和龙头是否继续放量。"
    if negative_events:
        return "存在利空或澄清线索，需等待风险释放和资金确认。"
    return "仍需结合竞价、成交量和核心标的承接确认。"


def _build_evidence(events: list[ThemeEvent]) -> list[dict[str, Any]]:
    ordered = sorted(events, key=lambda event: (event.policy_boost, event.event_score, event.published_at), reverse=True)
    evidence: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in ordered:
        if event.digest in seen:
            continue
        seen.add(event.digest)
        evidence.append(
            {
                "id": event.digest,
                "content": event.content[:180],
                "source": event.source,
                "published_at": _iso(event.published_at),
                "sentiment": event.sentiment,
                "source_tier": event.source_tier,
                "policy_boost": event.policy_boost,
                "score": round(event.event_score, 2),
                "raw_tags": event.raw_tags,
                "url": event.url,
            }
        )
        if len(evidence) >= 6:
            break
    return evidence


def _collect_related_symbols(events: list[ThemeEvent]) -> list[dict[str, str]]:
    by_symbol: dict[str, dict[str, str]] = {}
    for event in events:
        for item in event.related_symbols or []:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "").strip().upper()
            if not symbol or symbol in by_symbol:
                continue
            by_symbol[symbol] = {"symbol": symbol, "name": str(item.get("name") or "").strip()}
            if len(by_symbol) >= 10:
                return list(by_symbol.values())
    return list(by_symbol.values())


def _persist_ranking_snapshot(
    db: Session,
    ranking: list[dict[str, Any]],
    *,
    window: str,
    window_start: datetime,
    window_end: datetime,
    snapshot_date: str,
) -> None:
    now = _iso(_now_cn_naive())
    db.execute(
        text(
            """
            DELETE FROM market_news_theme_events
            WHERE snapshot_id IN (
                SELECT snapshot_id FROM market_news_theme_snapshots
                WHERE snapshot_date = :snapshot_date AND window_label = :window
            )
            """
        ),
        {"snapshot_date": snapshot_date, "window": window},
    )
    db.execute(
        text(
            """
            DELETE FROM market_news_theme_snapshots
            WHERE snapshot_date = :snapshot_date AND window_label = :window
            """
        ),
        {"snapshot_date": snapshot_date, "window": window},
    )
    for item in ranking:
        snapshot_id = _make_snapshot_id(snapshot_date, window, str(item["theme"]))
        db.execute(
            text(
                """
                INSERT INTO market_news_theme_snapshots (
                    snapshot_id, snapshot_date, window_label, window_start, window_end,
                    theme, parent_theme, rank, score, message_count, positive_count, negative_count,
                    consensus_rate, source_tier, policy_boost, disagreement_level, crowding_risk,
                    related_symbols_json, raw_tags_json, evidence_items_json, summary, catalyst, risk_note,
                    created_at, updated_at
                )
                VALUES (
                    :snapshot_id, :snapshot_date, :window_label, :window_start, :window_end,
                    :theme, :parent_theme, :rank, :score, :message_count, :positive_count, :negative_count,
                    :consensus_rate, :source_tier, :policy_boost, :disagreement_level, :crowding_risk,
                    :related_symbols_json, :raw_tags_json, :evidence_items_json, :summary, :catalyst, :risk_note,
                    :created_at, :updated_at
                )
                """
            ),
            {
                "snapshot_id": snapshot_id,
                "snapshot_date": snapshot_date,
                "window_label": window,
                "window_start": _iso(window_start),
                "window_end": _iso(window_end),
                "theme": item["theme"],
                "parent_theme": item.get("parent_theme"),
                "rank": item["rank"],
                "score": item["score"],
                "message_count": item["message_count"],
                "positive_count": item["positive_count"],
                "negative_count": item["negative_count"],
                "consensus_rate": item.get("consensus_rate"),
                "source_tier": item["source_tier"],
                "policy_boost": item["policy_boost"],
                "disagreement_level": item["disagreement_level"],
                "crowding_risk": item.get("crowding_risk"),
                "related_symbols_json": json.dumps(item.get("related_symbols") or [], ensure_ascii=False),
                "raw_tags_json": json.dumps(item.get("raw_tags") or [], ensure_ascii=False),
                "evidence_items_json": json.dumps(item.get("evidence_items") or [], ensure_ascii=False),
                "summary": item.get("summary"),
                "catalyst": item.get("catalyst"),
                "risk_note": item.get("risk_note"),
                "created_at": now,
                "updated_at": now,
            },
        )
        for evidence in item.get("evidence_items") or []:
            db.execute(
                text(
                    """
                    INSERT INTO market_news_theme_events (
                        snapshot_id, digest, theme, normalized_theme, raw_tags_json, sentiment,
                        source_tier, policy_boost, event_score, created_at
                    )
                    VALUES (
                        :snapshot_id, :digest, :theme, :normalized_theme, :raw_tags_json, :sentiment,
                        :source_tier, :policy_boost, :event_score, :created_at
                    )
                    ON CONFLICT (snapshot_id, digest, theme) DO NOTHING
                    """
                ),
                {
                    "snapshot_id": snapshot_id,
                    "digest": evidence["id"],
                    "theme": item["theme"],
                    "normalized_theme": item["theme"],
                    "raw_tags_json": json.dumps(evidence.get("raw_tags") or [], ensure_ascii=False),
                    "sentiment": evidence.get("sentiment") or "neutral",
                    "source_tier": evidence.get("source_tier") or item["source_tier"],
                    "policy_boost": bool(evidence.get("policy_boost")),
                    "event_score": float(evidence.get("score") or 0),
                    "created_at": now,
                },
            )


def _snapshot_row_to_payload(row: Any, *, include_evidence: bool) -> dict[str, Any]:
    payload = {
        "theme": row["theme"],
        "parent_theme": row["parent_theme"],
        "rank": int(row["rank"]),
        "score": round(float(row["score"] or 0), 2),
        "message_count": int(row["message_count"] or 0),
        "positive_count": int(row["positive_count"] or 0),
        "negative_count": int(row["negative_count"] or 0),
        "consensus_rate": row["consensus_rate"],
        "source_tier": row["source_tier"],
        "policy_boost": bool(row["policy_boost"]),
        "disagreement_level": row["disagreement_level"],
        "crowding_risk": row["crowding_risk"],
        "related_symbols": _loads(row["related_symbols_json"]),
        "raw_tags": _loads(row["raw_tags_json"]),
        "summary": row["summary"],
        "catalyst": row["catalyst"],
        "risk_note": row["risk_note"],
        "window": row["window_label"],
        "window_start": _iso(row["window_start"]),
        "window_end": _iso(row["window_end"]),
        "snapshot_date": row["snapshot_date"],
    }
    payload["evidence_items"] = _loads(row["evidence_items_json"]) if include_evidence else []
    return payload


def _performance_row_to_payload(row: Any) -> dict[str, Any]:
    return {
        "theme": row["theme"],
        "rank": int(row["rank"]) if row.get("rank") is not None else None,
        "score": row.get("score"),
        "message_count": row.get("message_count"),
        "consensus_rate": row.get("consensus_rate"),
        "horizon": row["horizon"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "change_pct": row["change_pct"],
        "source": row["source"],
        "detail": _loads(row["detail_json"], default={}),
    }


def _compute_theme_performance(db: Session, *, theme: str, snapshot_date: str, horizon: str) -> dict[str, Any]:
    table = _select_daily_table(db)
    if not table:
        return {"source": "unavailable:no_daily_table", "detail": {"reason": "daily table missing"}}
    days = SUPPORTED_HORIZONS[horizon]
    date_rows = db.execute(
        text(
            f"""
            SELECT trade_date
            FROM {table}
            WHERE trade_date > :snapshot_date
            GROUP BY trade_date
            ORDER BY trade_date
            LIMIT :days
            """
        ),
        {"snapshot_date": snapshot_date, "days": days},
    ).mappings().all()
    if len(date_rows) < days:
        return {"source": f"unavailable:{table}", "detail": {"reason": "insufficient_trade_dates"}}
    start_date = str(date_rows[0]["trade_date"])
    end_date = str(date_rows[-1]["trade_date"])
    if not _has_column(db, table, "sw_industry_l1"):
        return {"source": f"unavailable:{table}", "start_date": start_date, "end_date": end_date, "detail": {"reason": "missing_sw_industry_l1"}}
    result = db.execute(
        text(
            f"""
            WITH first_day AS (
                SELECT symbol, pre_close
                FROM {table}
                WHERE trade_date = :start_date
                  AND sw_industry_l1 = :theme
                  AND pre_close IS NOT NULL
                  AND pre_close > 0
            ),
            last_day AS (
                SELECT symbol, close
                FROM {table}
                WHERE trade_date = :end_date
                  AND sw_industry_l1 = :theme
                  AND close IS NOT NULL
            )
            SELECT AVG((last_day.close - first_day.pre_close) / NULLIF(first_day.pre_close, 0) * 100) AS change_pct,
                   COUNT(*) AS member_count
            FROM first_day
            JOIN last_day ON first_day.symbol = last_day.symbol
            """
        ),
        {"theme": theme, "start_date": start_date, "end_date": end_date},
    ).mappings().first() or {}
    change_pct = result.get("change_pct")
    member_count = int(result.get("member_count") or 0)
    return {
        "start_date": start_date,
        "end_date": end_date,
        "change_pct": round(float(change_pct), 4) if change_pct is not None else None,
        "source": f"industry_aggregate:{table}",
        "detail": {"member_count": member_count},
    }


def _load_news_rows(db: Session, *, window_start: datetime, window_end: datetime) -> list[Any]:
    rows = db.execute(
        text(
            """
            SELECT digest, content, published_at, source, url, sentiment,
                   positive_sectors_json, negative_sectors_json, related_symbols_json, fetched_at
            FROM market_news_items
            WHERE published_at >= :window_start
              AND published_at <= :window_end
            ORDER BY published_at DESC, fetched_at DESC
            LIMIT 1200
            """
        ),
        {"window_start": _iso(window_start), "window_end": _iso(window_end)},
    ).mappings().all()
    return list(rows)


def _load_market_confirmation(db: Session) -> dict[str, dict[str, float]]:
    confirmation: dict[str, dict[str, float]] = {}
    try:
        from api.routes.market import _load_sector_rankings

        gainers, losers = _load_sector_rankings(db, limit=30)
        inflows: list[dict[str, Any]] = []
        outflows: list[dict[str, Any]] = []
        if os.getenv("NEWS_THEME_USE_LIVE_FUND_FLOW", "0").strip().lower() in {"1", "true", "yes", "on"}:
            from api.routes.market import _load_sector_fund_flow

            inflows, outflows = _load_sector_fund_flow(limit=30)
    except Exception:
        return confirmation

    for item in gainers or []:
        theme, _raw = normalize_theme_name(str(item.get("sector_name") or ""))
        if theme:
            change_pct = float(item.get("change_pct") or 0)
            confirmation.setdefault(theme, {})["change_pct"] = change_pct
            confirmation[theme]["score"] = confirmation[theme].get("score", 0.0) + min(max(change_pct, 0), 8) * 0.8
    for item in losers or []:
        theme, _raw = normalize_theme_name(str(item.get("sector_name") or ""))
        if theme:
            change_pct = float(item.get("change_pct") or 0)
            confirmation.setdefault(theme, {})["change_pct"] = change_pct
            confirmation[theme]["score"] = confirmation[theme].get("score", 0.0) + max(change_pct, -8) * 0.35
    for item in inflows or []:
        theme, _raw = normalize_theme_name(str(item.get("sector_name") or ""))
        if theme:
            net_inflow = float(item.get("net_inflow") or 0)
            confirmation.setdefault(theme, {})["net_inflow"] = net_inflow
            confirmation[theme]["score"] = confirmation[theme].get("score", 0.0) + min(max(net_inflow / 100_000_000, 0), 10) * 0.35
    for item in outflows or []:
        theme, _raw = normalize_theme_name(str(item.get("sector_name") or ""))
        if theme:
            net_inflow = float(item.get("net_inflow") or 0)
            confirmation.setdefault(theme, {})["net_inflow"] = net_inflow
            confirmation[theme]["score"] = confirmation[theme].get("score", 0.0) + max(net_inflow / 100_000_000, -10) * 0.18
    return confirmation


def _select_daily_table(db: Session) -> str | None:
    for table in ("pub_stock_daily_kline", "market_stock_daily_kline", "stock_daily_kline"):
        if _has_table(db, table) and _has_column(db, table, "trade_date") and _has_column(db, table, "symbol"):
            return table
    return None


def _has_table(db: Session, table_name: str) -> bool:
    try:
        return bool(db.execute(text("SELECT to_regclass(:table_name)"), {"table_name": table_name}).scalar())
    except Exception:
        return False


def _has_column(db: Session, table_name: str, column_name: str) -> bool:
    try:
        row = db.execute(
            text(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = :table_name
                  AND column_name = :column_name
                LIMIT 1
                """
            ),
            {"table_name": table_name, "column_name": column_name},
        ).first()
        return row is not None
    except Exception:
        return False


def _resolve_window_range(window: str, now: datetime) -> tuple[datetime, datetime]:
    end = _normalize_dt(now) or _now_cn_naive()
    if window == "24h":
        return end - timedelta(hours=24), end
    if window == "72h":
        return end - timedelta(hours=72), end
    if window == "7d":
        return end - timedelta(days=7), end
    return _last_trading_close(end), end


def _last_trading_close(now: datetime) -> datetime:
    close = datetime.combine(now.date(), time(hour=15, minute=0))
    if now.weekday() < 5 and now >= close:
        return close
    cursor = now.date() - timedelta(days=1)
    while cursor.weekday() >= 5:
        cursor -= timedelta(days=1)
    return datetime.combine(cursor, time(hour=15, minute=0))


def _normalize_window(window: str) -> str:
    value = str(window or "premarket").strip().lower()
    return value if value in SUPPORTED_WINDOWS else "premarket"


def _normalize_sentiment(value: str) -> str:
    value = str(value or "").strip().lower()
    return value if value in {"positive", "negative", "neutral"} else "neutral"


def _top_source_tier(tiers: Iterable[str]) -> str:
    order = {"S": 4, "A": 3, "B": 2, "C": 1}
    return max((tier for tier in tiers if tier), key=lambda tier: order.get(tier, 0), default="B")


def _make_snapshot_id(snapshot_date: str, window: str, theme: str) -> str:
    return hashlib.sha256(f"{snapshot_date}|{window}|{theme}".encode("utf-8")).hexdigest()


def _loads(value: Any, default: Any | None = None) -> Any:
    if default is None:
        default = []
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return default


def _dedupe_strings(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _safe_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, time())
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None)
    except Exception:
        return None


def _normalize_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(CN_TZ).replace(tzinfo=None)
    return value


def _now_cn_naive() -> datetime:
    return datetime.now(CN_TZ).replace(tzinfo=None)


def _iso(value: Any) -> str | None:
    dt_value = _safe_datetime(value)
    if dt_value is None:
        return None
    return dt_value.isoformat()
