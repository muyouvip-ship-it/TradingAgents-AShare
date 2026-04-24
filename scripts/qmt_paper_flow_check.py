from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.core.env import load_project_env


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def _get_json(url: str, *, token: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(url, headers=_headers(token), params=params or {}, timeout=20)
    response.raise_for_status()
    return response.json()


def _post_json(url: str, *, token: str, payload: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.post(url, headers=_headers(token), json=payload, params=params or {}, timeout=20)
    response.raise_for_status()
    return response.json()


def _print_step(title: str, payload: dict[str, Any]) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _assert_safe_paper_channel(base_url: str, account_key: str, account_id: str) -> None:
    if account_key != "paper_sim":
        raise SystemExit("拒绝执行：联调脚本只允许 account_key=paper_sim")
    if ":8711" in base_url:
        raise SystemExit("拒绝执行：8711 是实盘 bridge 端口，虚拟仓联调必须使用 8710")
    if account_id != "39027628":
        raise SystemExit("拒绝执行：联调脚本默认只允许模拟账号 39027628")


def main() -> int:
    load_project_env()
    parser = argparse.ArgumentParser(description="QMT 虚拟仓全流程联调脚本。默认只读；显式开启后才提交模拟委托并撤单。")
    parser.add_argument("--base-url", default=os.getenv("QMT_HISTORY_BRIDGE_BASE_URL") or os.getenv("QMT_BRIDGE_BASE_URL") or "http://192.168.10.1:8710")
    parser.add_argument("--token", default=os.getenv("QMT_HISTORY_BRIDGE_TOKEN") or os.getenv("QMT_BRIDGE_TOKEN") or "your-bridge-token")
    parser.add_argument("--account-key", default=os.getenv("QMT_HISTORY_ACCOUNT_KEY") or "paper_sim")
    parser.add_argument("--account-id", default="39027628")
    parser.add_argument("--account-type", default="STOCK")
    parser.add_argument("--symbol", default="002105.SZ")
    parser.add_argument("--quantity", type=int, default=100)
    parser.add_argument("--price", type=float, default=0.01, help="默认使用极低限价验证委托/撤单链路，避免模拟仓成交。")
    parser.add_argument("--submit-cancel-test", action="store_true", help="提交一笔模拟限价委托并尝试撤单；默认不下单。")
    args = parser.parse_args()

    base_url = str(args.base_url).rstrip("/")
    _assert_safe_paper_channel(base_url, args.account_key, args.account_id)

    health = _get_json(f"{base_url}/health", token=args.token)
    _print_step("1. bridge 健康检查", health)

    snapshot_params = {
        "account_id": args.account_id,
        "account_type": args.account_type,
        "account_key": args.account_key,
    }
    snapshot = _get_json(f"{base_url}/snapshot", token=args.token, params=snapshot_params)
    _print_step(
        "2. 资产 / 持仓 / 委托 / 成交快照",
        {
            "asset": snapshot.get("asset") or {},
            "positions": len(snapshot.get("positions") or []),
            "orders": len(snapshot.get("orders") or []),
            "trades": len(snapshot.get("trades") or []),
            "bridge": snapshot.get("bridge") or {},
        },
    )

    if not args.submit_cancel_test:
        print("\n默认只读检查完成。若要验证模拟委托和撤单，追加 --submit-cancel-test。")
        return 0

    order_payload = {
        "account_id": args.account_id,
        "account_type": args.account_type,
        "account_key": args.account_key,
        "symbol": args.symbol,
        "side": "buy",
        "quantity": args.quantity,
        "price": args.price,
        "price_type": "limit",
        "strategy_name": "QmtPaperFlowCheck",
        "order_remark": "paper_sim_submit_cancel_test",
    }
    order_result = _post_json(f"{base_url}/orders", token=args.token, payload=order_payload)
    _print_step("3. 提交模拟委托", order_result)

    order_id = str(order_result.get("order_id") or "")
    time.sleep(2)
    after_submit = _get_json(f"{base_url}/snapshot", token=args.token, params=snapshot_params)
    _print_step(
        "4. 提交后刷新",
        {
            "orders": len(after_submit.get("orders") or []),
            "trades": len(after_submit.get("trades") or []),
            "latest_orders": (after_submit.get("orders") or [])[:5],
            "bridge": after_submit.get("bridge") or {},
        },
    )

    if order_id and order_id not in {"0", "-1", "None"}:
        cancel_result = _post_json(
            f"{base_url}/orders/{order_id}/cancel",
            token=args.token,
            params=snapshot_params,
        )
        _print_step("5. 撤单", cancel_result)
        time.sleep(2)
        after_cancel = _get_json(f"{base_url}/snapshot", token=args.token, params=snapshot_params)
        _print_step(
            "6. 撤单后刷新 / 成交确认",
            {
                "orders": len(after_cancel.get("orders") or []),
                "trades": len(after_cancel.get("trades") or []),
                "latest_orders": (after_cancel.get("orders") or [])[:5],
                "latest_trades": (after_cancel.get("trades") or [])[:5],
                "bridge": after_cancel.get("bridge") or {},
            },
        )
    else:
        print("\n委托未返回有效 order_id，跳过撤单。请查看上方 QMT 返回结果。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
