"""
策略管理API路由（完整版）

提供策略管理相关的REST API。
包含完整的CRUD操作。
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
import logging

# 导入数据库模型和服务
from api.models.strategy_models import (
    StrategyDB,
    BacktestJobDB,
    BacktestResultDB,
    TradeRecordDB,
    FactorDB,
    StrategyType,
    StrategyStatus,
)
from sqlalchemy.orm import Session

from api.core.strategy_db import get_strategy_db

logger = logging.getLogger(__name__)

# ============ Pydantic 模型定义 ============

class IndicatorConfig(BaseModel):
    """指标配置"""
    name: str
    display_name: str
    parameters: dict = Field(default_factory=dict)


class RuleConfig(BaseModel):
    """规则配置"""
    name: str
    condition: str
    parameters: dict = Field(default_factory=dict)


class PositionRule(BaseModel):
    """仓位规则"""
    initial: float = Field(default=0.3, ge=0, le=1)
    max_position: float = Field(default=0.8, ge=0, le=1)
    add_on_profit: Optional[float] = None
    reduce_on_loss: Optional[float] = None
    max_single_position: float = Field(default=0.3, ge=0, le=1)


class RiskRule(BaseModel):
    """风控规则"""
    stop_loss: float = Field(default=0.05, ge=0, le=1)
    take_profit: Optional[float] = None
    trailing_stop: Optional[float] = None
    max_positions: int = Field(default=10, ge=1)
    max_daily_loss: float = Field(default=0.03, ge=0, le=1)


class StrategyCreateRequest(BaseModel):
    """创建策略请求"""
    name: str = Field(..., min_length=1, max_length=200)
    strategy_type: str = Field(..., pattern="^(selection|trading|risk|portfolio)$")
    parent_id: Optional[str] = None
    description: Optional[str] = None

    # 策略配置
    indicators: List[IndicatorConfig] = Field(default_factory=list)
    entry_rules: List[RuleConfig] = Field(default_factory=list)
    exit_rules: List[RuleConfig] = Field(default_factory=list)
    position_rules: Optional[PositionRule] = None
    risk_rules: Optional[RiskRule] = None
    parameters: dict = Field(default_factory=dict)


class StrategyUpdateRequest(BaseModel):
    """更新策略请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    indicators: Optional[List[IndicatorConfig]] = None
    entry_rules: Optional[List[RuleConfig]] = None
    exit_rules: Optional[List[RuleConfig]] = None
    position_rules: Optional[PositionRule] = None
    risk_rules: Optional[RiskRule] = None
    parameters: Optional[dict] = None


class StrategyResponse(BaseModel):
    """策略响应"""
    id: str
    name: str
    strategy_type: str
    parent_id: Optional[str]
    description: Optional[str]
    indicators: Optional[List[dict]]
    entry_rules: Optional[List[dict]]
    exit_rules: Optional[List[dict]]
    position_rules: Optional[dict]
    risk_rules: Optional[dict]
    parameters: Optional[dict]
    status: str
    version: int
    is_active: bool
    run_count: int
    last_run_time: Optional[str]
    created_at: str
    updated_at: str
    performance: Optional[dict]

    model_config = ConfigDict(from_attributes=True)


class StrategyListResponse(BaseModel):
    """策略列表响应"""
    total: int
    strategies: List[StrategyResponse]


# ============ API 路由 ============

router = APIRouter(prefix="/api/v1/strategies", tags=["Strategies"])


