from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import text

from tests.postgres_test_utils import isolated_postgres_session
from api.database import Base
from api.services import news_eye_service, news_theme_service


@pytest.fixture
def db():
    with isolated_postgres_session(Base, schema_prefix="ta_news_theme") as session:
        yield session


def _seed_news(db, monkeypatch, items: list[dict]):
    monkeypatch.setattr(
        news_eye_service,
        "_fetch_external_news",
        lambda limit, symbols: (items, ["测试资讯源"], []),
    )
    news_eye_service.refresh_news_cache(db, limit=max(len(items), 20), symbols=[], trigger="test")


def _ranking(db, *, now: datetime = datetime(2026, 5, 10, 10, 0, 0)):
    return news_theme_service.refresh_theme_rankings(
        db,
        windows=("premarket",),
        limit=20,
        persist=True,
        now=now,
    )["premarket"]


def test_policy_tier_can_beat_many_low_quality_reposts(db, monkeypatch):
    items = [
        {
            "content": "国务院印发人工智能行动方案，人工智能产业获得专项支持",
            "published_at": "2026-05-09T09:00:00",
            "source": "国务院",
            "url": "https://example.com/policy",
        }
    ]
    items.extend(
        {
            "content": f"行业传闻称算力订单增长，算力板块走强，第{i}条转载",
            "published_at": f"2026-05-09T10:{i:02d}:00",
            "source": "行业小报",
            "url": f"https://example.com/repost-{i}",
        }
        for i in range(20)
    )
    _seed_news(db, monkeypatch, items)

    ranking = _ranking(db)

    assert ranking[0]["theme"] == "人工智能"
    assert ranking[0]["source_tier"] == "S"
    assert ranking[0]["policy_boost"] is True
    ai = next(item for item in ranking if item["theme"] == "人工智能")
    compute = next(item for item in ranking if item["theme"] == "算力")
    assert ai["score"] > compute["score"]


def test_theme_aliases_are_normalized_to_standard_catalog(db, monkeypatch):
    _seed_news(
        db,
        monkeypatch,
        [
            {
                "content": "大模型应用订单增长，LLM 和人工智能模型方向走强",
                "published_at": "2026-05-09T09:00:00",
                "source": "财联社电报",
                "url": "https://example.com/ai",
            }
        ],
    )

    ranking = _ranking(db)

    assert [item["theme"] for item in ranking] == ["人工智能"]
    assert {"大模型", "LLM", "人工智能模型"} & set(ranking[0]["raw_tags"])


def test_compute_theme_stays_independent_from_parent_ai_theme(db, monkeypatch):
    items = [
        {
            "content": f"算力订单增长，数据中心和服务器需求走强，第{i}条",
            "published_at": f"2026-05-09T09:{i:02d}:00",
            "source": "财联社电报",
            "url": f"https://example.com/compute-{i}",
        }
        for i in range(10)
    ]
    items.extend(
        {
            "content": f"人工智能应用增长，大模型方向活跃，第{i}条",
            "published_at": f"2026-05-09T10:{i:02d}:00",
            "source": "财联社电报",
            "url": f"https://example.com/ai-{i}",
        }
        for i in range(5)
    )
    _seed_news(db, monkeypatch, items)

    ranking = _ranking(db)

    assert ranking[0]["theme"] == "算力"
    assert ranking[0]["parent_theme"] == "AI"
    assert next(item for item in ranking if item["theme"] == "人工智能")["parent_theme"] == "AI"


def test_consensus_rate_and_disagreement_level_are_exposed(db, monkeypatch):
    items = [
        {
            "content": f"算力订单增长，算力板块走强，第{i}条",
            "published_at": f"2026-05-09T09:{i:02d}:00",
            "source": "财联社电报",
            "url": f"https://example.com/pos-{i}",
        }
        for i in range(10)
    ]
    items.extend(
        {
            "content": f"算力公司减持，算力板块承压，第{i}条",
            "published_at": f"2026-05-09T10:{i:02d}:00",
            "source": "财联社电报",
            "url": f"https://example.com/neg-{i}",
        }
        for i in range(3)
    )
    _seed_news(db, monkeypatch, items)

    compute = next(item for item in _ranking(db) if item["theme"] == "算力")

    assert compute["positive_count"] == 10
    assert compute["negative_count"] == 3
    assert compute["consensus_rate"] == pytest.approx(10 / 13, rel=1e-3)
    assert compute["disagreement_level"] == "healthy"


def test_crowding_risk_is_generated_for_over_consensus_theme(db, monkeypatch):
    _seed_news(
        db,
        monkeypatch,
        [
            {
                "content": f"算力订单增长，算力板块走强，第{i}条",
                "published_at": f"2026-05-09T09:{i:02d}:00",
                "source": "财联社电报",
                "url": f"https://example.com/hot-{i}",
            }
            for i in range(10)
        ],
    )

    compute = next(item for item in _ranking(db) if item["theme"] == "算力")

    assert compute["consensus_rate"] == 1
    assert "兑现" in compute["crowding_risk"]


def test_snapshot_history_and_performance_are_available(db, monkeypatch):
    _seed_news(
        db,
        monkeypatch,
        [
            {
                "content": "算力订单增长，算力板块走强",
                "published_at": "2026-05-09T09:00:00",
                "source": "财联社电报",
                "url": "https://example.com/snapshot",
            }
        ],
    )
    _ranking(db)
    db.execute(
        text(
            """
            CREATE TABLE pub_stock_daily_kline (
                symbol VARCHAR(16),
                trade_date VARCHAR(10),
                sw_industry_l1 VARCHAR(80),
                pre_close FLOAT,
                close FLOAT
            )
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO pub_stock_daily_kline (symbol, trade_date, sw_industry_l1, pre_close, close)
            VALUES
                ('000001.SZ', '2026-05-11', '算力', 10, 11),
                ('000001.SZ', '2026-05-12', '算力', 11, 12),
                ('000001.SZ', '2026-05-13', '算力', 12, 13)
            """
        )
    )
    db.commit()

    snapshots = news_theme_service.list_theme_snapshots(db, snapshot_date="2026-05-10")
    performance = news_theme_service.get_theme_performance(db, snapshot_date="2026-05-10", horizon="3d")

    assert snapshots["items"][0]["theme"] == "算力"
    assert performance["items"][0]["theme"] == "算力"
    assert performance["items"][0]["change_pct"] == pytest.approx(30.0)
