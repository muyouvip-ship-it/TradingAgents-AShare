"""
Prometheus监控 - P3优化
提供性能指标、错误追踪、业务指标
"""

import time
from typing import Dict, Any, Optional
from dataclasses import dataclass
from functools import wraps
import logging

logger = logging.getLogger(__name__)

# ━━━━ 检查Prometheus是否安装 ━━━━
try:
    from prometheus_client import (
        Counter,
        Histogram,
        Gauge,
        Info,
        CollectorRegistry,
        generate_latest,
        CONTENT_TYPE_LATEST,
        start_http_server,
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.warning(
        "prometheus_client未安装，监控指标将被禁用。"
        "运行: pip install prometheus_client"
    )


# ━━━━ 指标定义 ━━━━

if PROMETHEUS_AVAILABLE:
    # Agent执行指标
    agent_latency = Histogram(
        'trading_agent_latency_seconds',
        'Agent执行延迟',
        ['agent_name', 'agent_type'],
        buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
    )
    
    agent_errors = Counter(
        'trading_agent_errors_total',
        'Agent错误总数',
        ['agent_name', 'error_type'],
    )
    
    agent_invocations = Counter(
        'trading_agent_invocations_total',
        'Agent调用总数',
        ['agent_name'],
    )
    
    # 数据源指标
    data_source_latency = Histogram(
        'trading_data_source_latency_seconds',
        '数据源延迟',
        ['provider', 'method'],
        buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0],
    )
    
    data_source_errors = Counter(
        'trading_data_source_errors_total',
        '数据源错误总数',
        ['provider', 'method', 'error_type'],
    )
    
    # 辩论指标
    debate_rounds = Histogram(
        'trading_debate_rounds',
        '辩论轮次分布',
        buckets=[1, 2, 3, 4, 5, 6, 8, 10],
    )
    
    debate_consensus = Gauge(
        'trading_debate_consensus',
        '辩论共识度',
    )
    
    # 业务指标
    analysis_total = Counter(
        'trading_analysis_total',
        '分析请求总数',
        ['symbol', 'result'],  # result: success, error
    )
    
    decision_distribution = Counter(
        'trading_decision_distribution',
        '决策分布',
        ['decision'],  # BUY, SELL, HOLD
    )
    
    # 系统指标
    active_analyses = Gauge(
        'trading_active_analyses',
        '当前活跃分析数',
    )
    
    system_info = Info(
        'trading_system',
        '系统信息',
    )


# ━━━━ 装饰器 ━━━━

def track_agent_metrics(agent_name: str, agent_type: str = "analyst"):
    """
    Agent指标追踪装饰器
    
    使用示例:
        @track_agent_metrics("market_analyst", "analyst")
        async def market_analyst_node(state):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not PROMETHEUS_AVAILABLE:
                return await func(*args, **kwargs)
            
            start_time = time.time()
            agent_invocations.labels(agent_name=agent_name).inc()
            
            try:
                result = await func(*args, **kwargs)
                latency = time.time() - start_time
                agent_latency.labels(
                    agent_name=agent_name,
                    agent_type=agent_type,
                ).observe(latency)
                return result
                
            except Exception as e:
                agent_errors.labels(
                    agent_name=agent_name,
                    error_type=type(e).__name__,
                ).inc()
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not PROMETHEUS_AVAILABLE:
                return func(*args, **kwargs)
            
            start_time = time.time()
            agent_invocations.labels(agent_name=agent_name).inc()
            
            try:
                result = func(*args, **kwargs)
                latency = time.time() - start_time
                agent_latency.labels(
                    agent_name=agent_name,
                    agent_type=agent_type,
                ).observe(latency)
                return result
                
            except Exception as e:
                agent_errors.labels(
                    agent_name=agent_name,
                    error_type=type(e).__name__,
                ).inc()
                raise
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def track_data_source(provider: str, method: str):
    """
    数据源指标追踪装饰器
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not PROMETHEUS_AVAILABLE:
                return await func(*args, **kwargs)
            
            start_time = time.time()
            
            try:
                result = await func(*args, **kwargs)
                latency = time.time() - start_time
                data_source_latency.labels(
                    provider=provider,
                    method=method,
                ).observe(latency)
                return result
                
            except Exception as e:
                data_source_errors.labels(
                    provider=provider,
                    method=method,
                    error_type=type(e).__name__,
                ).inc()
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not PROMETHEUS_AVAILABLE:
                return func(*args, **kwargs)
            
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                latency = time.time() - start_time
                data_source_latency.labels(
                    provider=provider,
                    method=method,
                ).observe(latency)
                return result
                
            except Exception as e:
                data_source_errors.labels(
                    provider=provider,
                    method=method,
                    error_type=type(e).__name__,
                ).inc()
                raise
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


# ━━━━ 便捷函数 ━━━━

def record_debate_metrics(rounds: int, consensus: float):
    """记录辩论指标"""
    if not PROMETHEUS_AVAILABLE:
        return
    
    debate_rounds.observe(rounds)
    debate_consensus.set(consensus)


def record_analysis_result(symbol: str, success: bool):
    """记录分析结果"""
    if not PROMETHEUS_AVAILABLE:
        return
    
    result = "success" if success else "error"
    analysis_total.labels(symbol=symbol, result=result).inc()


def record_decision(decision: str):
    """记录决策"""
    if not PROMETHEUS_AVAILABLE:
        return
    
    decision_distribution.labels(decision=decision).inc()


def increment_active_analyses():
    """增加活跃分析数"""
    if PROMETHEUS_AVAILABLE:
        active_analyses.inc()


def decrement_active_analyses():
    """减少活跃分析数"""
    if PROMETHEUS_AVAILABLE:
        active_analyses.dec()


def set_system_info(version: str, provider: str):
    """设置系统信息"""
    if PROMETHEUS_AVAILABLE:
        system_info.info({
            'version': version,
            'llm_provider': provider,
        })


def start_metrics_server(port: int = 8001):
    """
    启动Prometheus指标服务器
    
    使用示例:
        start_metrics_server(8001)
        # 访问 http://localhost:8001/metrics
    """
    if not PROMETHEUS_AVAILABLE:
        logger.warning("Prometheus未安装，无法启动指标服务器")
        return
    
    start_http_server(port)
    logger.info(f"Prometheus指标服务器已启动: http://localhost:{port}/metrics")


def get_metrics() -> str:
    """获取Prometheus指标文本"""
    if not PROMETHEUS_AVAILABLE:
        return "# Prometheus未安装\n"
    
    return generate_latest().decode('utf-8')


# ━━━━ 集成到FastAPI ━━━━

def create_metrics_endpoint():
    """
    创建FastAPI metrics端点
    
    使用示例:
        from fastapi import FastAPI, Response
        from tradingagents.monitoring.metrics import create_metrics_endpoint
        
        app = FastAPI()
        
        @app.get("/metrics")
        async def metrics():
            return create_metrics_endpoint()
    """
    if not PROMETHEUS_AVAILABLE:
        from fastapi import Response
        return Response(
            content="# Prometheus未安装\n",
            media_type="text/plain",
        )
    
    from fastapi import Response
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
