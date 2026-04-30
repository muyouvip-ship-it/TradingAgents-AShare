from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.database import Base
from api.services import news_eye_service


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_refresh_news_cache_persists_items_and_sync_state(monkeypatch):
    db = _make_session()
    try:
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
        assert listing["background"]["active_sources"] == ["财联社电报", "东方财富全球快讯"]
        assert "300750.SZ" in (listing["background"]["tracked_symbols"] or [])
        assert any(item["source"] == "财联社电报" for item in listing["items"])
        assert any(symbol["symbol"] == "300750.SZ" for symbol in listing["items"][0]["related_symbols"] + listing["items"][1]["related_symbols"])
    finally:
        db.close()


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
