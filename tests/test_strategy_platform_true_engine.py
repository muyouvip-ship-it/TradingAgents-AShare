from pathlib import Path
from copy import deepcopy

from fastapi.testclient import TestClient

from api.app import app
from api.routes.strategy_platform import _default_dsl
from api.services.a_share_market_rules import get_a_share_market_rule, round_to_tick
from api.services.minute_data_service import evaluate_intraday_confirmation, get_minute_cache_root, load_aggregated_minute_bars
from api.services.strategy_dsl_compiler import compile_strategy_dsl
from api.services.strategy_platform_engine import run_strategy_backtest


def test_compile_strategy_dsl_returns_execution_ir():
    compiled = compile_strategy_dsl(_default_dsl("portfolio").model_dump())
    assert compiled.status == "passed"
    assert compiled.selection_plan["market"] == "A_SHARE"
    assert "1d" in compiled.timeframes_required
    assert "1w" in compiled.timeframes_required
    assert "30m" in compiled.timeframes_required
    assert compiled.minute_requirements["enabled"] is True
    assert compiled.backend_resolution["compute"] in {"polars", "pandas_fallback"}


def test_compile_strategy_dsl_rejects_unknown_schema_fields():
    dsl = _default_dsl("portfolio").model_dump()
    dsl["factor_model"]["unknown_field"] = True
    compiled = compile_strategy_dsl(dsl)
    assert compiled.status == "failed"
    assert any("DSL schema 校验失败" in error for error in compiled.errors)


def test_compile_strategy_dsl_returns_pending_confirmation_for_unknown_factor():
    dsl = _default_dsl("portfolio").model_dump()
    dsl["factor_model"]["factors"][0]["name"] = "custom_alpha_x"
    compiled = compile_strategy_dsl(dsl)

    assert compiled.status == "passed"
    assert compiled.pending_confirmations
    assert compiled.pending_confirmations[0]["kind"] == "unknown_factor"


def test_compile_strategy_dsl_blocks_future_function_fields():
    dsl = _default_dsl("portfolio").model_dump()
    dsl["entry"]["conditions"][0]["indicator"] = "future_return_5d"
    compiled = compile_strategy_dsl(dsl)

    assert compiled.status == "failed"
    assert compiled.future_function_risks
    assert any("疑似未来函数" in error for error in compiled.errors)


def test_llm_draft_exposes_structured_output_schema_and_compile_report():
    client = TestClient(app)
    schema_response = client.get("/v1/strategies/dsl-schema")
    assert schema_response.status_code == 200
    schema_payload = schema_response.json()
    assert schema_payload["structured_outputs"] is True
    assert "json_schema" in schema_payload

    draft_response = client.post("/v1/strategies/llm-draft", json={"prompt": "创建算力板块业绩暴增选股策略"})
    assert draft_response.status_code == 200
    draft_payload = draft_response.json()
    assert draft_payload["compile_report"]["status"] == "passed"
    assert draft_payload["structured_output_schema"]["title"] == "StrategyDslSchema"
    assert draft_payload["llm_runtime"]["shared_with_settings"] is True
    assert draft_payload["llm_runtime"]["source"] in {"server_default", "user_settings"}
    assert "api_key" not in draft_payload["llm_runtime"]


