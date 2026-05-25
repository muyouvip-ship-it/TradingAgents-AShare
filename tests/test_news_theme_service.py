from __future__ import annotations

import json
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


def test_theme_card_uses_dominant_tier_and_keeps_top_policy_tier(db, monkeypatch):
    _seed_news(
        db,
        monkeypatch,
        [
            {
                "content": "国务院印发人工智能行动方案，人工智能产业获得专项支持",
                "published_at": "2026-05-10T09:00:00",
                "source": "国务院",
                "url": "https://example.com/ai-policy",
            }
        ]
        + [
            {
                "content": f"财联社电报，人工智能应用订单增长，上市公司公告显示业务进展，第{i}条",
                "published_at": f"2026-05-10T09:{i + 1:02d}:00",
                "source": "财联社电报",
                "url": f"https://example.com/ai-a-{i}",
            }
            for i in range(3)
        ],
    )

    ai = next(item for item in _ranking(db) if item["theme"] == "人工智能")

    assert ai["source_tier"] == "A"
    assert ai["top_source_tier"] == "S"
    assert ai["policy_boost"] is True
    assert "主导来源层级A" in ai["summary"]
    assert "含S级政策催化" in ai["summary"]


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


def test_research_provider_symbols_are_not_theme_recommendations(db, monkeypatch):
    monkeypatch.setattr(
        news_eye_service,
        "get_reverse_stock_map",
        lambda: {
            "601688.SH": "华泰证券",
            "300857.SZ": "协创数据",
            "300059.SZ": "东方财富",
        },
    )
    _seed_news(
        db,
        monkeypatch,
        [
            {
                "content": "【华泰证券维持英伟达买入评级】华泰证券表示，Agentic AI推动低时延推理芯片需求，人工智能基础设施景气提升。",
                "published_at": "2026-05-10T09:00:00",
                "source": "财联社电报",
                "url": "https://example.com/huatai-research",
            },
            {
                "content": "协创数据AI芯片订单增长，人工智能终端需求走强",
                "published_at": "2026-05-10T09:10:00",
                "source": "财联社电报",
                "url": "https://example.com/ai-stock",
            },
            {
                "content": "【东方财富财经早餐】人工智能与先进制造业深度融合，政策支持持续加码。",
                "published_at": "2026-05-10T09:20:00",
                "source": "东方财富财经早餐",
                "url": "https://example.com/eastmoney-breakfast",
            },
        ],
    )

    ai = next(item for item in _ranking(db) if item["theme"] == "人工智能")

    assert {"symbol": "300857.SZ", "name": "协创数据"} in ai["related_symbols"]
    assert all(item["name"] != "华泰证券" for item in ai["related_symbols"])
    assert all(item["name"] != "东方财富" for item in ai["related_symbols"])


def test_generic_theme_keyword_symbol_names_are_not_recommendations(db, monkeypatch):
    monkeypatch.setattr(
        news_eye_service,
        "get_reverse_stock_map",
        lambda: {"300024.SZ": "机器人"},
    )
    _seed_news(
        db,
        monkeypatch,
        [
            {
                "content": "人工智能政策推动智能机器人应用增长，相关行业销售收入提升",
                "published_at": "2026-05-10T09:00:00",
                "source": "财联社电报",
                "url": "https://example.com/generic-robot",
            }
        ],
    )

    ai = next(item for item in _ranking(db) if item["theme"] == "人工智能")

    assert all(item["name"] != "机器人" for item in ai["related_symbols"])


