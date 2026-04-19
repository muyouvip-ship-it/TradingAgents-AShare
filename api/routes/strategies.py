"""
策略管理API路由

提供策略管理相关的REST API。
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.services.strategy_service import StrategyService


# Pydantic 模型定义
class StrategyResponse(BaseModel):
    """策略响应模型"""
    strategy_id: str
    name: str
    strategy_type: str
    description: str
    parameters: dict
    is_active: bool
    created_at: str
    last_run_time: Optional[str] = None
    run_count: int


class StrategyListResponse(BaseModel):
    """策略列表响应"""
    total: int
    strategies: List[StrategyResponse]


class StrategyUpdateRequest(BaseModel):
    """策略更新请求"""
    parameters: dict = Field(default_factory=dict)


class StrategyToggleRequest(BaseModel):
    """策略激活/停用请求"""
    strategy_id: str


class StrategyStatisticsResponse(BaseModel):
    """策略统计响应"""
    total_strategies: int
    active_strategies: int
    by_type: dict
    timestamp: str


class StrategyPerformanceResponse(BaseModel):
    """策略性能响应"""
    strategy_id: str
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    last_run_time: Optional[str] = None
    run_count: int


class OperationResponse(BaseModel):
    """操作响应"""
    success: bool
    strategy_id: str
    message: str
    timestamp: str


# 创建路由器
router = APIRouter(prefix="/v1/strategies", tags=["strategies"])

# 服务实例
service = StrategyService()


@router.get("", response_model=StrategyListResponse)
async def list_strategies(
    strategy_type: Optional[str] = Query(None, description="策略类型过滤"),
    active_only: bool = Query(False, description="只返回活跃策略"),
):
    """
    获取策略列表

    - **strategy_type**: 策略类型过滤（selection/trading/risk/portfolio）
    - **active_only**: 是否只返回活跃策略
    """
    strategies = service.list_strategies(
        strategy_type=strategy_type,
        active_only=active_only,
    )

    return StrategyListResponse(
        total=len(strategies),
        strategies=[StrategyResponse(**s) for s in strategies],
    )


@router.get("/statistics", response_model=StrategyStatisticsResponse)
async def get_statistics():
    """
    获取策略统计信息

    返回：
    - 总策略数
    - 活跃策略数
    - 各类型策略数量
    """
    stats = service.get_strategy_statistics()
    return StrategyStatisticsResponse(**stats)


@router.get("/{strategy_id}", response_model=StrategyResponse)
async def get_strategy(strategy_id: str):
    """
    获取策略详情

    - **strategy_id**: 策略ID
    """
    strategy = service.get_strategy(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    return StrategyResponse(**strategy)


@router.patch("/{strategy_id}/parameters", response_model=OperationResponse)
async def update_parameters(
    strategy_id: str,
    request: StrategyUpdateRequest,
):
    """
    更新策略参数

    - **strategy_id**: 策略ID
    - **parameters**: 新参数字典
    """
    result = service.update_strategy_parameters(strategy_id, request.parameters)

    if not result['success']:
        raise HTTPException(status_code=400, detail=result['message'])

    return OperationResponse(**result)


@router.post("/{strategy_id}/activate", response_model=OperationResponse)
async def activate_strategy(strategy_id: str):
    """
    激活策略

    - **strategy_id**: 策略ID
    """
    result = service.activate_strategy(strategy_id)

    if not result['success']:
        raise HTTPException(status_code=404, detail=result['message'])

    return OperationResponse(**result)


@router.post("/{strategy_id}/deactivate", response_model=OperationResponse)
async def deactivate_strategy(strategy_id: str):
    """
    停用策略

    - **strategy_id**: 策略ID
    """
    result = service.deactivate_strategy(strategy_id)

    if not result['success']:
        raise HTTPException(status_code=404, detail=result['message'])

    return OperationResponse(**result)


@router.get("/{strategy_id}/performance", response_model=StrategyPerformanceResponse)
async def get_performance(strategy_id: str):
    """
    获取策略性能数据

    - **strategy_id**: 策略ID
    """
    performance = service.get_strategy_performance(strategy_id)

    if not performance:
        raise HTTPException(status_code=404, detail="Strategy not found")

    return StrategyPerformanceResponse(**performance)
