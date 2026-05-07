from __future__ import annotations

import pytest

from tests.postgres_test_utils import isolated_postgres_session
from api.database import Base
from api.services import news_eye_service


@pytest.fixture
def db():
    with isolated_postgres_session(Base, schema_prefix="ta_news_eye") as session:
        yield session


def test_refresh_news_cache_persists_items_and_sync_state(db, monkeypatch):
    monkeypatch.setattr(
        news_eye_service,
        "_fetch_external_news",
        lambda limit, symbols: (
            [
                {
                    "content": "宁德时代签约扩产，锂电池板块走强",
                    "published_at": "2026-04-30T20:30:00",
                    "source": "财联社电报",
                    "url": "https://example.com/a",
                    "seed_symbols": ["300750.SZ"],
                },
                {
                    "content": "平安银行一季报增长超预期",
                    "published_at": "2026-04-30T20:31:00",
                    "source": "东方财富全球快讯",
                    "url": "https://example.com/b",
                    "seed_symbols": ["000001.SZ"],
                },
            ],
            ["财联社电报", "东方财富全球快讯"],
            [],
        ),
    )

    result = news_eye_service.refresh_news_cache(
        db,
        limit=20,
        symbols=["300750.SZ", "000001.SZ"],
        trigger="manual",
    )

    assert result["saved"] == 2
    listing = news_eye_service.list_news_items(db, limit=20)
    assert listing["total"] == 2
    assert listing["history"]["total_available"] == 2
    assert listing["background"]["active_sources"] == ["财联社电报", "东方财富全球快讯"]
    assert "300750.SZ" in (listing["background"]["tracked_symbols"] or [])
    assert any(item["source"] == "财联社电报" for item in listing["items"])
    assert any(symbol["symbol"] == "300750.SZ" for symbol in listing["items"][0]["related_symbols"] + listing["items"][1]["related_symbols"])


def test_fetch_external_news_collects_general_and_symbol_sources(monkeypatch):
    import pandas as pd
    import akshare as ak

    monkeypatch.setattr(
        ak,
        "stock_info_global_cls",
        lambda symbol="全部": pd.DataFrame(
            [{"标题": "财联社快讯", "内容": "算力方向再获催化", "发布日期": "2026-04-30", "发布时间": "20:10:00"}]
        ),
    )
    monkeypatch.setattr(
        ak,
        "stock_info_global_em",
        lambda: pd.DataFrame(
            [{"标题": "东财快讯", "摘要": "人工智能板块活跃", "发布时间": "2026-04-30 20:11:00", "链接": "https://example.com/em"}]
        ),
    )
    monkeypatch.setattr(ak, "stock_info_global_ths", lambda: pd.DataFrame())
    monkeypatch.setattr(ak, "stock_info_global_sina", lambda: pd.DataFrame())
    monkeypatch.setattr(ak, "stock_info_global_futu", lambda: pd.DataFrame())
    monkeypatch.setattr(ak, "stock_info_cjzc_em", lambda: pd.DataFrame())
    monkeypatch.setattr(
        ak,
        "stock_news_em",
        lambda symbol="300750": pd.DataFrame(
            [{"标题": "宁德时代新闻", "内容": "宁德时代订单增长", "发布时间": "2026-04-30 20:12:00", "链接": "https://example.com/symbol"}]
        ),
    )

    items, active_sources, warnings = news_eye_service._fetch_external_news(20, symbols=["300750.SZ"])

    assert len(items) >= 3
    assert "财联社电报" in active_sources
    assert "东方财富全球快讯" in active_sources
    assert any(source.startswith("东方财富个股新闻:300750.SZ") for source in active_sources)
    assert not any("拉取失败" in warning for warning in warnings)


def test_extract_impact_payload_separates_positive_and_negative_entities(monkeypatch):
    monkeypatch.setattr(
        news_eye_service,
        "get_reverse_stock_map",
        lambda: {
            "300750.SZ": "宁德时代",
            "000001.SZ": "平安银行",
        },
    )

    positive_sectors, negative_sectors, positive_symbols, negative_symbols, sentiment = news_eye_service._extract_impact_payload(
        "宁德时代签约扩产，锂电池板块走强；平安银行遭处罚，银行板块承压"
    )

    assert sentiment == "neutral"
    assert "锂电池" in positive_sectors
    assert "银行" in negative_sectors
    assert "300750.SZ" in positive_symbols
    assert "000001.SZ" in negative_symbols


def test_extract_symbols_matches_stock_codes_and_names_without_duplicate_hits(monkeypatch):
    monkeypatch.setattr(
        news_eye_service,
        "get_reverse_stock_map",
        lambda: {
            "300750.SZ": "宁德时代",
            "000001.SZ": "平安银行",
        },
    )

    symbols = news_eye_service._extract_symbols("宁德时代公告扩产，300750 再获关注，平安银行维持稳健增长")

    assert symbols == ["300750.SZ", "000001.SZ"]