def test_theme_recommendations_keep_symbols_in_same_theme_positive_context(db):
    news_eye_service.ensure_news_tables(db)
    rows = [
        {
            "digest": "finance-noise".ljust(64, "0"),
            "dedupe_key": "finance-noise",
            "content": "财政部发布通知，推进金融支持实体经济和医保基金监管。永创智能公告称包装设备订单增长。",
            "published_at": "2026-05-10T09:00:00",
            "source": "财政部",
            "url": "https://example.com/finance-noise",
            "sentiment": "positive",
            "positive_sectors_json": json.dumps(["金融"], ensure_ascii=False),
            "negative_sectors_json": "[]",
            "positive_symbols_json": json.dumps([{"symbol": "603901.SH", "name": "永创智能"}], ensure_ascii=False),
            "negative_symbols_json": "[]",
            "related_symbols_json": json.dumps([{"symbol": "603901.SH", "name": "永创智能"}], ensure_ascii=False),
            "fetched_at": "2026-05-10T09:01:00",
        },
        {
            "digest": "finance-bank".ljust(64, "0"),
            "dedupe_key": "finance-bank",
            "content": "平安银行业绩增长，银行和金融科技服务改善。",
            "published_at": "2026-05-10T09:10:00",
            "source": "财联社电报",
            "url": "https://example.com/finance-bank",
            "sentiment": "positive",
            "positive_sectors_json": json.dumps(["银行"], ensure_ascii=False),
            "negative_sectors_json": "[]",
            "positive_symbols_json": json.dumps([{"symbol": "000001.SZ", "name": "平安银行"}], ensure_ascii=False),
            "negative_symbols_json": "[]",
            "related_symbols_json": json.dumps([{"symbol": "000001.SZ", "name": "平安银行"}], ensure_ascii=False),
            "fetched_at": "2026-05-10T09:11:00",
        },
        {
            "digest": "finance-street".ljust(64, "0"),
            "dedupe_key": "finance-street",
            "content": "金融街4月和5月至今销售签约金额较一季度提升。",
            "published_at": "2026-05-10T09:20:00",
            "source": "新浪7x24",
            "url": "https://example.com/finance-street",
            "sentiment": "positive",
            "positive_sectors_json": json.dumps(["金融"], ensure_ascii=False),
            "negative_sectors_json": "[]",
            "positive_symbols_json": json.dumps([{"symbol": "000402.SZ", "name": "金 融 街"}], ensure_ascii=False),
            "negative_symbols_json": "[]",
            "related_symbols_json": json.dumps([{"symbol": "000402.SZ", "name": "金 融 街"}], ensure_ascii=False),
            "fetched_at": "2026-05-10T09:21:00",
        },
        {
            "digest": "finance-research".ljust(64, "0"),
            "dedupe_key": "finance-research",
            "content": "中邮证券：维持永创智能增持评级。中邮证券研报指出，永创智能业绩增长。",
            "published_at": "2026-05-10T09:30:00",
            "source": "新浪7x24",
            "url": "https://example.com/finance-research",
            "sentiment": "positive",
            "positive_sectors_json": json.dumps(["证券"], ensure_ascii=False),
            "negative_sectors_json": "[]",
            "positive_symbols_json": json.dumps([{"symbol": "603901.SH", "name": "永创智能"}], ensure_ascii=False),
            "negative_symbols_json": "[]",
            "related_symbols_json": json.dumps([{"symbol": "603901.SH", "name": "永创智能"}], ensure_ascii=False),
            "fetched_at": "2026-05-10T09:31:00",
        },
    ]
    db.execute(
        text(
            """
            INSERT INTO market_news_items (
                digest, dedupe_key, content, published_at, source, url, sentiment,
                positive_sectors_json, negative_sectors_json, positive_symbols_json,
                negative_symbols_json, related_symbols_json, fetched_at
            )
            VALUES (
                :digest, :dedupe_key, :content, :published_at, :source, :url, :sentiment,
                :positive_sectors_json, :negative_sectors_json, :positive_symbols_json,
                :negative_symbols_json, :related_symbols_json, :fetched_at
            )
            """
        ),
        rows,
    )
    db.commit()

    finance = next(item for item in _ranking(db) if item["theme"] == "金融")

    assert {"symbol": "000001.SZ", "name": "平安银行"} in finance["related_symbols"]
    assert all(item["name"] != "永创智能" for item in finance["related_symbols"])
    assert all(item["name"] != "金 融 街" for item in finance["related_symbols"])


