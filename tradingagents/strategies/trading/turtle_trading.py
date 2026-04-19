"""
海龟交易策略

基于海龟交易法则的趋势跟踪策略。
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import pandas as pd
import numpy as np

from tradingagents.strategies.base.strategy_base import StrategyBase, StrategyType
from tradingagents.strategies.base.signal import Signal, SignalType


class TurtleTradingStrategy(StrategyBase):
    """海龟交易策略 - 基于唐奇安通道的趋势跟踪"""
    
    def __init__(
        self,
        strategy_id: str = "turtle_trading",
        name: str = "海龟交易策略",
        description: str = "基于海龟交易法则的趋势跟踪策略，使用唐奇安通道生成信号",
        parameters: Optional[Dict[str, Any]] = None,
    ):
        default_params = {
            "entry_period": 20,
            "exit_period": 10,
        }
        
        if parameters:
            default_params.update(parameters)
        
        super().__init__(
            strategy_id=strategy_id,
            name=name,
            description=description,
            strategy_type=StrategyType.TRADING,
            parameters=default_params,
        )
    
    def generate_signals(self, data: pd.DataFrame) -> List[Signal]:
        """生成海龟交易信号"""
        signals = []
        
        # 计算唐奇安通道
        data = self._calculate_donchian(data)
        
        # 生成信号
        for i in range(max(self.parameters['entry_period'], self.parameters['exit_period']), len(data)):
            # 突破入场：价格突破N日最高价
            if data['close'].iloc[i] > data['upper_channel_entry'].iloc[i-1]:
                signal = Signal(
                    symbol=data['symbol'].iloc[i],
                    signal_type=SignalType.BUY,
                    price=data['close'].iloc[i],
                    quantity=0,
                    timestamp=data['date'].iloc[i],
                    confidence=self._calculate_confidence(data, i, SignalType.BUY),
                    metadata={
                        "price": float(data['close'].iloc[i]),
                        "upper_channel": float(data['upper_channel_entry'].iloc[i]),
                        "lower_channel": float(data['lower_channel_exit'].iloc[i]),
                        "reason": "突破20日新高",
                    }
                )
                signals.append(signal)
            
            # 突破出场：价格跌破M日最低价
            elif data['close'].iloc[i] < data['lower_channel_exit'].iloc[i-1]:
                signal = Signal(
                    symbol=data['symbol'].iloc[i],
                    signal_type=SignalType.SELL,
                    price=data['close'].iloc[i],
                    quantity=0,
                    timestamp=data['date'].iloc[i],
                    confidence=self._calculate_confidence(data, i, SignalType.SELL),
                    metadata={
                        "price": float(data['close'].iloc[i]),
                        "upper_channel": float(data['upper_channel_entry'].iloc[i]),
                        "lower_channel": float(data['lower_channel_exit'].iloc[i]),
                        "reason": "跌破10日新低",
                    }
                )
                signals.append(signal)
        
        self.logger.info(f"Generated {len(signals)} Turtle Trading signals")
        return signals
    
    def _calculate_donchian(self, data: pd.DataFrame) -> pd.DataFrame:
        """计算唐奇安通道"""
        data = data.copy()
        
        # 入场通道（20日）
        data['upper_channel_entry'] = data['high'].rolling(window=self.parameters['entry_period']).max()
        data['lower_channel_entry'] = data['low'].rolling(window=self.parameters['entry_period']).min()
        
        # 出场通道（10日）
        data['upper_channel_exit'] = data['high'].rolling(window=self.parameters['exit_period']).max()
        data['lower_channel_exit'] = data['low'].rolling(window=self.parameters['exit_period']).min()
        
        return data
    
    def _calculate_confidence(self, data: pd.DataFrame, i: int, signal_type: SignalType) -> float:
        """计算信号置信度"""
        # 基于突破幅度
        if signal_type == SignalType.BUY:
            breakout_strength = (data['close'].iloc[i] - data['upper_channel_entry'].iloc[i-1]) / data['close'].iloc[i]
        else:
            breakout_strength = (data['lower_channel_exit'].iloc[i-1] - data['close'].iloc[i]) / data['close'].iloc[i]
        
        confidence = min(breakout_strength * 100, 1.0)
        return confidence
    
    def validate_parameters(self) -> bool:
        """验证参数"""
        entry_period = self.parameters.get('entry_period', 20)
        exit_period = self.parameters.get('exit_period', 10)
        
        if entry_period <= 0 or exit_period <= 0:
            return False
        if exit_period > entry_period:
            return False
        return True
