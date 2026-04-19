"""
策略执行API路由

提供策略执行、优化、风险分析相关的REST API。
"""

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from datetime import datetime
import logging
import asyncio

from tradingagents.strategies.executor import get_executor
from tradingagents.strategies.optimizer import get_optimizer
from tradingagents.strategies.risk_analyzer import get_risk_analyzer

logger = logging.getLogger(__name__)


# Pydantic 模型定义
class ScheduleStrategyRequest(BaseModel):
    """调度策略请求"""
    strategy_id: str
    schedule_type: str = Field("daily", description="调度类型: daily, hourly, custom")
    schedule_time: str = Field("09:30", description="执行时间 (HH:MM)")
    symbols: List[str] = Field(..., description="股票代码列表")


class GridSearchRequest(BaseModel):
    """网格搜索请求"""
    strategy_id: str
    symbol: str
    start_date: str
    end_date: str
    param_grid: Dict[str, List[Any]] = Field(..., description="参数网格")
    initial_capital: float = 1000000.0
    metric: str = Field("total_return", description="优化指标")
    top_n: int = Field(10, description="返回前N个结果")


class CompareStrategiesRequest(BaseModel):
    """策略对比请求"""
    strategy_ids: List[str]
    symbol: str
    start_date: str
    end_date: str
    initial_capital: float = 1000000.0


class MultiStrategyPortfolioRequest(BaseModel):
    """多策略组合请求"""
    strategy_weights: Dict[str, float] = Field(..., description="策略权重映射")
    symbol: str
    start_date: str
    end_date: str
    initial_capital: float = 1000000.0


class RiskAnalysisRequest(BaseModel):
    """风险分析请求"""
    portfolio_values: List[Dict[str, Any]]
    confidence_level: float = 0.95


# 创建路由器
router = APIRouter(prefix="/v1/strategy", tags=["strategy"])


# ============================================================
# 策略执行相关API
# ============================================================

@router.post("/schedule")
async def schedule_strategy(request: ScheduleStrategyRequest):
    """
    调度策略执行
    
    设置定时任务，自动运行策略并生成信号。
    """
    try:
        executor = get_executor()
        
        # 启动执行器（如果未启动）
        if not executor.scheduler.running:
            await executor.start()
        
        job_id = executor.schedule_strategy(
            strategy_id=request.strategy_id,
            schedule_type=request.schedule_type,
            schedule_time=request.schedule_time,
            symbols=request.symbols,
        )
        
        return {
            "status": "success",
            "job_id": job_id,
            "message": f"Strategy {request.strategy_id} scheduled successfully",
        }
        
    except Exception as e:
        logger.error(f"Failed to schedule strategy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/schedule/{job_id}")
async def unschedule_strategy(job_id: str):
    """
    取消策略调度
    """
    try:
        executor = get_executor()
        executor.unschedule_strategy(job_id)
        
        return {
            "status": "success",
            "message": f"Job {job_id} unscheduled successfully",
        }
        
    except Exception as e:
        logger.error(f"Failed to unschedule strategy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/schedule/active")
async def get_active_schedules():
    """
    获取活跃的调度任务
    """
    try:
        executor = get_executor()
        jobs = executor.get_active_jobs()
        
        return {
            "status": "success",
            "active_jobs": jobs,
            "total_jobs": sum(len(j) for j in jobs.values()),
        }
        
    except Exception as e:
        logger.error(f"Failed to get active schedules: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signals/{strategy_id}")
