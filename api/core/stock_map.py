from __future__ import annotations

import json
import time
from threading import Lock
from pathlib import Path
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
_cn_stock_map_version: int = 0
_STOCK_MAP_TTL = 7 * 86400
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_STOCK_MAP_CACHE_PATH = _PROJECT_ROOT / "data" / "cn_stock_map.json"


def load_cn_stock_map(force_refresh: bool = False) -> Dict[str, str]:
    global _cn_stock_map, _cn_stock_reverse_map, _cn_stock_map_loaded_at, _cn_stock_map_version
    with _cn_stock_map_lock:
        if _cn_stock_map is None:
            cached_map, cached_at = _load_stock_map_cache()
            if cached_map:
                _cn_stock_map = cached_map
                _cn_stock_reverse_map = {code: name for name, code in cached_map.items()}
                _cn_stock_map_loaded_at = cached_at
                _cn_stock_map_version += 1
                logger.info("Stock map loaded from local cache symbols: %s", len(cached_map))
            else:
                _cn_stock_map = dict(_FALLBACK_STOCK_MAP)
                _cn_stock_reverse_map = {code: name for name, code in _cn_stock_map.items()}
                _cn_stock_map_loaded_at = 0
                _cn_stock_map_version += 1
                logger.info("Stock map initialized from fallback symbols: %s", len(_cn_stock_map))
        if force_refresh:
            refreshed_map = _fetch_stock_map_from_akshare()
            if refreshed_map:
                _cn_stock_map = refreshed_map
                _cn_stock_reverse_map = {code: name for name, code in refreshed_map.items()}
                _cn_stock_map_loaded_at = time.time()
                _cn_stock_map_version += 1
                _write_stock_map_cache(refreshed_map, _cn_stock_map_loaded_at)
                logger.info("Stock map refreshed from akshare symbols: %s", len(refreshed_map))
    return dict(_cn_stock_map)


def get_reverse_stock_map() -> Dict[str, str]:
    load_cn_stock_map()
    return dict(_cn_stock_reverse_map or {})


def get_stock_map_version() -> int:
    load_cn_stock_map()
    return _cn_stock_map_version


def get_reverse_stock_map_cached_only() -> Dict[str, str]:
    if _cn_stock_map is None or _cn_stock_reverse_map is None:
        return {}
    return dict(_cn_stock_reverse_map)


def stock_map_cache_age_seconds() -> float | None:
    if _cn_stock_map_loaded_at <= 0:
        return None
    return max(0.0, time.time() - _cn_stock_map_loaded_at)


def stock_map_cache_is_stale() -> bool:
    age = stock_map_cache_age_seconds()
    return age is None or age >= _STOCK_MAP_TTL


def refresh_cn_stock_map_if_stale() -> Dict[str, str]:
    if stock_map_cache_is_stale():
        return load_cn_stock_map(force_refresh=True)
    return load_cn_stock_map()


def _fetch_stock_map_from_akshare() -> Dict[str, str]:
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
        return stock_map
    except Exception as exc:
        logger.warning("Stock map akshare refresh failed, keeping cached/fallback data: %s", exc)
        return {}


def _load_stock_map_cache() -> tuple[Dict[str, str], float]:
    try:
        if not _STOCK_MAP_CACHE_PATH.exists():
            return {}, 0
        payload = json.loads(_STOCK_MAP_CACHE_PATH.read_text(encoding="utf-8"))
        data = payload.get("data") if isinstance(payload, dict) else None
        loaded_at = float(payload.get("loaded_at") or 0) if isinstance(payload, dict) else 0
        if not isinstance(data, dict):
            return {}, 0
        normalized = {
            str(name).strip(): str(symbol).strip().upper()
            for name, symbol in data.items()
            if str(name).strip() and str(symbol).strip()
        }
        return normalized, loaded_at
    except Exception as exc:
        logger.warning("Stock map cache load failed: %s", exc)
        return {}, 0


def _write_stock_map_cache(stock_map: Dict[str, str], loaded_at: float) -> None:
    try:
        _STOCK_MAP_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "loaded_at": loaded_at,
            "count": len(stock_map),
            "data": stock_map,
        }
        _STOCK_MAP_CACHE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Stock map cache write failed: %s", exc)