def test_llm_draft_respects_requested_selection_strategy_type():
    client = TestClient(app)
    response = client.post(
        "/v1/strategies/llm-draft",
        json={
            "prompt": "创建一个选股策略：算力板块、市值100亿到200亿、业绩高增长，只做选股不做交易",
            "strategy_type": "selection",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["strategy_type"] == "selection"
    assert payload["dsl"]["strategy_type"] == "selection"
    assert payload["dsl"]["entry"]["conditions"] == []
    assert payload["dsl"]["exit"]["conditions"] == []


def test_factor_registry_routes_expose_builtin_metadata():
    client = TestClient(app)
    list_response = client.get("/v1/factors")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["total"] >= 8
    names = {item["name"] for item in payload["items"]}
    assert "money_flow_strength_20d" in names

    detail_response = client.get("/v1/factors/money_flow_strength_20d")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["display_name"] == "20日资金强度"
    assert "amount" in detail["required_fields"]
    assert "polars" in detail["backend_support"]


def test_strategy_clone_and_version_routes():
    client = TestClient(app)
    strategy = client.get("/v1/strategies").json()["strategies"][0]
    strategy_id = strategy["id"]

    clone_response = client.post(f"/v1/strategies/{strategy_id}/clone", json={"name": "克隆策略测试"})
    assert clone_response.status_code == 200
    cloned = clone_response.json()
    assert cloned["name"] == "克隆策略测试"
    assert cloned["id"] != strategy_id

    versions_response = client.get(f"/v1/strategies/{strategy_id}/versions")
    assert versions_response.status_code == 200
    assert versions_response.json()["versions"]

    dsl = strategy["current_version"]["dsl"]
    dsl["factor_model"]["select"]["min_score"] = 0.7
    version_response = client.post(
        f"/v1/strategies/{strategy_id}/versions",
        json={"dsl": dsl, "change_summary": "提高选股阈值", "activate": True},
    )
    assert version_response.status_code == 200
    updated = version_response.json()
    assert updated["version"] >= 2
    assert updated["current_version"]["change_summary"] == "提高选股阈值"

    activate_response = client.post(f"/v1/strategies/{strategy_id}/activate", json={"status": "active"})
    assert activate_response.status_code == 200
    assert activate_response.json()["status"] == "active"


def test_minute_aggregation_and_confirmation_work_with_fallback():
    aggregated = load_aggregated_minute_bars(
        symbols=["300750.SZ"],
        trade_date="2024-10-08",
        timeframe="30m",
    )
    assert aggregated.timeframe == "30m"
    assert aggregated.items
    first = aggregated.items[0]
    assert {"symbol", "bar_start", "bar_end", "open", "high", "low", "close", "volume", "amount", "vwap"} <= set(first.keys())

    confirmation = evaluate_intraday_confirmation(
        symbols=["300750.SZ"],
        trade_date="2024-10-08",
        timeframe="30m",
    )
    assert confirmation.items
    assert "confirmed" in confirmation.items[0]


def test_minute_cache_root_and_parquet_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("MINUTE_CACHE_ROOT", str(tmp_path / "minute_cache"))
    aggregated = load_aggregated_minute_bars(
        symbols=["300750.SZ"],
        trade_date="2024-10-08",
        timeframe="15m",
    )

    assert get_minute_cache_root() == tmp_path / "minute_cache"
    assert aggregated.cache_path
    assert Path(aggregated.cache_path).exists()
    if aggregated.parquet_cache_path:
        assert Path(aggregated.parquet_cache_path).exists()


def test_backtest_endpoint_returns_minute_engine_diagnostics():
    client = TestClient(app)
    strategy_id = client.get("/v1/strategies").json()["strategies"][0]["id"]
    response = client.post(
        "/v1/backtests",
        json={
            "strategy_id": strategy_id,
            "symbols": ["300750.SZ", "300520.SZ"],
            "start_date": "2024-09-01",
            "end_date": "2024-12-31",
            "initial_capital": 1_000_000,
            "frequency": "daily_minute",
            "benchmark": "沪深300",
            "use_minute_confirm": True,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert "engine_mode" in payload["result"]["summary"]
    assert "watchlist_days" in payload["result"]["summary"]
    assert "confirm_hit_rate" in payload["result"]["diagnostics"]
    assert "universe_filter" in payload["result"]["diagnostics"]
    assert "order_count" in payload["result"]["diagnostics"]
    assert "risk_event_count" in payload["result"]["diagnostics"]
    run_id = payload["id"]
    watchlists = client.get(f"/v1/backtests/{run_id}/watchlists").json()["items"]
    confirmations = client.get(f"/v1/backtests/{run_id}/minute-confirmations").json()["items"]
    orders = client.get(f"/v1/backtests/{run_id}/orders").json()["items"]
    metrics_response = client.get(f"/v1/backtests/{run_id}/metrics")
    paged_watchlists = client.get(f"/v1/backtests/{run_id}/watchlists?limit=1&sort_by=rank&sort_order=asc").json()
    assert watchlists
    assert confirmations
    assert orders
    assert metrics_response.status_code == 200
    assert metrics_response.json()["metrics"]["final_capital"] > 0
    assert paged_watchlists["total"] >= 1
    assert len(paged_watchlists["items"]) == 1


def test_backtest_endpoint_supports_walk_forward():
    client = TestClient(app)
    strategy_id = client.get("/v1/strategies").json()["strategies"][0]["id"]
    response = client.post(
        "/v1/backtests",
        json={
            "strategy_id": strategy_id,
            "symbols": ["300750.SZ", "300520.SZ", "601136.SH"],
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "initial_capital": 1_000_000,
            "frequency": "daily",
            "benchmark": "沪深300",
            "use_minute_confirm": False,
            "walk_forward": {
                "enabled": True,
                "train_days": 40,
                "test_days": 20,
                "step_days": 20,
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["summary"]["walk_forward_enabled"] is True
    assert payload["result"]["diagnostics"]["walk_forward"]["enabled"] is True
    assert payload["result"]["diagnostics"]["walk_forward"]["window_count"] >= 1


def test_a_share_market_rules_are_board_aware():
    main_rule = get_a_share_market_rule("600000.SH")
    chinext_rule = get_a_share_market_rule("300750.SZ")
    star_rule = get_a_share_market_rule("688001.SH")
    bse_rule = get_a_share_market_rule("830000.BJ")
    st_rule = get_a_share_market_rule("600000.SH", is_st=True)

    assert main_rule.daily_limit_pct == 0.10
    assert chinext_rule.daily_limit_pct == 0.20
    assert star_rule.daily_limit_pct == 0.20
    assert bse_rule.daily_limit_pct == 0.30
    assert st_rule.daily_limit_pct == 0.05
    assert round_to_tick(10.006) == 10.01


def test_position_models_generate_distinct_allocations():
    base_dsl = _default_dsl("portfolio").model_dump()
    base_dsl["universe"]["min_listing_days"] = 1
    base_dsl["universe"]["filters"] = []
    base_dsl["factor_model"]["select"] = {"top_n": 3, "min_score": 0.3}
    base_dsl["risk"].update(
        {
            "max_positions": 3,
            "take_profit_pct": 1.5,
            "trailing_stop_pct": 0.8,
            "max_drawdown_pct": 1.0,
            "max_daily_loss_pct": 1.0,
        }
    )
    base_dsl["position"].update(
        {
            "max_single_position_pct": 0.35,
            "max_position_pct": 1.0,
            "cash_reserve_pct": 0.0,
            "initial_position_pct": 0.18,
            "risk_per_trade_pct": 0.01,
            "target_volatility_pct": 0.12,
        }
    )
    symbols = ["300750.SZ", "300520.SZ", "601136.SH"]
    results = {}
    for method in ("equal_weight", "factor_weight", "volatility_target", "risk_budget"):
        dsl = deepcopy(base_dsl)
        dsl["position"]["method"] = method
        result = run_strategy_backtest(
            run_id=f"unit_position_model_{method}",
            strategy_name=f"{method}测试",
            dsl=dsl,
            symbols=symbols,
            start_date="2024-01-01",
            end_date="2024-06-30",
            initial_capital=1_000_000,
            frequency="daily",
            benchmark="沪深300",
            use_minute_confirm=False,
        )
        results[method] = result
        buy_orders = [item for item in result.orders if item["side"] == "buy" and not item.get("is_pyramid_add")]
        assert buy_orders
        assert all(item.get("allocation_method") for item in buy_orders)

    def allocations_by_day(result):
        buy_orders = [item for item in result.orders if item["side"] == "buy" and not item.get("is_pyramid_add")]
        mapping = {}
        for item in buy_orders:
            mapping.setdefault(item["signal_date"], []).append(round(float(item.get("allocation_cash") or 0.0), 2))
        return mapping

    equal_allocations = allocations_by_day(results["equal_weight"])
    factor_allocations = allocations_by_day(results["factor_weight"])
    vol_allocations = allocations_by_day(results["volatility_target"])
    risk_allocations = allocations_by_day(results["risk_budget"])
    first_equal_allocations = equal_allocations[min(equal_allocations)]

    assert len(first_equal_allocations) >= 2
    assert max(first_equal_allocations) - min(first_equal_allocations) < 1
    assert any(
        factor_allocations.get(signal_date) != equal_allocations.get(signal_date)
        for signal_date in set(equal_allocations) & set(factor_allocations)
    )
    assert any(
        vol_allocations.get(signal_date) != equal_allocations.get(signal_date)
        for signal_date in set(equal_allocations) & set(vol_allocations)
    )
    assert risk_allocations


def test_pyramid_add_orders_are_generated():
    dsl = _default_dsl("portfolio").model_dump()
    dsl["universe"]["min_listing_days"] = 1
    dsl["universe"]["filters"] = []
    dsl["factor_model"]["select"] = {"top_n": 1, "min_score": 0.2}
    dsl["position"].update(
        {
            "method": "risk_budget",
            "initial_position_pct": 0.1,
            "max_single_position_pct": 0.4,
            "max_position_pct": 1.0,
            "cash_reserve_pct": 0.0,
            "risk_per_trade_pct": 0.01,
            "pyramid_enabled": True,
            "pyramid_max_adds": 2,
            "pyramid_trigger_pct": 0.015,
            "pyramid_scale_pct": 0.5,
        }
    )
    dsl["risk"].update(
        {
            "max_positions": 1,
            "stop_loss_pct": 0.3,
            "take_profit_pct": 2.0,
            "trailing_stop_pct": 0.8,
            "max_drawdown_pct": 1.0,
            "max_daily_loss_pct": 1.0,
        }
    )
    result = run_strategy_backtest(
        run_id="unit_pyramid_add",
        strategy_name="金字塔加仓测试",
        dsl=dsl,
        symbols=["300750.SZ"],
        start_date="2024-01-01",
        end_date="2024-07-31",
        initial_capital=1_000_000,
        frequency="daily",
        benchmark="沪深300",
        use_minute_confirm=False,
    )
    pyramid_orders = [item for item in result.orders if item["side"] == "buy" and item.get("is_pyramid_add")]
    pyramid_trades = [item for item in result.trades if item["direction"] == "buy" and item.get("is_pyramid_add")]
    assert pyramid_orders
    assert pyramid_trades
    assert all(item["reason"] == "pyramid_add" for item in pyramid_orders)


def test_universe_filters_and_order_artifact_are_written():
    dsl = _default_dsl("portfolio").model_dump()
    dsl["universe"]["min_listing_days"] = 1
    dsl["universe"]["filters"] = [
        {"field": "float_market_cap", "op": "between", "value": [10_000_000_000, 14_000_000_000], "unit": "CNY"}
    ]
    dsl["factor_model"]["select"] = {"top_n": 5, "min_score": 0.5}
    result = run_strategy_backtest(
        run_id="unit_universe_orders",
        strategy_name="股票池过滤订单测试",
        dsl=dsl,
        symbols=["300750.SZ", "300520.SZ", "601136.SH"],
        start_date="2024-01-01",
        end_date="2024-06-30",
        initial_capital=1_000_000,
        frequency="daily",
        benchmark="沪深300",
        use_minute_confirm=False,
    )

    assert result.diagnostics["universe_filter"]["applied_filters"]
    assert result.diagnostics["universe_filter"]["concept_filter"]["status"] in {"metadata_missing", "applied", "not_requested", "no_match_fallback"}
    assert result.orders
    assert result.diagnostics["order_count"] == len(result.orders)
    assert "orders" in {path.name.removesuffix(".json") for path in Path(result.artifact_root).glob("*.json")}


def test_evolution_detail_and_paper_account_create_routes():
    client = TestClient(app)
    strategy_id = client.get("/v1/strategies").json()["strategies"][0]["id"]
    experiment_response = client.post("/v1/evolution/experiments", json={"strategy_id": strategy_id})
    assert experiment_response.status_code == 200
    experiment_id = experiment_response.json()["id"]
    detail_response = client.get(f"/v1/evolution/experiments/{experiment_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == experiment_id
    candidates_response = client.get(f"/v1/evolution/experiments/{experiment_id}/candidates")
    assert candidates_response.status_code == 200
    assert candidates_response.json()["candidates"]

    account_response = client.post(
        "/v1/paper/accounts",
        json={"id": "paper-route-test", "name": "纸交易测试账户", "initial_capital": 500000},
    )
    assert account_response.status_code in {200, 409}
    if account_response.status_code == 200:
        assert account_response.json()["cash"] == 500000


def test_backtest_cancel_and_compare_routes():
    client = TestClient(app)
    strategy_id = client.get("/v1/strategies").json()["strategies"][0]["id"]

    payload = {
        "strategy_id": strategy_id,
        "symbols": ["300750.SZ", "300520.SZ"],
        "start_date": "2024-09-01",
        "end_date": "2024-12-31",
        "initial_capital": 1_000_000,
        "frequency": "daily_minute",
        "benchmark": "沪深300",
        "use_minute_confirm": True,
    }
    first = client.post("/v1/backtests", json=payload)
    second = client.post("/v1/backtests", json={**payload, "symbols": ["300750.SZ"]})

    assert first.status_code == 200
    assert second.status_code == 200

    first_run_id = first.json()["id"]
    second_run_id = second.json()["id"]

    cancel_response = client.post(f"/v1/backtests/{first_run_id}/cancel")
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "completed"

    compare_response = client.post("/v1/backtests/compare", json={"run_ids": [first_run_id, second_run_id]})
    assert compare_response.status_code == 200
    compare_payload = compare_response.json()
    assert compare_payload["run_ids"] == [first_run_id, second_run_id]
    assert len(compare_payload["runs"]) == 2
    assert "total_return" in compare_payload["summary"]
    assert compare_payload["runs"][0]["diagnostics"]["engine_mode"] in {"true_engine", "fallback"}