def test_llm_core_stock_suggestions_replace_text_extraction(db, monkeypatch):
    stock_map = {
        "603019.SH": "中科曙光",
        "601688.SH": "华泰证券",
    }
    monkeypatch.setattr(news_eye_service, "get_reverse_stock_map", lambda: stock_map)
    monkeypatch.setattr(news_theme_service, "get_reverse_stock_map", lambda: stock_map)
    _seed_news(
        db,
        monkeypatch,
        [
            {
                "content": "国务院印发人工智能行动方案，人工智能产业获得专项支持",
                "published_at": "2026-05-10T09:00:00",
                "source": "国务院",
                "url": "https://example.com/ai-policy",
            },
            {
                "content": "人工智能公司减持，人工智能板块承压",
                "published_at": "2026-05-10T09:10:00",
                "source": "财联社电报",
                "url": "https://example.com/ai-risk",
            },
        ],
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        news_theme_service,
        "_resolve_core_stock_llm_config",
        lambda db, user_id: {"provider": "mock", "model": "mock-model", "base_url": None, "api_key": None},
    )
    monkeypatch.setattr(news_theme_service, "_llm_symbol_suggestions_sync_enabled", lambda: True)

    def fake_invoke(config, context):
        captured["context"] = context
        return {
            "items": [
                {
                    "theme": "人工智能",
                    "symbols": [
                        {"symbol": "603019.SH", "name": "中科曙光", "reason": "算力基础设施核心标的"},
                        {"symbol": "601688.SH", "name": "华泰证券", "reason": "研报来源，应该被过滤"},
                    ],
                }
            ]
        }

    monkeypatch.setattr(news_theme_service, "_invoke_core_stock_llm", fake_invoke)

    ai = next(item for item in news_theme_service.refresh_theme_rankings(
        db,
        windows=("premarket",),
        limit=20,
        persist=True,
        now=datetime(2026, 5, 10, 10, 0, 0),
        user_id="user-1",
    )["premarket"] if item["theme"] == "人工智能")

    assert ai["related_symbols"] == [{"symbol": "603019.SH", "name": "中科曙光"}]
    assert ai["symbol_suggestion_source"] == "llm:mock/mock-model"
    evidence_text = json.dumps(captured["context"], ensure_ascii=False)
    assert "专项支持" in evidence_text
    assert "减持" not in evidence_text


def test_llm_core_stock_suggestions_can_refresh_async_without_blocking_page(db, monkeypatch):
    stock_map = {"603019.SH": "中科曙光"}
    monkeypatch.setattr(news_eye_service, "get_reverse_stock_map", lambda: stock_map)
    monkeypatch.setattr(news_theme_service, "get_reverse_stock_map", lambda: stock_map)
    monkeypatch.setattr(
        news_theme_service,
        "_resolve_core_stock_llm_config",
        lambda db, user_id: {"provider": "mock", "model": "mock-model", "base_url": None, "api_key": None},
    )
    monkeypatch.setattr(news_theme_service, "_llm_symbol_suggestions_sync_enabled", lambda: False)

    started: dict[str, object] = {}

    def fake_queue(**kwargs):
        started["window"] = kwargs["window"]
        started["evidence_hash"] = kwargs["evidence_hash"]
        started["prompt_items"] = kwargs["prompt_items"]
        started["config"] = kwargs["config"]
        return True

    monkeypatch.setattr(news_theme_service, "_queue_core_stock_suggestion_refresh", fake_queue)

    _seed_news(
        db,
        monkeypatch,
        [
            {
                "content": "国务院印发人工智能行动方案，人工智能产业获得专项支持",
                "published_at": "2026-05-10T09:00:00",
                "source": "国务院",
                "url": "https://example.com/ai-policy",
            }
        ],
    )

    ranking = news_theme_service.refresh_theme_rankings(
        db,
        windows=("premarket",),
        limit=20,
        persist=True,
        now=datetime(2026, 5, 10, 10, 0, 0),
        user_id="user-1",
    )["premarket"]

    ai = next(item for item in ranking if item["theme"] == "人工智能")
    assert ai["symbol_suggestion_source"] == "fallback:positive_news"
    assert isinstance(ai["related_symbols"], list)
    assert started["window"] == "premarket"
    assert started["prompt_items"]


