"""
策略管理器

管理所有策略的注册、执行、监控。
"""

from typing import Any, Dict, List, Optional, Type
from datetime import datetime
import pandas as pd
import logging

from tradingagents.strategies.base.strategy_base import (
    StrategyBase,
    StrategyType,
    StrategyResult,
)
from tradingagents.strategies.selection.value_investing import ValueInvestingStrategy
from tradingagents.strategies.selection.growth_investing import GrowthInvestingStrategy
from tradingagents.strategies.trading.ma_cross import MACrossStrategy
from tradingagents.strategies.trading.macd import MACDStrategy
from tradingagents.strategies.trading.rsi import RSIStrategy
from tradingagents.strategies.trading.bollinger_bands import BollingerBandsStrategy
from tradingagents.strategies.trading.turtle_trading import TurtleTradingStrategy

logger = logging.getLogger(__name__)


class StrategyManager:
    """
    策略管理器

    功能：
    - 注册和管理策略
    - 执行策略并返回结果
    - 监控策略状态
    - 策略持久化（保存/加载）
    """

    def __init__(self):
        self._strategies: Dict[str, StrategyBase] = {}
        self._results_history: List[StrategyResult] = []
        self._strategy_classes: Dict[str, Type[StrategyBase]] = {}

        # 注册内置策略类
        self._register_builtin_strategies()

    def _register_builtin_strategies(self):
        """注册内置策略"""
        self.register_strategy_class('value_investing', ValueInvestingStrategy)
        self.register_strategy_class('growth_investing', GrowthInvestingStrategy)
        self.register_strategy_class('ma_cross', MACrossStrategy)
        self.register_strategy_class('macd', MACDStrategy)
        self.register_strategy_class('rsi', RSIStrategy)
        self.register_strategy_class('bollinger_bands', BollingerBandsStrategy)
        self.register_strategy_class('turtle_trading', TurtleTradingStrategy)

        # 注册默认策略实例
        self.register_strategy(ValueInvestingStrategy())
        self.register_strategy(GrowthInvestingStrategy())
        self.register_strategy(MACrossStrategy())
        self.register_strategy(MACDStrategy())
        self.register_strategy(RSIStrategy())
        self.register_strategy(BollingerBandsStrategy())
        self.register_strategy(TurtleTradingStrategy())

    def register_strategy_class(self, strategy_type: str, strategy_class: Type[StrategyBase]):
        """
        注册策略类

        Args:
            strategy_type: 策略类型标识
            strategy_class: 策略类
        """
        self._strategy_classes[strategy_type] = strategy_class
        logger.info(f"Registered strategy class: {strategy_type}")

    def register_strategy(self, strategy: StrategyBase):
        """
        注册策略实例

        Args:
            strategy: 策略实例
        """
        self._strategies[strategy.strategy_id] = strategy
        logger.info(f"Registered strategy: {strategy.strategy_id} ({strategy.name})")

    def get_strategy(self, strategy_id: str) -> Optional[StrategyBase]:
        """
        获取策略

        Args:
            strategy_id: 策略ID

        Returns:
            策略实例，如果不存在返回None
        """
        return self._strategies.get(strategy_id)

    def list_strategies(
        self,
        strategy_type: Optional[StrategyType] = None,
        active_only: bool = False,
    ) -> List[StrategyBase]:
        """
        列出策略

        Args:
            strategy_type: 策略类型过滤（可选）
            active_only: 是否只返回活跃策略

        Returns:
            策略列表
        """
        strategies = list(self._strategies.values())

        if strategy_type:
            strategies = [s for s in strategies if s.strategy_type == strategy_type]

        if active_only:
            strategies = [s for s in strategies if s.is_active]

        return strategies

    def execute_strategy(
        self,
        strategy_id: str,
        data: pd.DataFrame,
        **kwargs
    ) -> Optional[StrategyResult]:
        """
        执行策略

        Args:
            strategy_id: 策略ID
            data: 输入数据
            **kwargs: 额外参数

        Returns:
            策略执行结果，如果策略不存在返回None
        """
        strategy = self.get_strategy(strategy_id)
        if not strategy:
            logger.error(f"Strategy not found: {strategy_id}")
            return None

        try:
            result = strategy.execute(data, **kwargs)
            self._results_history.append(result)
            logger.info(f"Executed strategy {strategy_id}, generated {len(result.signals)} signals")
            return result
        except Exception as e:
            logger.error(f"Error executing strategy {strategy_id}: {e}")
            return None

    def update_strategy_parameters(
        self,
        strategy_id: str,
        parameters: Dict[str, Any],
    ) -> bool:
        """
        更新策略参数

        Args:
            strategy_id: 策略ID
            parameters: 新参数

        Returns:
            是否更新成功
        """
        strategy = self.get_strategy(strategy_id)
        if not strategy:
            logger.error(f"Strategy not found: {strategy_id}")
            return False

        success = strategy.update_parameters(parameters)
        if success:
            logger.info(f"Updated parameters for strategy {strategy_id}")
        else:
            logger.warning(f"Failed to update parameters for strategy {strategy_id}")

        return success

    def activate_strategy(self, strategy_id: str) -> bool:
        """激活策略"""
        strategy = self.get_strategy(strategy_id)
        if not strategy:
            return False
        strategy.is_active = True
        logger.info(f"Activated strategy {strategy_id}")
        return True

    def deactivate_strategy(self, strategy_id: str) -> bool:
        """停用策略"""
        strategy = self.get_strategy(strategy_id)
        if not strategy:
            return False
        strategy.is_active = False
        logger.info(f"Deactivated strategy {strategy_id}")
        return True

    def get_strategy_status(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        """
        获取策略状态

        Args:
            strategy_id: 策略ID

        Returns:
            策略状态字典
        """
        strategy = self.get_strategy(strategy_id)
        if not strategy:
            return None

        return {
            'strategy_id': strategy.strategy_id,
            'name': strategy.name,
            'type': strategy.strategy_type.value,
            'is_active': strategy.is_active,
            'last_run_time': strategy.last_run_time.isoformat() if strategy.last_run_time else None,
            'run_count': strategy.run_count,
            'parameters': strategy.parameters,
        }

    def get_all_strategies_status(self) -> List[Dict[str, Any]]:
        """获取所有策略状态"""
        return [self.get_strategy_status(sid) for sid in self._strategies.keys()]

    def create_strategy_from_config(
        self,
        strategy_type: str,
        strategy_id: str,
        name: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Optional[StrategyBase]:
        """
        从配置创建策略实例

        Args:
            strategy_type: 策略类型
            strategy_id: 策略ID
            name: 策略名称
            parameters: 策略参数

        Returns:
            策略实例，如果类型不存在返回None
        """
        strategy_class = self._strategy_classes.get(strategy_type)
        if not strategy_class:
            logger.error(f"Strategy type not found: {strategy_type}")
            return None

        try:
            strategy = strategy_class(
                strategy_id=strategy_id,
                name=name,
                parameters=parameters,
            )
            self.register_strategy(strategy)
            return strategy
        except Exception as e:
            logger.error(f"Error creating strategy: {e}")
            return None

    def get_results_history(
        self,
        strategy_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[StrategyResult]:
        """
        获取执行历史

        Args:
            strategy_id: 策略ID过滤（可选）
            limit: 返回数量限制

        Returns:
            执行结果列表
        """
        results = self._results_history

        if strategy_id:
            results = [r for r in results if r.strategy_id == strategy_id]

        return results[-limit:]

    def to_dict(self) -> Dict[str, Any]:
        """导出管理器状态"""
        return {
            'strategies': {sid: s.to_dict() for sid, s in self._strategies.items()},
            'results_count': len(self._results_history),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StrategyManager':
        """从字典创建管理器实例"""
        manager = cls()
        # 恢复策略状态
        for sid, sdata in data.get('strategies', {}).items():
            if sid in manager._strategies:
                # 更新已存在策略的状态
                strategy = manager._strategies[sid]
                strategy.parameters = sdata.get('parameters', {})
                strategy.is_active = sdata.get('is_active', False)
                strategy.run_count = sdata.get('run_count', 0)

        return manager


# 全局单例
_strategy_manager_instance: Optional[StrategyManager] = None


def get_strategy_manager() -> StrategyManager:
    """获取策略管理器单例"""
    global _strategy_manager_instance
    if _strategy_manager_instance is None:
        _strategy_manager_instance = StrategyManager()
    return _strategy_manager_instance
