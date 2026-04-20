from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pandas as pd


def sse_pack(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def parse_stock_csv(raw: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            rows.append({"symbol": parts[0], "name": parts[1], "value": parts[2]})
    return rows


def normalize_kline_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    return out