def test_error_cache_temporarily_hides_repeated_llm_failures(db, monkeypatch):
    stock_map = {"603019.SH": "中科曙光"}
    monkeypatch.setattr(news_eye_service, "get_reverse_stock_map", lambda: stock_map)
    monkeypatch.setattr(news_theme_service, "get_reverse_stock_map", lambda: stock_map)
    monkeypatch.setattr(
        news_theme_service,
        "_resolve_core_stock_llm_config",
        lambda db, user_id: {"provider": "mock", "model": "mock-model", "base_url": None, "api_key": None},
    )
    monkeypatch.setattr(news_theme_service, "_llm_symbol_suggestions_sync_enabled", lambda: True)
    monkeypatch.setattr(news_theme_service, "_invoke_core_stock_llm", lambda config, context: (_ for _ in ()).throw(TimeoutError("boom")))
    monkeypatch.setattr(news_theme_service, "LLM_SYMBOL_ERROR_CACHE_TTL_SECONDS", 600)

    _seed_news(
        db,
        monkeypatch,
        [
            {
                "content": "国务院印发人工智能行动方案，人工智能产业获得专项支持",
                "published_at": "2026-05-10T09:00:00",
                "source": "国务院",
                "url": "https://example.com/ai-policy",
            }
        ],
    )

    first = news_theme_service.refresh_theme_rankings(
        db,
        windows=("premarket",),
        limit=20,
        persist=True,
        now=datetime(2026, 5, 10, 10, 0, 0),
        user_id="user-1",
    )["premarket"]
    ai_first = next(item for item in first if item["theme"] == "人工智能")
    assert ai_first["symbol_suggestion_source"] == "fallback:positive_news"

    calls: list[str] = []

    def fail_if_called(config, context):
        calls.append("called")
        raise AssertionError("LLM should not be called again within error cache ttl")

    monkeypatch.setattr(news_theme_service, "_invoke_core_stock_llm", fail_if_called)
    second = news_theme_service.refresh_theme_rankings(
        db,
        windows=("premarket",),
        limit=20,
        persist=True,
        now=datetime(2026, 5, 10, 10, 0, 30),
        user_id="user-1",
    )["premarket"]

    ai_second = next(item for item in second if item["theme"] == "人工智能")
    assert ai_second["symbol_suggestion_source"] == "fallback:positive_news"
    assert not calls


def test_llm_error_cache_is_scoped_by_model_config(db, monkeypatch):
    stock_map = {"603019.SH": "中科曙光"}
    monkeypatch.setattr(news_eye_service, "get_reverse_stock_map", lambda: stock_map)
    monkeypatch.setattr(news_theme_service, "get_reverse_stock_map", lambda: stock_map)
    configs = {
        "bad-user": {"provider": "openai", "model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1", "api_key": None},
        "good-user": {"provider": "openai", "model": "astron-code-latest", "base_url": "https://maas-coding-api.cn-huabei-1.xf-yun.com/v2", "api_key": "key"},
    }
    monkeypatch.setattr(news_theme_service, "_resolve_core_stock_llm_config", lambda db, user_id: configs[user_id])
    monkeypatch.setattr(news_theme_service, "_llm_symbol_suggestions_sync_enabled", lambda: True)
    monkeypatch.setattr(news_theme_service, "LLM_SYMBOL_ERROR_CACHE_TTL_SECONDS", 600)
    calls: list[str] = []

    def fake_invoke(config, context):
        calls.append(str(config["model"]))
        if config["model"] == "gpt-4o-mini":
            raise TimeoutError("bad config")
        return {"items": [{"theme": "人工智能", "symbols": [{"symbol": "603019.SH", "name": "中科曙光"}]}]}

    monkeypatch.setattr(news_theme_service, "_invoke_core_stock_llm", fake_invoke)
    _seed_news(
        db,
        monkeypatch,
        [
            {
                "content": "国务院印发人工智能行动方案，人工智能产业获得专项支持",
                "published_at": "2026-05-10T09:00:00",
                "source": "国务院",
                "url": "https://example.com/ai-policy",
            }
        ],
    )

    failed = news_theme_service.refresh_theme_rankings(
        db,
        windows=("premarket",),
        limit=20,
        persist=True,
        now=datetime(2026, 5, 10, 10, 0, 0),
        user_id="bad-user",
    )["premarket"]
    assert next(item for item in failed if item["theme"] == "人工智能")["symbol_suggestion_source"] == "fallback:positive_news"

    recovered = news_theme_service.refresh_theme_rankings(
        db,
        windows=("premarket",),
        limit=20,
        persist=True,
        now=datetime(2026, 5, 10, 10, 0, 30),
        user_id="good-user",
    )["premarket"]
    ai = next(item for item in recovered if item["theme"] == "人工智能")
    assert ai["related_symbols"] == [{"symbol": "603019.SH", "name": "中科曙光"}]
    assert ai["symbol_suggestion_source"] == "llm:openai/astron-code-latest"
    assert calls == ["gpt-4o-mini", "astron-code-latest"]


