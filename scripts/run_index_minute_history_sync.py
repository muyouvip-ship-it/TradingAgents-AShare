from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.core.env import load_project_env
from api.services.qmt_market_data_service import sync_index_minute_history


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="同步主要指数历史 1 分钟 K 线到 PostgreSQL index_minute_kline")
    parser.add_argument("--start-date", required=True, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--symbols", nargs="*", default=None, help="可选：指定指数代码列表")
    parser.add_argument("--data-source", default="qmt", choices=("qmt", "akshare"), help="分钟线数据源")
    return parser.parse_args()


def main() -> int:
    load_project_env()
    args = parse_args()
    started_at = datetime.now().isoformat()
    print(f"[index-minute-sync] started_at={started_at} start={args.start_date} end={args.end_date}", flush=True)

    def progress(progress_value: int, message: str) -> None:
        print(f"[index-minute-sync] progress={progress_value} message={message}", flush=True)

    payload = sync_index_minute_history(
        start_date=args.start_date,
        end_date=args.end_date,
        symbols=args.symbols,
        data_source=args.data_source,
        progress_callback=progress,
    )
    print(json.dumps(payload, ensure_ascii=False), flush=True)
    return 0 if payload.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
