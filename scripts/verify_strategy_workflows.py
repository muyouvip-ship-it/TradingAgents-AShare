#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


BASE_URL = "http://127.0.0.1:8500"
START_DATE = "2025-01-02"
END_DATE = "2025-01-15"
POLL_TIMEOUT_SECONDS = 180
POLL_INTERVAL_SECONDS = 1.0


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


def request_json(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"detail": raw}
        raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {parsed}") from exc


def backtest_payload(strategy: dict[str, Any], universe: dict[str, Any] | None = None) -> dict[str, Any]:
    strategy_type = strategy.get("strategy_type") or "portfolio"
    is_selection = strategy_type == "selection"
    mode = "daily_only" if is_selection else "daily_select_intraday_trade"
    frequency = "daily" if is_selection else "daily_minute"
    return {
        "strategy_id": strategy["id"],
        "start_date": START_DATE,
        "end_date": END_DATE,
        "initial_capital": 1_000_000,
        "frequency": frequency,
        "benchmark": "沪深300",
        "use_minute_confirm": not is_selection,
        "backtest_mode": mode,
        "universe": universe or {"scope": "all"},
        "cost_config": {
            "commission_rate": 0.0003,
            "min_commission": 5,
            "stamp_duty_rate": 0.001,
            "slippage_rate": 0.001,
        },
        "minute_config": {
            "lazy_load": True,
            "execution_granularity": "daily" if is_selection else "minute",
            "missing_data_policy": "skip",
        },
        "walk_forward": {},
    }


def wait_backtest(run_id: str) -> dict[str, Any]:
    deadline = time.time() + POLL_TIMEOUT_SECONDS
    latest: dict[str, Any] = {}
    while time.time() < deadline:
        latest = request_json("GET", f"/v1/backtests/{run_id}")
        if latest.get("status") in {"completed", "failed", "cancelled"}:
            return latest
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"回测 {run_id} 超时，最后状态：{latest}")


def count_endpoint(run_id: str, suffix: str) -> int:
    try:
        response = request_json("GET", f"/v1/backtests/{run_id}/{suffix}")
        return len(response.get("items") or [])
    except Exception:
        return -1


def verify_run(strategy: dict[str, Any], run: dict[str, Any]) -> CheckResult:
    strategy_type = strategy.get("strategy_type")
    summary = ((run.get("result") or {}).get("summary") or {})
    diagnostics = ((run.get("result") or {}).get("diagnostics") or {})
    run_id = run["id"]
    endpoint_counts = {
        "watchlists": count_endpoint(run_id, "watchlists"),
        "minute_confirmations": count_endpoint(run_id, "minute-confirmations"),
        "trades": count_endpoint(run_id, "trades"),
        "signals": count_endpoint(run_id, "signals"),
        "positions": count_endpoint(run_id, "positions"),
        "orders": count_endpoint(run_id, "orders"),
        "trade_snapshots": count_endpoint(run_id, "trade-snapshots"),
    }

    issues: list[str] = []
    if run.get("status") != "completed":
        issues.append(f"状态不是 completed: {run.get('status')} / {run.get('error_message')}")
    if strategy_type == "selection":
        if not bool(summary.get("selection_only_mode") or diagnostics.get("selection_only_mode")):
            issues.append("选股策略未标记 selection_only_mode")
        if endpoint_counts["trades"] not in {0, -1}:
            issues.append(f"选股策略不应默认产生成交，当前 trades={endpoint_counts['trades']}")
        if endpoint_counts["orders"] not in {0, -1}:
            issues.append(f"选股策略不应默认产生订单，当前 orders={endpoint_counts['orders']}")
        if endpoint_counts["watchlists"] <= 0:
            issues.append("选股策略未产出候选池 watchlists")
    else:
        if bool(summary.get("selection_only_mode") or diagnostics.get("selection_only_mode")):
            issues.append("非选股策略被错误标记 selection_only_mode")
        if endpoint_counts["watchlists"] <= 0:
            issues.append("非选股策略未产出候选池 watchlists")
    if diagnostics.get("fallback_mode") is True:
        issues.append("当前走 fallback_mode，未使用真引擎")

    return CheckResult(
        name=strategy["name"],
        ok=not issues,
        detail="；".join(issues) if issues else "通过",
        payload={
            "strategy_id": strategy["id"],
            "strategy_type": strategy_type,
            "run_id": run_id,
            "status": run.get("status"),
            "engine_mode": summary.get("engine_mode"),
            "selection_only_mode": summary.get("selection_only_mode"),
            "watchlist_days": summary.get("watchlist_days"),
            "metrics": run.get("metrics"),
            "endpoint_counts": endpoint_counts,
            "diagnostics": {
                "fallback_mode": diagnostics.get("fallback_mode"),
                "minute_data_missing": diagnostics.get("minute_data_missing"),
                "confirm_hit_rate": diagnostics.get("confirm_hit_rate"),
                "minute_load_count": diagnostics.get("minute_load_count"),
            },
        },
    )


