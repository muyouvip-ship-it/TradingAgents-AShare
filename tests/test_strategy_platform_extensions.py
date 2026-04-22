from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from api.app import app
from api.routes.strategy_platform import _default_dsl
from api.services.daily_kline_parquet_store import (
    load_daily_kline_slice_from_parquet,
    write_daily_kline_parquet_cache,
)
from api.services.strategy_compute_backend import compute_daily_features
from api.services.strategy_dsl_compiler import compile_strategy_dsl
from scripts.export_daily_kline_to_parquet import export_daily_kline_to_parquet


def test_daily_kline_parquet_roundtrip(tmp_path: Path):
    frame = pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "date": "2024-01-02",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "volume": 100000,
                "amount": 1020000,
                "turnover_rate": 1.2,
                "pre_close": 9.9,
                "float_market_cap": 10000000000,
                "total_market_cap": 15000000000,
                "net_profit_ttm": 500000000,
            }
        ]
    )
    assert write_daily_kline_parquet_cache(frame, root=tmp_path)
    loaded = load_daily_kline_slice_from_parquet(
        symbols=["000001.SZ"],
        start_date="2024-01-01",
        end_date="2024-01-31",
        root=tmp_path,
    )
    assert loaded is not None
    assert loaded.iloc[0]["symbol"] == "000001.SZ"


def test_daily_kline_parquet_loader_supports_mixed_schema(tmp_path: Path):
    first_year = pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "date": "2023-12-29",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "volume": 100000,
                "amount": 1020000,
                "turnover_rate": None,
                "pre_close": 9.9,
                "float_market_cap": 10000000000,
                "total_market_cap": 15000000000,
                "net_profit_ttm": None,
            }
        ]
    )
    second_year = first_year.copy()
    second_year["date"] = "2024-01-02"
    second_year["net_profit_ttm"] = 500000000.5
    first_year.to_parquet(tmp_path / "daily_kline_2023.parquet", index=False)
    second_year.to_parquet(tmp_path / "daily_kline_2024.parquet", index=False)

    loaded = load_daily_kline_slice_from_parquet(
        symbols=["000001.SZ"],
        start_date="2023-01-01",
        end_date="2024-12-31",
        root=tmp_path,
    )

    assert loaded is not None
    assert len(loaded) == 2
    assert loaded["net_profit_ttm"].notna().sum() == 1


def test_export_daily_kline_to_parquet_from_database(tmp_path: Path, monkeypatch):
    database_path = tmp_path / "market.db"
    engine = create_engine(f"sqlite:///{database_path}")
    frame = pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "trade_date": "2024-01-02",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "volume": 100000,
                "amount": 1020000,
                "turnover_rate": 1.2,
                "pre_close": 9.9,
                "float_market_cap": 10000000000,
                "total_market_cap": 15000000000,
                "net_profit_ttm": 500000000,
            }
        ]
    )
    frame.to_sql("stock_daily_kline", engine, index=False)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    result = export_daily_kline_to_parquet(
        start_date="2024-01-01",
        end_date="2024-01-31",
        batch_days=30,
        root=tmp_path / "parquet",
    )
    assert result["row_count"] == 1
    assert result["file_count"] == 1


def test_export_daily_kline_to_parquet_batches_do_not_overlap(tmp_path: Path, monkeypatch):
    database_path = tmp_path / "market.db"
    engine = create_engine(f"sqlite:///{database_path}")
    frame = pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "trade_date": f"2024-01-0{day}",
                "open": 10.0 + day,
                "high": 10.5 + day,
                "low": 9.8 + day,
                "close": 10.2 + day,
                "volume": 100000 + day,
                "amount": 1020000 + day,
                "turnover_rate": 1.2,
                "pre_close": 9.9,
                "float_market_cap": 10000000000,
                "total_market_cap": 15000000000,
                "net_profit_ttm": 500000000,
            }
            for day in range(1, 4)
        ]
    )
    frame.to_sql("stock_daily_kline", engine, index=False)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")

    result = export_daily_kline_to_parquet(
        start_date="2024-01-01",
        end_date="2024-01-03",
        batch_days=1,
        root=tmp_path / "parquet",
    )
    loaded = load_daily_kline_slice_from_parquet(
        symbols=["000001.SZ"],
        start_date="2024-01-01",
        end_date="2024-01-03",
        root=tmp_path / "parquet",
    )

    assert result["row_count"] == 3
    assert loaded is not None
    assert len(loaded) == 3


