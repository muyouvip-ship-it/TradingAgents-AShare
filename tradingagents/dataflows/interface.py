import os
import asyncio
import time
from typing import Any

from .alpha_vantage_common import AlphaVantageRateLimitError
from .config import get_config
from .providers import build_default_registry
from .resilience import (
    FallbackChain,
    health_tracker,
    logger,
)

# Tools organized by category
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": ["get_stock_data"],
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": ["get_indicators"],
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement",
        ],
    },
    "news_data": {
        "description": "News and insider data",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ],
    },
    "realtime_data": {
        "description": "Real-time market quotes",
        "tools": ["get_realtime_quotes"],
    },
    "cn_market_data": {
        "description": "China A-share market sentiment and fund flow data",
        "tools": [
            "get_board_fund_flow",
            "get_individual_fund_flow",
            "get_lhb_detail",
            "get_zt_pool",
            "get_hot_stocks_xq",
        ],
    },
}

_registry = build_default_registry()

VENDOR_LIST = _registry.list_names()


def _is_trace_enabled() -> bool:
    env_value = os.getenv("TA_TRACE")
    if env_value is not None:
        return env_value.strip().lower() in ("1", "true", "yes", "on")

    config = get_config()
    return bool(config.get("provider_trace", True))


def _trace(msg: str) -> None:
    if _is_trace_enabled():
        print(f"[provider-trace] {msg}", flush=True)


def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")


def get_vendor(category: str, method: str = None) -> str:
    """Get configured vendor for category or tool method."""
    config = get_config()

    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    return config.get("data_vendors", {}).get(category, "yfinance")


def _resolve_vendor_chain(method: str, configured_vendor: str) -> list[str]:
    configured = [v.strip() for v in configured_vendor.split(",") if v.strip()]
    fallback = configured.copy()

    for provider_name in _registry.list_names():
        if provider_name not in fallback:
            fallback.append(provider_name)

    return fallback


def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to provider implementations with fallback support.
    
    优化版本：
    - 支持重试机制
    - 支持熔断器
    - 支持健康检查
    - 支持异步provider
    """
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    fallback_vendors = _resolve_vendor_chain(method, vendor_config)
    last_exc = None
    _trace(
        f"method={method} category={category} configured='{vendor_config}' "
        f"chain={fallback_vendors}"
    )

    for vendor in fallback_vendors:
        # 检查熔断器
        breaker = health_tracker.get_breaker(vendor)
        if not breaker.is_available():
            _trace(f"method={method} vendor={vendor} status=skip reason=circuit-breaker-open")
            logger.info(f"Provider {vendor} 熔断中，跳过")
            continue
        
        provider = _registry.get(vendor)
        if provider is None:
            _trace(f"method={method} vendor={vendor} status=skip reason=not-registered")
            continue

        impl_func = getattr(provider, method, None)
        if impl_func is None:
            _trace(f"method={method} vendor={vendor} status=skip reason=not-implemented")
            continue

        try:
            start_time = time.time()
            
            # 支持异步和同步provider
            if asyncio.iscoroutinefunction(impl_func):
                result = asyncio.run(impl_func(*args, **kwargs))
            else:
                result = impl_func(*args, **kwargs)
            
            latency = time.time() - start_time
            health_tracker.record_success(vendor, method, latency)
            
            _trace(f"method={method} vendor={vendor} status=hit latency={latency:.2f}s")
            logger.info(f"Provider {vendor} 执行 {method} 成功 ({latency:.2f}s)")
            return result
            
        except (AlphaVantageRateLimitError, NotImplementedError) as exc:
            last_exc = exc
            health_tracker.record_failure(vendor, method, exc)
            _trace(
                f"method={method} vendor={vendor} status=fallback "
                f"reason={type(exc).__name__}"
            )
            logger.warning(f"Provider {vendor} 执行 {method} 失败: {exc}")
            continue
            
        except Exception as exc:
            last_exc = exc
            health_tracker.record_failure(vendor, method, exc)
            _trace(
                f"method={method} vendor={vendor} status=fallback "
                f"reason={type(exc).__name__}"
            )
            logger.warning(f"Provider {vendor} 执行 {method} 失败: {exc}")
            continue

    _trace(f"method={method} status=failed reason=no-available-vendor")
    
    # 生成详细的错误报告
    health_status = health_tracker.get_stats()
    available_vendors = [
        v for v in fallback_vendors 
        if health_tracker.get_breaker(v).is_available()
    ]
    
    error_msg = (
        f"所有数据源均失败。\n"
        f"请求方法: {method}\n"
        f"尝试顺序: {fallback_vendors}\n"
        f"可用源: {available_vendors}\n"
        f"健康状态: {health_status}\n"
        f"最后错误: {type(last_exc).__name__}: {last_exc}"
    )
    
    if last_exc is not None:
        raise RuntimeError(error_msg) from last_exc
    raise RuntimeError(error_msg)


def get_data_source_health() -> dict:
    """获取数据源健康状态（新增API）"""
    return health_tracker.get_stats()


def reset_circuit_breaker(provider: str):
    """重置指定provider的熔断器（新增API）"""
    breaker = health_tracker.get_breaker(provider)
    breaker.failures = 0
    breaker.state = "closed"
    logger.info(f"已重置 {provider} 的熔断器")