def verify_universe_params(strategy: dict[str, Any]) -> list[CheckResult]:
    scenarios = [
        ("股票池=全部", {"scope": "all"}),
        ("股票池=主板", {"scope": "main_board"}),
        ("股票池=创业板", {"scope": "chinext"}),
        ("股票池=指定个股", {"scope": "symbols", "symbols": ["000001.SZ", "600000.SH"]}),
        ("股票池=指定板块", {"scope": "sector", "sector": "算力"}),
    ]
    results: list[CheckResult] = []
    for label, universe in scenarios:
        try:
            created = request_json("POST", "/v1/backtests", backtest_payload(strategy, universe=universe))
            completed = wait_backtest(created["id"])
            summary = ((completed.get("result") or {}).get("summary") or {})
            diagnostics = ((completed.get("result") or {}).get("diagnostics") or {})
            ok = completed.get("status") == "completed" and bool(summary.get("selection_only_mode"))
            detail = "通过" if ok else f"失败: {completed.get('status')} {completed.get('error_message')}"
            results.append(CheckResult(
                name=f"{strategy['name']} · {label}",
                ok=ok,
                detail=detail,
                payload={
                    "run_id": completed.get("id"),
                    "status": completed.get("status"),
                    "watchlist_days": summary.get("watchlist_days"),
                    "symbol_count": summary.get("symbol_count"),
                    "universe_filter": diagnostics.get("universe_filter"),
                },
            ))
        except Exception as exc:
            results.append(CheckResult(name=f"{strategy['name']} · {label}", ok=False, detail=str(exc)))
    return results


def main() -> int:
    all_results: list[CheckResult] = []
    strategies_response = request_json("GET", "/v1/strategies")
    strategies = strategies_response.get("strategies") or []
    print(f"发现策略数量: {len(strategies)}")

    for strategy in strategies:
        compile_response = request_json("POST", f"/v1/strategies/{strategy['id']}/compile")
        compile_ok = compile_response.get("status") == "passed"
        all_results.append(CheckResult(
            name=f"{strategy['name']} · DSL 编译",
            ok=compile_ok,
            detail="通过" if compile_ok else json.dumps(compile_response, ensure_ascii=False),
            payload={"strategy_id": strategy["id"], "strategy_type": strategy.get("strategy_type")},
        ))
        if not compile_ok:
            continue
        try:
            created = request_json("POST", "/v1/backtests", backtest_payload(strategy))
            completed = wait_backtest(created["id"])
            all_results.append(verify_run(strategy, completed))
            print(f"完成: {strategy['name']} -> {completed.get('status')} ({completed.get('id')})")
        except Exception as exc:
            all_results.append(CheckResult(
                name=f"{strategy['name']} · 回测流程",
                ok=False,
                detail=str(exc),
                payload={"strategy_id": strategy["id"], "strategy_type": strategy.get("strategy_type")},
            ))
            print(f"失败: {strategy['name']} -> {exc}")

    first_selection = next((item for item in strategies if item.get("strategy_type") == "selection"), None)
    if first_selection:
        print(f"开始股票池参数验收: {first_selection['name']}")
        all_results.extend(verify_universe_params(first_selection))

    output = {
        "base_url": BASE_URL,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "total_checks": len(all_results),
        "passed": sum(1 for item in all_results if item.ok),
        "failed": sum(1 for item in all_results if not item.ok),
        "results": [
            {"name": item.name, "ok": item.ok, "detail": item.detail, "payload": item.payload}
            for item in all_results
        ],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
