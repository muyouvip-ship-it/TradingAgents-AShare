"""
数据源健壮性模块 - P0优化
提供重试、降级、熔断机制
"""

import asyncio
import time
from typing import Any, Callable, Dict, List, Optional
from functools import wraps
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class CircuitBreaker:
    """熔断器 - 防止持续调用失败的provider"""
    failure_threshold: int = 5
    recovery_timeout: int = 60  # 秒
    
    failures: int = 0
    last_failure_time: Optional[datetime] = None
    state: str = "closed"  # closed, open, half-open
    
    def record_failure(self):
        """记录失败"""
        self.failures += 1
        self.last_failure_time = datetime.now()
        
        if self.failures >= self.failure_threshold:
            self.state = "open"
            logger.warning(f"熔断器打开，{self.failure_threshold}次连续失败")
    
    def record_success(self):
        """记录成功"""
        self.failures = 0
        self.state = "closed"
    
    def is_available(self) -> bool:
        """检查是否可用"""
        if self.state == "closed":
            return True
        
        if self.state == "open":
            # 检查是否可以进入半开状态
            if self.last_failure_time:
                elapsed = (datetime.now() - self.last_failure_time).total_seconds()
                if elapsed >= self.recovery_timeout:
                    self.state = "half-open"
                    logger.info("熔断器进入半开状态，尝试恢复")
                    return True
            return False
        
        # half-open状态允许一次尝试
        return True


@dataclass
class RetryConfig:
    """重试配置"""
    max_attempts: int = 3
    wait_min: float = 1.0  # 秒
    wait_max: float = 10.0
    wait_multiplier: float = 2.0
    retryable_exceptions: tuple = (
        ConnectionError,
        TimeoutError,
        asyncio.TimeoutError,
    )


class DataProviderHealth:
    """数据源健康状态跟踪"""
    
    def __init__(self):
        self.health: Dict[str, Dict[str, Any]] = {}
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
    
    def get_breaker(self, provider: str) -> CircuitBreaker:
        """获取provider的熔断器"""
        if provider not in self.circuit_breakers:
            self.circuit_breakers[provider] = CircuitBreaker()
        return self.circuit_breakers[provider]
    
    def record_success(self, provider: str, method: str, latency: float):
        """记录成功调用"""
        if provider not in self.health:
            self.health[provider] = {
                "total_calls": 0,
                "success_calls": 0,
                "failed_calls": 0,
                "avg_latency": 0.0,
                "last_success": None,
            }
        
        health = self.health[provider]
        health["total_calls"] += 1
        health["success_calls"] += 1
        health["avg_latency"] = (
            health["avg_latency"] * (health["success_calls"] - 1) + latency
        ) / health["success_calls"]
        health["last_success"] = datetime.now()
        
        self.get_breaker(provider).record_success()
    
    def record_failure(self, provider: str, method: str, error: Exception):
        """记录失败调用"""
        if provider not in self.health:
            self.health[provider] = {
                "total_calls": 0,
                "success_calls": 0,
                "failed_calls": 0,
                "errors": [],
                "last_failure": None,
            }
        
        health = self.health[provider]
        health["total_calls"] += 1
        health["failed_calls"] += 1
        health["last_failure"] = datetime.now()
        
        # 保留最近10个错误
        if "errors" not in health:
            health["errors"] = []
        health["errors"].append({
            "time": datetime.now().isoformat(),
            "method": method,
            "error": str(error),
        })
        if len(health["errors"]) > 10:
            health["errors"] = health["errors"][-10:]
        
        self.get_breaker(provider).record_failure()
    
    def get_stats(self) -> Dict[str, Any]:
        """获取健康统计"""
        return {
            provider: {
                **data,
                "circuit_breaker_state": self.get_breaker(provider).state,
            }
            for provider, data in self.health.items()
        }


# 全局健康跟踪器
health_tracker = DataProviderHealth()