def test_llm_core_stock_background_queue_is_single_flight(monkeypatch):
    class FakeThread:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def start(self):
            return None

    monkeypatch.setattr(news_theme_service.threading, "Thread", FakeThread)
    monkeypatch.setattr(news_theme_service, "LLM_SYMBOL_GLOBAL_ERROR_COOLDOWN_SECONDS", 300)
    news_theme_service._CORE_STOCK_SUGGESTION_TASKS.clear()
    news_theme_service._CORE_STOCK_LAST_FAILURE_AT.clear()
    payload = {
        "config": {"provider": "mock", "model": "mock-model"},
        "window": "premarket",
        "evidence_hash": "hash",
        "window_start": datetime(2026, 5, 10, 9, 0, 0),
        "window_end": datetime(2026, 5, 10, 10, 0, 0),
        "prompt_items": [{"theme": "人工智能", "evidence": [{"content": "政策支持"}]}],
    }
    try:
        assert news_theme_service._queue_core_stock_suggestion_refresh(cache_key="cache-1", **payload) is True
        assert news_theme_service._queue_core_stock_suggestion_refresh(cache_key="cache-2", **payload) is False
    finally:
        news_theme_service._CORE_STOCK_SUGGESTION_TASKS.clear()
        news_theme_service._CORE_STOCK_LAST_FAILURE_AT.clear()


def test_llm_core_stock_background_queue_respects_failure_cooldown(monkeypatch):
    news_theme_service._CORE_STOCK_SUGGESTION_TASKS.clear()
    news_theme_service._CORE_STOCK_LAST_FAILURE_AT.clear()
    monkeypatch.setattr(news_theme_service, "LLM_SYMBOL_GLOBAL_ERROR_COOLDOWN_SECONDS", 300)
    config_hash = news_theme_service._make_core_stock_config_hash({"provider": "mock", "model": "mock-model"})
    news_theme_service._CORE_STOCK_LAST_FAILURE_AT[config_hash] = datetime(2026, 5, 10, 10, 0, 0)
    try:
        assert news_theme_service._core_stock_global_failure_cooldown_active(datetime(2026, 5, 10, 10, 4, 0), config_hash=config_hash) is True
        assert news_theme_service._core_stock_global_failure_cooldown_active(datetime(2026, 5, 10, 10, 6, 0), config_hash=config_hash) is False
        other_hash = news_theme_service._make_core_stock_config_hash({"provider": "mock", "model": "other-model"})
        assert news_theme_service._core_stock_global_failure_cooldown_active(datetime(2026, 5, 10, 10, 4, 0), config_hash=other_hash) is False
    finally:
        news_theme_service._CORE_STOCK_SUGGESTION_TASKS.clear()
        news_theme_service._CORE_STOCK_LAST_FAILURE_AT.clear()


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
            CREATE TABLE stock_daily_kline (
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
            INSERT INTO stock_daily_kline (symbol, trade_date, sw_industry_l1, pre_close, close)
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