@router.post("", response_model=StrategyResponse, summary="创建策略")
async def create_strategy(request: StrategyCreateRequest, db: Session = Depends(get_strategy_db)):
    """
    创建新策略

    - **name**: 策略名称
    - **strategy_type**: 策略类型 (selection, trading, risk, portfolio)
    - **indicators**: 指标配置列表
    - **entry_rules**: 入场规则列表
    - **exit_rules**: 出场规则列表
    - **position_rules**: 仓位规则
    - **risk_rules**: 风控规则
    """
    try:
        # 创建策略实例
        db_strategy = StrategyDB(
            name=request.name,
            strategy_type=StrategyType(request.strategy_type),
            parent_id=request.parent_id,
            description=request.description,
            indicators=[i.dict() for i in request.indicators],
            entry_rules=[r.dict() for r in request.entry_rules],
            exit_rules=[r.dict() for r in request.exit_rules],
            position_rules=request.position_rules.dict() if request.position_rules else None,
            risk_rules=request.risk_rules.dict() if request.risk_rules else None,
            parameters=request.parameters,
            status=StrategyStatus.DRAFT,
        )

        db.add(db_strategy)
        db.commit()
        db.refresh(db_strategy)

        logger.info(f"Created strategy: {db_strategy.id} - {db_strategy.name}")

        return StrategyResponse(**db_strategy.to_dict())

    except Exception as e:
        db.rollback()
        logger.error(f"Error creating strategy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=StrategyListResponse, summary="获取策略列表")
async def list_strategies(
    strategy_type: Optional[str] = Query(None, pattern="^(selection|trading|risk|portfolio)$"),
    status: Optional[str] = Query(None, pattern="^(draft|active|paused|archived)$"),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None, max_length=100),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_strategy_db),
):
    """
    获取策略列表

    - **strategy_type**: 策略类型过滤
    - **status**: 状态过滤
    - **is_active**: 是否激活过滤
    - **search**: 搜索关键词（名称、描述）
    - **skip**: 分页偏移
    - **limit**: 分页大小
    """
    try:
        query = db.query(StrategyDB)

        # 过滤条件
        if strategy_type:
            query = query.filter(StrategyDB.strategy_type == StrategyType(strategy_type))

        if status:
            query = query.filter(StrategyDB.status == StrategyStatus(status))

        if is_active is not None:
            query = query.filter(StrategyDB.is_active == is_active)

        if search:
            query = query.filter(
                (StrategyDB.name.contains(search)) |
                (StrategyDB.description.contains(search))
            )

        # 排序
        query = query.order_by(StrategyDB.updated_at.desc())

        # 总数
        total = query.count()

        # 分页
        strategies = query.offset(skip).limit(limit).all()

        return StrategyListResponse(
            total=total,
            strategies=[StrategyResponse(**s.to_dict()) for s in strategies],
        )

    except Exception as e:
        logger.error(f"Error listing strategies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{strategy_id}", response_model=StrategyResponse, summary="获取策略详情")
async def get_strategy(strategy_id: str, db: Session = Depends(get_strategy_db)):
    """获取单个策略的详细信息"""
    try:
        strategy = db.query(StrategyDB).filter(StrategyDB.id == strategy_id).first()

        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")

        return StrategyResponse(**strategy.to_dict())

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting strategy {strategy_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{strategy_id}", response_model=StrategyResponse, summary="更新策略")
async def update_strategy(
    strategy_id: str,
    request: StrategyUpdateRequest,
    db: Session = Depends(get_strategy_db),
):
    """
    更新策略信息

    只更新请求中提供的字段
    """
    try:
        strategy = db.query(StrategyDB).filter(StrategyDB.id == strategy_id).first()

        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")

        # 更新字段
        update_data = request.dict(exclude_unset=True)

        for field, value in update_data.items():
            if field in ["indicators", "entry_rules", "exit_rules"]:
                # 转换为字典列表
                value = [v.dict() if hasattr(v, "dict") else v for v in value]
            elif field in ["position_rules", "risk_rules"]:
                # 转换为字典
                value = value.dict() if hasattr(value, "dict") else value

            setattr(strategy, field, value)

        # 增加版本号
        strategy.version += 1
        strategy.updated_at = datetime.now()

        db.commit()
        db.refresh(strategy)

        logger.info(f"Updated strategy: {strategy_id}")

        return StrategyResponse(**strategy.to_dict())

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating strategy {strategy_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{strategy_id}", summary="删除策略")
async def delete_strategy(strategy_id: str, db: Session = Depends(get_strategy_db)):
    """删除策略"""
    try:
        strategy = db.query(StrategyDB).filter(StrategyDB.id == strategy_id).first()

        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")

        children = db.query(StrategyDB).filter(StrategyDB.parent_id == strategy_id).count()
        if children > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete strategy with {children} child strategies"
            )

        job_count = db.query(BacktestJobDB).filter(BacktestJobDB.strategy_id == strategy_id).count()
        if job_count > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete strategy with {job_count} backtest jobs; archive it instead"
            )

        trade_count = db.query(TradeRecordDB).filter(TradeRecordDB.strategy_id == strategy_id).count()
        if trade_count > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete strategy with {trade_count} trade records; archive it instead"
            )

        db.delete(strategy)
        db.commit()

        logger.info(f"Deleted strategy: {strategy_id}")

        return {"success": True, "message": "Strategy deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting strategy {strategy_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{strategy_id}/activate", summary="激活策略")