def with_retry(
    max_attempts: int = 3,
    wait_min: float = 1.0,
    wait_max: float = 10.0,
    wait_multiplier: float = 2.0,
    retryable_exceptions: tuple = None,
):
    """
    重试装饰器
    
    使用示例:
        @with_retry(max_attempts=3)
        async def fetch_data():
            return await some_api_call()
    """
    if retryable_exceptions is None:
        retryable_exceptions = (ConnectionError, TimeoutError, asyncio.TimeoutError)
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_exc = None
            wait_time = wait_min
            
            for attempt in range(1, max_attempts + 1):
                try:
                    start_time = time.time()
                    result = await func(*args, **kwargs)
                    latency = time.time() - start_time
                    
                    # 记录成功
                    provider = kwargs.get("_provider", "unknown")
                    method = func.__name__
                    health_tracker.record_success(provider, method, latency)
                    
                    return result
                    
                except retryable_exceptions as e:
                    last_exc = e
                    logger.warning(
                        f"尝试 {attempt}/{max_attempts} 失败: {func.__name__} - {e}"
                    )
                    
                    if attempt < max_attempts:
                        await asyncio.sleep(wait_time)
                        wait_time = min(wait_time * wait_multiplier, wait_max)
                    
                    # 记录失败
                    provider = kwargs.get("_provider", "unknown")
                    health_tracker.record_failure(provider, func.__name__, e)
                except Exception as e:
                    # 非重试异常，直接抛出
                    provider = kwargs.get("_provider", "unknown")
                    health_tracker.record_failure(provider, func.__name__, e)
                    raise
            
            raise RuntimeError(
                f"重试{max_attempts}次后仍失败: {func.__name__}"
            ) from last_exc
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            last_exc = None
            wait_time = wait_min
            
            for attempt in range(1, max_attempts + 1):
                try:
                    start_time = time.time()
                    result = func(*args, **kwargs)
                    latency = time.time() - start_time
                    
                    provider = kwargs.get("_provider", "unknown")
                    health_tracker.record_success(provider, func.__name__, latency)
                    
                    return result
                    
                except retryable_exceptions as e:
                    last_exc = e
                    logger.warning(
                        f"尝试 {attempt}/{max_attempts} 失败: {func.__name__} - {e}"
                    )
                    
                    if attempt < max_attempts:
                        time.sleep(wait_time)
                        wait_time = min(wait_time * wait_multiplier, wait_max)
                    
                    provider = kwargs.get("_provider", "unknown")
                    health_tracker.record_failure(provider, func.__name__, e)
                except Exception as e:
                    provider = kwargs.get("_provider", "unknown")
                    health_tracker.record_failure(provider, func.__name__, e)
                    raise
            
            raise RuntimeError(
                f"重试{max_attempts}次后仍失败: {func.__name__}"
            ) from last_exc
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


class FallbackChain:
    """
    降级链 - 支持多数据源降级
    
    使用示例:
        chain = FallbackChain(["akshare", "baostock", "yfinance"])
        data = await chain.execute("get_stock_data", symbol="600519")
    """
    
    def __init__(
        self,
        providers: List[str],
        health: DataProviderHealth = None,
    ):
        self.providers = providers
        self.health = health or health_tracker
    
    async def execute(
        self,
        method: str,
        registry,
        *args,
        **kwargs,
    ) -> Any:
        """
        按优先级尝试provider，直到成功
        
        Args:
            method: 方法名（如 "get_stock_data"）
            registry: DataProviderRegistry实例
            *args, **kwargs: 传递给方法的参数
        
        Returns:
            方法执行结果
        
        Raises:
            RuntimeError: 所有provider都失败
        """
        last_exc = None
        
        for provider_name in self.providers:
            # 检查熔断器
            breaker = self.health.get_breaker(provider_name)
            if not breaker.is_available():
                logger.info(f"Provider {provider_name} 熔断中，跳过")
                continue
            
            provider = registry.get(provider_name)
            if provider is None:
                logger.warning(f"Provider {provider_name} 未注册")
                continue
            
            impl_func = getattr(provider, method, None)
            if impl_func is None:
                logger.debug(f"Provider {provider_name} 不支持方法 {method}")
                continue
            
            try:
                start_time = time.time()
                kwargs["_provider"] = provider_name
                
                # 支持async和sync
                if asyncio.iscoroutinefunction(impl_func):
                    result = await impl_func(*args, **kwargs)
                else:
                    result = impl_func(*args, **kwargs)
                
                latency = time.time() - start_time
                self.health.record_success(provider_name, method, latency)
                
                logger.info(f"Provider {provider_name} 执行 {method} 成功 ({latency:.2f}s)")
                return result
                
            except Exception as e:
                latency = time.time() - start_time
                self.health.record_failure(provider_name, method, e)
                last_exc = e
                logger.warning(
                    f"Provider {provider_name} 执行 {method} 失败: {e}"
                )
                continue
        
        raise RuntimeError(
            f"所有provider都失败。尝试顺序: {self.providers}。"
            f"最后错误: {last_exc}"
        ) from last_exc


def get_provider_status() -> Dict[str, Any]:
    """获取所有provider的状态"""
    return health_tracker.get_stats()


# 便捷函数
def create_resilient_interface(
    registry,
    provider_chain: List[str] = None,
):
    """
    创建健壮的数据接口
    
    Args:
        registry: DataProviderRegistry实例
        provider_chain: provider优先级列表
    
    Returns:
        健壮的接口对象
    """
    if provider_chain is None:
        provider_chain = ["cn_akshare", "cn_baostock", "yfinance"]
    
    chain = FallbackChain(provider_chain)
    
    class ResilientInterface:
        async def __getattr__(self, method: str):
            """动态方法调用"""
            async def wrapper(*args, **kwargs):
                return await chain.execute(method, registry, *args, **kwargs)
            return wrapper
    
    return ResilientInterface()
