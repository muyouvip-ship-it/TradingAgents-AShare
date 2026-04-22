from __future__ import annotations

from threading import Lock
from typing import Dict, Optional

from api.core.logging import logger

_FALLBACK_STOCK_MAP: Dict[str, str] = {
    "贵州茅台": "600519.SH",
    "宁德时代": "300750.SZ",
    "平安银行": "000001.SZ",
}
_cn_stock_map: Optional[Dict[str, str]] = None
_cn_stock_reverse_map: Optional[Dict[str, str]] = None
_cn_stock_map_lock = Lock()
_cn_stock_map_loaded_at: float = 0
_STOCK_MAP_TTL = 7 * 86400


def load_cn_stock_map() -> Dict[str, str]:
    global _cn_stock_map, _cn_stock_reverse_map, _cn_stock_map_loaded_at
    with _cn_stock_map_lock:
        if _cn_stock_map is None:
            stock_map = dict(_FALLBACK_STOCK_MAP)
            try:
                import akshare as ak

                frame = ak.stock_info_a_code_name()
                if frame is not None and not frame.empty:
                    for _, row in frame.iterrows():
                        name = str(row.get("name") or "").strip()
                        code = str(row.get("code") or "").strip()
                        if not name or len(code) != 6 or not code.isdigit():
                            continue
                        if code.startswith("6"):
                            symbol = f"{code}.SH"
                        elif code.startswith(("0", "3")):
                            symbol = f"{code}.SZ"
                        elif code.startswith(("4", "8")):
                            symbol = f"{code}.BJ"
                        else:
                            continue
                        stock_map[name] = symbol
                logger.info("Stock map loaded from akshare symbols: %s", len(stock_map))
            except Exception as exc:
                logger.warning("Stock map akshare load failed, fallback only: %s", exc)
            _cn_stock_map = stock_map
            _cn_stock_reverse_map = {code: name for name, code in _cn_stock_map.items()}
            logger.info("Stock map initialized with fallback symbols: %s", len(_cn_stock_map))
    return dict(_cn_stock_map)


def get_reverse_stock_map() -> Dict[str, str]:
    load_cn_stock_map()
    return dict(_cn_stock_reverse_map or {})


def get_reverse_stock_map_cached_only() -> Dict[str, str]:
    if _cn_stock_map is None or _cn_stock_reverse_map is None:
        return {}
    return dict(_cn_stock_reverse_map)
