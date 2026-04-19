"""
策略管理服务

提供策略相关的API服务。
"""

from typing import Any, Dict, List, Optional
import logging
from datetime import datetime

from tradingagents.strategies.manager import get_strategy_manager, StrategyManager
from tradingagents.strategies.base.strategy_base import StrategyType

logger = logging.getLogger(__name__)


class StrategyService:
    """策略服务"""

    def __init__(self):
        self.manager = get_strategy_manager()

    def list_strategies(
        self,
        strategy_type: Optional[str] = None,
        active_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        获取策略列表

        Args:
            strategy_type: 策略类型过滤
            active_only: 是否只返回活跃策略

        Returns:
            策略列表
        """
        type_filter = None
        if strategy_type:
            try:
                type_filter = StrategyType(strategy_type)
            except ValueError:
                logger.warning(f"Invalid strategy type: {strategy_type}")

        strategies = self.manager.list_strategies(
            strategy_type=type_filter,
            active_only=active_only,
        )

        return [s.to_dict() for s in strategies]

    def get_strategy(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        """
        获取策略详情

        Args:
            strategy_id: 策略ID

        Returns:
            策略详情
        """
        strategy = self.manager.get_strategy(strategy_id)
        if not strategy:
            return None

        return strategy.to_dict()

    def update_strategy_parameters(
        self,
        strategy_id: str,
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        更新策略参数

        Args:
            strategy_id: 策略ID
            parameters: 新参数

        Returns:
            更新结果
        """
        success = self.manager.update_strategy_parameters(strategy_id, parameters)

        return {
            'success': success,
            'strategy_id': strategy_id,
            'message': 'Parameters updated successfully' if success else 'Failed to update parameters',
            'timestamp': datetime.now().isoformat(),
        }

    def activate_strategy(self, strategy_id: str) -> Dict[str, Any]:
        """
        激活策略

        Args:
            strategy_id: 策略ID

        Returns:
            操作结果
        """
        success = self.manager.activate_strategy(strategy_id)

        return {
            'success': success,
            'strategy_id': strategy_id,
            'is_active': True,
            'message': 'Strategy activated' if success else 'Failed to activate strategy',
            'timestamp': datetime.now().isoformat(),
        }

    def deactivate_strategy(self, strategy_id: str) -> Dict[str, Any]:
        """
        停用策略

        Args:
            strategy_id: 策略ID

        Returns:
            操作结果
        """
        success = self.manager.deactivate_strategy(strategy_id)

        return {
            'success': success,
            'strategy_id': strategy_id,
            'is_active': False,
            'message': 'Strategy deactivated' if success else 'Failed to deactivate strategy',
            'timestamp': datetime.now().isoformat(),
        }

    def get_strategy_statistics(self) -> Dict[str, Any]:
        """
        获取策略统计信息

        Returns:
            统计信息
        """
        all_strategies = self.manager.list_strategies()
        active_strategies = [s for s in all_strategies if s.is_active]

        # 按类型统计
        type_stats = {}
        for s in all_strategies:
            stype = s.strategy_type.value
            if stype not in type_stats:
                type_stats[stype] = {'total': 0, 'active': 0}
            type_stats[stype]['total'] += 1
            if s.is_active:
                type_stats[stype]['active'] += 1

        return {
            'total_strategies': len(all_strategies),
            'active_strategies': len(active_strategies),
            'by_type': type_stats,
            'timestamp': datetime.now().isoformat(),
        }

    def get_strategy_performance(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        """
        获取策略性能数据

        Args:
            strategy_id: 策略ID

        Returns:
            性能数据
        """
        strategy = self.manager.get_strategy(strategy_id)
        if not strategy:
            return None

        # 模拟性能数据（实际应从历史结果计算）
        return {
            'strategy_id': strategy_id,
            'total_return': 0.156,  # 模拟数据
            'sharpe_ratio': 1.82,
            'max_drawdown': -0.12,
            'win_rate': 0.65,
            'profit_factor': 1.85,
            'last_run_time': strategy.last_run_time.isoformat() if strategy.last_run_time else None,
            'run_count': strategy.run_count,
        }
