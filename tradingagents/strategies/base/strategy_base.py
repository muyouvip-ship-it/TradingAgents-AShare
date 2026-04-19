"""
策略基类模块

定义所有策略的通用接口和基础功能。
所有具体策略（选股、交易、风控、组合）都继承自此类。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import pandas as pd


class StrategyType(str, Enum):
    """策略类型枚举"""
    SELECTION = "selection"  # 选股策略
    TRADING = "trading"      # 交易策略
    RISK = "risk"            # 风控策略
    PORTFOLIO = "portfolio"  # 组合策略


class SignalType(str, Enum):
    """信号类型"""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    ADJUST = "adjust"


class SignalStrength(str, Enum):
    """信号强度"""
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"


@dataclass
class Signal:
    """交易信号"""
    type: SignalType
    strength: SignalStrength
    confidence: float  # 0.0 - 1.0
    reason: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': self.type.value,
            'strength': self.strength.value,
            'confidence': self.confidence,
            'reason': self.reason,
            'timestamp': self.timestamp.isoformat(),
            'metadata': self.metadata,
        }


@dataclass
class StrategyResult:
    """策略执行结果"""
    strategy_id: str
    strategy_name: str
    strategy_type: StrategyType
    signals: List[Signal]
    performance_metrics: Dict[str, float]
    execution_time: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'strategy_id': self.strategy_id,
            'strategy_name': self.strategy_name,
            'strategy_type': self.strategy_type.value,
            'signals': [s.to_dict() for s in self.signals],
            'performance_metrics': self.performance_metrics,
            'execution_time': self.execution_time.isoformat(),
            'metadata': self.metadata,
        }


class StrategyBase(ABC):
    """
    策略基类

    所有具体策略的父类，定义统一接口。
    支持参数化配置、回测、信号生成等功能。
    """

    def __init__(
        self,
        strategy_id: str,
        name: str,
        strategy_type: StrategyType,
        description: str = "",
        parameters: Optional[Dict[str, Any]] = None,
    ):
        self.strategy_id = strategy_id
        self.name = name
        self.strategy_type = strategy_type
        self.description = description
        self.parameters = parameters or {}
        self.is_active = False
        self.created_at = datetime.now()
        self.last_run_time: Optional[datetime] = None
        self.run_count = 0

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame, **kwargs) -> List[Signal]:
        """
        生成交易信号（核心方法）

        Args:
            data: 输入数据（股票价格、财务数据等）
            **kwargs: 额外参数

        Returns:
            交易信号列表
        """
        pass

    @abstractmethod
    def validate_parameters(self) -> bool:
        """
        验证策略参数是否有效

        Returns:
            参数是否有效
        """
        pass

    def update_parameters(self, new_params: Dict[str, Any]) -> bool:
        """
        更新策略参数

        Args:
            new_params: 新参数字典

        Returns:
            是否更新成功
        """
        old_params = self.parameters.copy()
        self.parameters.update(new_params)

        if not self.validate_parameters():
            self.parameters = old_params
            return False

        return True

    def execute(self, data: pd.DataFrame, **kwargs) -> StrategyResult:
        """
        执行策略

        Args:
            data: 输入数据
            **kwargs: 额外参数

        Returns:
            策略执行结果
        """
        start_time = datetime.now()

        # 生成信号
        signals = self.generate_signals(data, **kwargs)

        # 计算性能指标（如果有历史数据）
        performance_metrics = self._calculate_performance_metrics(signals)

        # 更新统计
        self.last_run_time = start_time
        self.run_count += 1

        return StrategyResult(
            strategy_id=self.strategy_id,
            strategy_name=self.name,
            strategy_type=self.strategy_type,
            signals=signals,
            performance_metrics=performance_metrics,
            metadata={'parameters': self.parameters}
        )

    def _calculate_performance_metrics(self, signals: List[Signal]) -> Dict[str, float]:
        """
        计算性能指标

        Args:
            signals: 信号列表

        Returns:
            性能指标字典
        """
        # 默认返回基础指标，具体策略可以重写此方法
        buy_signals = [s for s in signals if s.type == SignalType.BUY]
        sell_signals = [s for s in signals if s.type == SignalType.SELL]

        return {
            'total_signals': len(signals),
            'buy_signals': len(buy_signals),
            'sell_signals': len(sell_signals),
            'avg_confidence': sum(s.confidence for s in signals) / len(signals) if signals else 0.0,
        }

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'strategy_id': self.strategy_id,
            'name': self.name,
            'strategy_type': self.strategy_type.value,
            'description': self.description,
            'parameters': self.parameters,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat(),
            'last_run_time': self.last_run_time.isoformat() if self.last_run_time else None,
            'run_count': self.run_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StrategyBase':
        """从字典创建策略实例"""
        # 子类需要重写此方法
        raise NotImplementedError("Subclasses must implement from_dict method")

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(id={self.strategy_id}, name={self.name}, type={self.strategy_type.value})>"