def test_enrich_news_item_falls_back_to_seed_symbol_for_positive_story(monkeypatch):
    monkeypatch.setattr(news_eye_service, "get_reverse_stock_map", lambda: {})

    enriched = news_eye_service._enrich_news_item(
        {
            "content": "公司签约扩产，订单增长超预期",
            "published_at": "2026-04-30T20:31:00",
            "source": "东方财富个股新闻",
            "seed_symbols": ["300750.SZ"],
        }
    )

    positive_symbols = news_eye_service._loads(enriched["positive_symbols_json"])
    related_symbols = news_eye_service._loads(enriched["related_symbols_json"])

    assert enriched["sentiment"] == "positive"
    assert any(item["symbol"] == "300750.SZ" for item in positive_symbols)
    assert any(item["symbol"] == "300750.SZ" for item in related_symbols)


def test_list_news_items_supports_offset_history(db, monkeypatch):
    monkeypatch.setattr(
        news_eye_service,
        "_fetch_external_news",
        lambda limit, symbols: (
            [
                {
                    "content": f"第{i}条快讯，宁德时代订单增长",
                    "published_at": f"2026-04-30T20:{i:02d}:00",
                    "source": "财联社电报",
                    "url": f"https://example.com/{i}",
                    "seed_symbols": ["300750.SZ"],
                }
                for i in range(5)
            ],
            ["财联社电报"],
            [],
        ),
    )
    news_eye_service.refresh_news_cache(db, limit=10, symbols=["300750.SZ"], trigger="manual")

    first_page = news_eye_service.list_news_items(db, limit=2, offset=0)
    second_page = news_eye_service.list_news_items(db, limit=2, offset=2)

    assert first_page["total"] == 5
    assert first_page["history"]["has_more"] is True
    assert first_page["history"]["returned"] == 2
    assert second_page["history"]["offset"] == 2
    assert len(second_page["items"]) == 2


def test_list_news_items_filters_by_symbol_and_sector_via_index_tables(db, monkeypatch):
    monkeypatch.setattr(
        news_eye_service,
        "_fetch_external_news",
        lambda limit, symbols: (
            [
                {
                    "content": "宁德时代签约扩产，锂电池板块走强",
                    "published_at": "2026-04-30T20:30:00",
                    "source": "财联社电报",
                    "url": "https://example.com/a1",
                    "seed_symbols": ["300750.SZ"],
                },
                {
                    "content": "平安银行遭处罚，银行板块承压",
                    "published_at": "2026-04-30T20:31:00",
                    "source": "东方财富全球快讯",
                    "url": "https://example.com/a2",
                    "seed_symbols": ["000001.SZ"],
                },
            ],
            ["财联社电报", "东方财富全球快讯"],
            [],
        ),
    )
    monkeypatch.setattr(
        news_eye_service,
        "get_reverse_stock_map",
        lambda: {
            "300750.SZ": "宁德时代",
            "000001.SZ": "平安银行",
        },
    )

    news_eye_service.refresh_news_cache(db, limit=10, symbols=["300750.SZ", "000001.SZ"], trigger="manual")

    symbol_filtered = news_eye_service.list_news_items(db, limit=10, symbol="300750.SZ")
    sector_filtered = news_eye_service.list_news_items(db, limit=10, sector="银行")

    assert len(symbol_filtered["items"]) == 1
    assert symbol_filtered["items"][0]["source"] == "财联社电报"
    assert len(sector_filtered["items"]) == 1
    assert sector_filtered["items"][0]["source"] == "东方财富全球快讯"


def test_parse_news_analysis_payload_strips_code_fences():
    parsed = news_eye_service._parse_news_analysis_payload(
        """```json
        {"summary":"测试","sentiment":"positive","sentiment_reason":"订单增长","positive_sectors":["锂电池"],"negative_sectors":[],"positive_symbols":["宁德时代(300750.SZ)"],"negative_symbols":[],"trading_takeaway":"关注持续性"}
        ```"""
    )

    assert parsed is not None
    assert parsed["sentiment"] == "positive"


def test_is_a_share_relevant_news_filters_overseas_noise(monkeypatch):
    monkeypatch.setattr(news_eye_service, "get_reverse_stock_map", lambda: {})

    assert news_eye_service._is_a_share_relevant_news({
        "content": "证监会表示将持续完善上市公司分红制度，A股红利板块受关注",
        "source": "财联社电报",
    }) is True
    assert news_eye_service._is_a_share_relevant_news({
        "content": "道琼斯指数收涨，微软和亚马逊领涨美股科技股",
        "source": "东方财富全球快讯",
    }) is False
    assert news_eye_service._is_a_share_relevant_news({
        "content": "美联储释放降息预期，原油与铜价走高，有望带动A股有色板块情绪",
        "source": "东方财富全球快讯",
    }) is True
