from __future__ import annotations

import re
from typing import Dict, List, Optional

from api.core.stock_map import load_cn_stock_map


def normalize_symbol(raw: str) -> str:
    s = raw.strip().upper()
    m = re.search(r"(\d{6})(?:\.(SH|SZ|SS|BJ))?", s)
    if m:
        code = m.group(1)
        suffix = m.group(2)
        if suffix:
            if suffix == "SS":
                return f"{code}.SH"
            return f"{code}.{suffix}"
        if code.startswith(("4", "8")):
            market = "BJ"
        elif code.startswith(("5", "6", "9")):
            market = "SH"
        else:
            market = "SZ"
        return f"{code}.{market}"
    m2 = re.search(r"([A-Z]{1,6}(?:\.[A-Z]{1,3})?)", s)
    if m2:
        return m2.group(1)
    stock_map = load_cn_stock_map()
    if s in stock_map:
        return stock_map[s]
    return s


def search_cn_stock_by_name(query: str) -> Optional[str]:
    query = query.strip()
    if not query:
        return None
    stock_map = load_cn_stock_map()
    if query in stock_map:
        return stock_map[query]
    candidates = [(name, code) for name, code in stock_map.items() if query in name or name in query]
    if len(candidates) == 1:
        return candidates[0][1]
    if candidates:
        candidates.sort(key=lambda x: len(x[0]))
        return candidates[0][1]
    return None


def split_watchlist_batch_text(text: str) -> List[str]:
    return [token.strip() for token in re.split(r"[\s,，、；;]+", text.strip()) if token.strip()]


def resolve_watchlist_identifier(raw: str, name_to_code: Dict[str, str], code_to_name: Dict[str, str]):
    token = raw.strip()
    if not token:
        return None, None, "输入为空"
    if token in name_to_code:
        symbol = name_to_code[token]
        return symbol, code_to_name.get(symbol, token), None
    symbol = normalize_symbol(token)
    if symbol in code_to_name:
        return symbol, code_to_name.get(symbol, symbol), None
    return None, None, f"未识别的股票代码或名称: {token}"
