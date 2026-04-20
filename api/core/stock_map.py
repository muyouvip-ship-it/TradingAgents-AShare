from __future__ import annotations

from threading import Lock
from typing import Dict, Optional

from api.core.logging import logger

_cn_stock_map: Optional[Dict[str, str]] = None
_cn_stock_reverse_map: Optional[Dict[str, str]] = None
_cn_stock_map_lock = Lock()
_cn_stock_map_loaded_at: float = 0
_STOCK_MAP_TTL = 7 * 86400


def load_cn_stock_map() -> Dict[str, str]:
    global _cn_stock_map, _cn_stock_reverse_map, _cn_stock_map_loaded_at
    import time as _time

    now = _time.time()
    if _cn_stock_map is not None and (now - _cn_stock_map_loaded_at) > _STOCK_MAP_TTL:
        _cn_stock_map = None
        _cn_stock_reverse_map = None
    if _cn_stock_map is not None:
        return _cn_stock_map
    with _cn_stock_map_lock:
        if _cn_stock_map is not None and (now - _cn_stock_map_loaded_at) <= _STOCK_MAP_TTL:
            return _cn_stock_map
        result: Dict[str, str] = {}
        try:
            import akshare as ak
            from api.core.stock_utils import normalize_symbol

            df = ak.stock_info_a_code_name()
            for _, row in df.iterrows():
                name = str(row.get("name", "")).strip()
                code = str(row.get("code", "")).strip()
                if name and code:
                    result[name] = normalize_symbol(code)
            stock_count = len(result)
            fund_count = 0
            try:
                fund_df = ak.fund_name_em()
                existing_codes = set(result.values())
                for _, row in fund_df.iterrows():
                    code = str(row.get("基金代码", "")).strip()
                    name = str(row.get("基金简称", "")).strip()
                    if name and code and len(code) == 6 and code.isdigit():
                        normalized = normalize_symbol(code)
                        if normalized not in existing_codes:
                            result[name] = normalized
                            existing_codes.add(normalized)
                fund_count = len(result) - stock_count
            except Exception as fe:
                logger.info(f"[StockMap] ETF/fund load skipped: {fe}")
            _cn_stock_map = result
            _cn_stock_reverse_map = {code: name for name, code in result.items()}
            _cn_stock_map_loaded_at = now
            logger.info(f"[StockMap] Loaded {stock_count} stocks + {fund_count} ETFs/funds = {len(result)} total.")
        except Exception as e:
            logger.info(f"[StockMap] Failed to load: {e}")
            if _cn_stock_map is None:
                _cn_stock_map = {}
                _cn_stock_reverse_map = {}
    return _cn_stock_map
+
+
def get_reverse_stock_map() -> Dict[str, str]:
    load_cn_stock_map()
    return dict(_cn_stock_reverse_map or {})
+
+
def get_reverse_stock_map_cached_only() -> Dict[str, str]:
    if _cn_stock_map is None or _cn_stock_reverse_map is None:
        return {}
    return dict(_cn_stock_reverse_map)