async def get_signal_history(strategy_id: str, limit: int = 100):
    """
    获取策略信号历史
    """
    try:
        executor = get_executor()
        signals = executor.get_signal_history(strategy_id)[-limit:]
        
        return {
            "status": "success",
            "strategy_id": strategy_id,
            "signals": [
                {
                    "symbol": s.symbol,
                    "type": s.signal_type.value,
                    "price": s.price,
                    "timestamp": str(s.timestamp),
                    "confidence": s.confidence,
                    "metadata": s.metadata,
                }
                for s in signals
            ],
            "total": len(signals),
        }
        
    except Exception as e:
        logger.error(f"Failed to get signal history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 策略优化相关API
# ============================================================

@router.post("/optimize/grid-search")
async def grid_search(request: GridSearchRequest):
    """
    参数网格搜索
    
    测试所有参数组合，找出最优参数。
    """
    try:
        optimizer = get_optimizer()
        
        results = optimizer.grid_search(
            strategy_id=request.strategy_id,
            symbol=request.symbol,
            start_date=request.start_date,
            end_date=request.end_date,
            param_grid=request.param_grid,
            initial_capital=request.initial_capital,
            metric=request.metric,
            top_n=request.top_n,
        )
        
        return {
            "status": "success",
            "total_combinations": len(results),
            "top_results": results,
        }
        
    except Exception as e:
        logger.error(f"Grid search failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/optimize/compare")
async def compare_strategies(request: CompareStrategiesRequest):
    """
    策略对比分析
    
    对比多个策略的表现。
    """
    try:
        optimizer = get_optimizer()
        
        comparison_df = optimizer.compare_strategies(
            strategy_ids=request.strategy_ids,
            symbol=request.symbol,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
        )
        
        return {
            "status": "success",
            "comparison": comparison_df.to_dict('records'),
        }
        
    except Exception as e:
        logger.error(f"Strategy comparison failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/optimize/portfolio")
async def multi_strategy_portfolio(request: MultiStrategyPortfolioRequest):
    """
    多策略组合回测
    
    测试多个策略的组合效果。
    """
    try:
        optimizer = get_optimizer()
        
        result = optimizer.multi_strategy_portfolio(
            strategy_weights=request.strategy_weights,
            symbol=request.symbol,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
        )
        
        return {
            "status": "success",
            "result": result,
        }
        
    except Exception as e:
        logger.error(f"Multi-strategy portfolio failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 风险分析相关API
# ============================================================

@router.post("/risk/var")
async def calculate_var(request: RiskAnalysisRequest):
    """
    计算VaR（风险价值）
    """
    try:
        import pandas as pd
        
        analyzer = get_risk_analyzer()
        
        # 转换为DataFrame
        df = pd.DataFrame(request.portfolio_values)
        returns = df['value'].pct_change().dropna()
        
        # 计算VaR
        var_result = analyzer.calculate_var(
            returns=returns,
            confidence_level=request.confidence_level,
        )
        
        return {
            "status": "success",
            "var": var_result,
        }
        
    except Exception as e:
        logger.error(f"VaR calculation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/risk/stress-test")
async def stress_test(request: RiskAnalysisRequest):
    """
    压力测试
    """
    try:
        import pandas as pd
        
        analyzer = get_risk_analyzer()
        
        # 转换为DataFrame
        df = pd.DataFrame(request.portfolio_values)
        
        # 执行压力测试
        stress_result = analyzer.stress_test(df)
        
        return {
            "status": "success",
            "stress_test": stress_result,
        }
        
    except Exception as e:
        logger.error(f"Stress test failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/risk/monte-carlo")
async def monte_carlo_simulation(request: RiskAnalysisRequest):
    """
    蒙特卡洛模拟
    """
    try:
        import pandas as pd
        
        analyzer = get_risk_analyzer()
        
        # 转换为DataFrame
        df = pd.DataFrame(request.portfolio_values)
        returns = df['value'].pct_change().dropna()
        
        # 执行蒙特卡洛模拟
        mc_result = analyzer.monte_carlo_simulation(
            returns=returns,
            initial_value=df['value'].iloc[0],
        )
        
        return {
            "status": "success",
            "monte_carlo": mc_result,
        }
        
    except Exception as e:
        logger.error(f"Monte Carlo simulation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/risk/analyze")
async def full_risk_analysis(request: RiskAnalysisRequest):
    """
    完整风险分析
    
    包括VaR、CVaR、压力测试、蒙特卡洛模拟等。
    """
    try:
        import pandas as pd
        
        analyzer = get_risk_analyzer()
        
        # 转换为DataFrame
        df = pd.DataFrame(request.portfolio_values)
        
        # 完整风险分析
        risk_metrics = analyzer.calculate_risk_metrics(df)
        
        return {
            "status": "success",
            "risk_metrics": risk_metrics,
        }
        
    except Exception as e:
        logger.error(f"Risk analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
