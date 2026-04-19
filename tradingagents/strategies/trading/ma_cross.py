"""
均线交叉策略

基于快慢均线交叉的趋势跟踪策略。
金叉买入，死叉卖出。
"""

from typing import Any, Dict, List, Optional
import pandas as pd
import numpy as np

from tradingagents.strategies.base.strategy_base import (
    StrategyBase,
    StrategyType,
    Signal,
    SignalType,
    SignalStrength,
)
from tradingagents.strategies.base.signal import create_buy_signal, create_sell_signal, create_hold_signal


class MACrossStrategy(StrategyBase):
    """
    均线交叉策略

    交易规则：
    1. 金叉（快线上穿慢线）：买入信号
    2. 死叉（快线下穿慢线）：卖出信号
    3. 其他：持有

    参数：
    - fast_period: 快线周期（默认5）
    - slow_period: 慢线周期（默认20）
    - volume_threshold: 成交量放大阈值（默认1.5倍）
    """

    DEFAULT_PARAMS = {
        'fast_period': 5,
        'slow_period': 20,
        'volume_threshold': 1.5,
    }

    def __init__(
        self,
        strategy_id: str = "ma_cross",
        name: str = "均线交叉策略",
        parameters: Optional[Dict[str, Any]] = None,
    ):
        params = {**self.DEFAULT_PARAMS, **(parameters or {})}
        super().__init__(
            strategy_id=strategy_id,
            name=name,
            strategy_type=StrategyType.TRADING,
            description="基于快慢均线交叉的趋势跟踪策略，金叉买入，死叉卖出",
            parameters=params,
        )

    def validate_parameters(self) -> bool:
        """验证参数有效性"""
        try:
            if self.parameters['fast_period'] <= 0:
                return False
            if self.parameters['slow_period'] <= 0:
                return False
            if self.parameters['fast_period'] >= self.parameters['slow_period']:
                return False  # 快线周期必须小于慢线周期
            return True
        except Exception:
            return False

    def generate_signals(self, data: pd.DataFrame, **kwargs) -> List[Signal]:
        """
        生成交易信号

        Args:
            data: 股票价格数据，需包含以下列：
                - date: 日期
                - close: 收盘价
                - volume: 成交量（可选）
                - symbol: 股票代码（可选）

        Returns:
            交易信号列表
        """
        signals = []

        if data.empty or 'close' not in data.columns:
            return signals

        # 确保数据按日期排序
        if 'date' in data.columns:
            data = data.sort_values('date')

        fast_period = self.parameters['fast_period']
        slow_period = self.parameters['slow_period']

        # 计算均线
        data = data.copy()
        data['ma_fast'] = data['close'].rolling(window=fast_period).mean()
        data['ma_slow'] = data['close'].rolling(window=slow_period).mean()

        # 计算成交量均值（如果有成交量数据）
        if 'volume' in data.columns:
            data['volume_ma'] = data['volume'].rolling(window=slow_period).mean()

        # 需要至少slow_period + 1天的数据
        if len(data) < slow_period + 1:
            return signals

        # 遍历数据，寻找交叉点
        for i in range(slow_period, len(data)):
            try:
                current = data.iloc[i]
                previous = data.iloc[i - 1]

                # 跳过NaN
                if pd.isna(current['ma_fast']) or pd.isna(current['ma_slow']):
                    continue

                # 金叉：快线上穿慢线
                if (previous['ma_fast'] <= previous['ma_slow']) and (current['ma_fast'] > current['ma_slow']):
                    strength = SignalStrength.MODERATE
                    confidence = 0.6

                    # 成交量放大，增强信号
                    if 'volume' in data.columns and 'volume_ma' in data.columns:
                        if not pd.isna(current['volume_ma']) and current['volume'] > current['volume_ma'] * self.parameters['volume_threshold']:
                            strength = SignalStrength.STRONG
                            confidence = 0.8

                    reason = f"金叉: MA{fast_period}({current['ma_fast']:.2f})上穿MA{slow_period}({current['ma_slow']:.2f})"

                    signal = create_buy_signal(
                        reason=reason,
                        confidence=confidence,
                        strength=strength,
                        metadata={
                            'symbol': current.get('symbol', ''),
                            'date': current.get('date', '').isoformat() if isinstance(current.get('date'), pd.Timestamp) else str(current.get('date', '')),
                            'ma_fast': float(current['ma_fast']),
                            'ma_slow': float(current['ma_slow']),
                            'close': float(current['close']),
                            'volume': float(current.get('volume', 0)),
                        }
                    )
                    signals.append(signal)

                # 死叉：快线下穿慢线
                elif (previous['ma_fast'] >= previous['ma_slow']) and (current['ma_fast'] < current['ma_slow']):
                    strength = SignalStrength.MODERATE
                    confidence = 0.6

                    # 成交量放大，增强信号
                    if 'volume' in data.columns and 'volume_ma' in data.columns:
                        if not pd.isna(current['volume_ma']) and current['volume'] > current['volume_ma'] * self.parameters['volume_threshold']:
                            strength = SignalStrength.STRONG
                            confidence = 0.8

                    reason = f"死叉: MA{fast_period}({current['ma_fast']:.2f})下穿MA{slow_period}({current['ma_slow']:.2f})"

                    signal = create_sell_signal(
                        reason=reason,
                        confidence=confidence,
                        strength=strength,
                        metadata={
                            'symbol': current.get('symbol', ''),
                            'date': current.get('date', '').isoformat() if isinstance(current.get('date'), pd.Timestamp) else str(current.get('date', '')),
                            'ma_fast': float(current['ma_fast']),
                            'ma_slow': float(current['ma_slow']),
                            'close': float(current['close']),
                            'volume': float(current.get('volume', 0)),
                        }
                    )
                    signals.append(signal)

            except Exception:
                continue

        return signals

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MACrossStrategy':
        """从字典创建策略实例"""
        return cls(
            strategy_id=data.get('strategy_id', 'ma_cross'),
            name=data.get('name', '均线交叉策略'),
            parameters=data.get('parameters'),
        )