def test_compute_daily_features_supports_extended_factor_transforms():
    dsl = _default_dsl("portfolio").model_dump()
    dsl["factor_model"]["factors"] = [
        {"name": "amount_zscore_20d", "weight": 0.4, "direction": "higher_better", "transform": "zscore"},
        {"name": "ma_gap_5_20", "weight": 0.3, "direction": "higher_better", "transform": "raw"},
        {"name": "turnover_rate", "weight": 0.3, "direction": "higher_better", "transform": "rank_pct"},
    ]
    compiled = compile_strategy_dsl(dsl)
    frame = pd.DataFrame(
        [
            {
                "symbol": f"00000{idx}.SZ",
                "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=day),
                "open": 10 + idx + day * 0.1,
                "high": 10.5 + idx + day * 0.1,
                "low": 9.8 + idx + day * 0.1,
                "close": 10.2 + idx + day * 0.1,
                "volume": 100000 + idx * 1000 + day * 50,
                "amount": (10.2 + idx + day * 0.1) * (100000 + idx * 1000 + day * 50),
                "turnover_rate": 1.0 + idx * 0.1,
                "pre_close": 10 + idx,
                "float_market_cap": 10000000000 + idx * 1000000,
                "total_market_cap": 15000000000 + idx * 1000000,
                "net_profit_ttm": 500000000 + day * 1000000 + idx * 100000,
            }
            for idx in range(1, 4)
            for day in range(30)
        ]
    )
    features, _ = compute_daily_features(frame, compiled)
    assert "amount_zscore_20d" in features.columns
    assert "ma_gap_5_20" in features.columns
    assert "turnover_rate_signal" in features.columns
    assert "factor_score" in features.columns


def test_paper_routes_persist_orders():
    client = TestClient(app)
    strategy_id = client.get("/v1/strategies").json()["strategies"][0]["id"]
    create_response = client.post(f"/v1/paper/accounts/demo-test/run-strategy?strategy_id={strategy_id}")
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["orders"][0]["signal_source"] in {"latest_backtest_order", "latest_backtest_signal", "default_fallback"}
    orders_response = client.get("/v1/paper/accounts/demo-test/orders")
    positions_response = client.get("/v1/paper/accounts/demo-test/positions")
    equity_response = client.get("/v1/paper/accounts/demo-test/equity")
    assert orders_response.status_code == 200
    assert len(orders_response.json()["orders"]) >= 1
    assert positions_response.status_code == 200
    assert equity_response.status_code == 200


def test_strategy_templates_route_and_template_metadata_persist():
    client = TestClient(app)
    templates_response = client.get("/v1/strategies/templates")
    assert templates_response.status_code == 200
    templates = templates_response.json()["templates"]
    assert len(templates) >= 3
    first_template = templates[0]
    assert first_template["parameters"]

    detail_response = client.get(f"/v1/strategies/templates/{first_template['id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["id"] == first_template["id"]
    assert detail["default_dsl"]["strategy_type"] == detail["strategy_type"]

    create_response = client.post(
        "/v1/strategies",
        json={
            "name": "模板策略保存测试",
            "strategy_type": detail["strategy_type"],
            "description": detail["description"],
            "source": "template",
            "status": "draft",
            "dsl": detail["default_dsl"],
            "template_id": detail["id"],
            "template_name": detail["name"],
            "template_parameters": {
                "top_n": 18,
                "min_score": 0.61,
                "max_positions": 10,
            },
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["template_id"] == detail["id"]
    assert created["template_name"] == detail["name"]
    assert created["template_parameters"]["top_n"] == 18