async def activate_strategy(strategy_id: str, db: Session = Depends(get_strategy_db)):
    """激活策略（开始运行）"""
    try:
        strategy = db.query(StrategyDB).filter(StrategyDB.id == strategy_id).first()

        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")

        strategy.is_active = True
        strategy.status = StrategyStatus.ACTIVE
        strategy.updated_at = datetime.now()

        db.commit()
        db.refresh(strategy)

        logger.info(f"Activated strategy: {strategy_id}")

        return {
            "success": True,
            "strategy_id": strategy_id,
            "status": strategy.status.value,
            "message": "Strategy activated successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error activating strategy {strategy_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{strategy_id}/deactivate", summary="停用策略")
async def deactivate_strategy(strategy_id: str, db: Session = Depends(get_strategy_db)):
    """停用策略（暂停运行）"""
    try:
        strategy = db.query(StrategyDB).filter(StrategyDB.id == strategy_id).first()

        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")

        strategy.is_active = False
        strategy.status = StrategyStatus.PAUSED
        strategy.updated_at = datetime.now()

        db.commit()
        db.refresh(strategy)

        logger.info(f"Deactivated strategy: {strategy_id}")

        return {
            "success": True,
            "strategy_id": strategy_id,
            "status": strategy.status.value,
            "message": "Strategy deactivated successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deactivating strategy {strategy_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{strategy_id}/clone", response_model=StrategyResponse, summary="克隆策略")
async def clone_strategy(strategy_id: str, db: Session = Depends(get_strategy_db)):
    """克隆策略（创建副本）"""
    try:
        original = db.query(StrategyDB).filter(StrategyDB.id == strategy_id).first()

        if not original:
            raise HTTPException(status_code=404, detail="Strategy not found")

        # 创建副本
        clone = StrategyDB(
            name=f"{original.name} (副本)",
            strategy_type=original.strategy_type,
            parent_id=original.parent_id,
            description=original.description,
            indicators=original.indicators,
            entry_rules=original.entry_rules,
            exit_rules=original.exit_rules,
            position_rules=original.position_rules,
            risk_rules=original.risk_rules,
            parameters=original.parameters,
            status=StrategyStatus.DRAFT,
        )

        db.add(clone)
        db.commit()
        db.refresh(clone)

        logger.info(f"Cloned strategy: {strategy_id} -> {clone.id}")

        return StrategyResponse(**clone.to_dict())

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error cloning strategy {strategy_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{strategy_id}/performance", summary="获取策略绩效")
async def get_strategy_performance(strategy_id: str, db: Session = Depends(get_strategy_db)):
    """获取策略绩效数据"""
    try:
        strategy = db.query(StrategyDB).filter(StrategyDB.id == strategy_id).first()

        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")

        latest_job = db.query(BacktestJobDB).filter(
            BacktestJobDB.strategy_id == strategy_id,
            BacktestJobDB.status == 'completed'
        ).order_by(BacktestJobDB.completed_at.desc()).first()

        if latest_job and latest_job.result:
            metrics = latest_job.result.get('metrics', {})
            performance = {
                "strategy_id": strategy_id,
                "run_count": strategy.run_count,
                "last_run_time": strategy.last_run_time.isoformat() if strategy.last_run_time else None,
                "latest_job_id": latest_job.id,
                "metrics": metrics,
            }
        else:
            performance = {
                "strategy_id": strategy_id,
                "run_count": strategy.run_count,
                "last_run_time": strategy.last_run_time.isoformat() if strategy.last_run_time else None,
                "latest_job_id": None,
                "metrics": {
                    "total_return": strategy.total_return,
                    "sharpe_ratio": strategy.sharpe_ratio,
                    "max_drawdown": strategy.max_drawdown,
                    "win_rate": strategy.win_rate,
                },
            }

        return performance

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting strategy performance {strategy_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============ 统计接口 ============

@router.get("/stats/summary", summary="获取策略统计概览")
async def get_strategy_stats(db: Session = Depends(get_strategy_db)):
    """获取策略统计概览"""
    try:
        total = db.query(StrategyDB).count()
        active = db.query(StrategyDB).filter(StrategyDB.is_active == True).count()

        # 按类型统计
        type_stats = {}
        for stype in StrategyType:
            count = db.query(StrategyDB).filter(StrategyDB.strategy_type == stype).count()
            type_stats[stype.value] = {
                "total": count,
                "active": db.query(StrategyDB).filter(
                    StrategyDB.strategy_type == stype,
                    StrategyDB.is_active == True
                ).count(),
            }

        return {
            "total_strategies": total,
            "active_strategies": active,
            "by_type": type_stats,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"Error getting strategy stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
