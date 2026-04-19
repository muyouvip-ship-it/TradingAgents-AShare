"""
MACD策略

基于MACD指标的交易策略。
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import pandas as pd
import numpy as np

from tradingagents.strategies.base.strategy_base import StrategyBase, StrategyType
from tradingagents.strategies.base.signal import Signal, SignalType


class MACDStrategy(StrategyBase):
    """MACD策略 - 基于MACD指标的金叉死叉信号"""
    
    def __init__(
        self,
        strategy_id: str = "macd",
        name: str = "MACD策略",
        description: str = "基于MACD指标的交易策略，通过快慢线交叉生成买卖信号",
        parameters: Optional[Dict[str, Any]] = None,
    ):
        default_params = {
            "fast_period": 12,
            "slow_period": 26,
            "signal_period": 9,
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
        """生成MACD交易信号"""
        signals = []
        
        # 计算MACD指标
        data = self._calculate_macd(data)
        
        # 生成信号
        for i in range(1, len(data)):
            # 金叉：MACD上穿信号线
            if (data['macd'].iloc[i] > data['signal_line'].iloc[i] and
                data['macd'].iloc[i-1] <= data['signal_line'].iloc[i-1]):
                
                signal = Signal(
                    symbol=data['symbol'].iloc[i],
                    signal_type=SignalType.BUY,
                    price=data['close'].iloc[i],
                    quantity=0,  # 由风险管理模块决定
                    timestamp=data['date'].iloc[i],
                    confidence=self._calculate_confidence(data, i, SignalType.BUY),
                    metadata={
                        "macd": float(data['macd'].iloc[i]),
                        "signal_line": float(data['signal_line'].iloc[i]),
                        "histogram": float(data['histogram'].iloc[i]),
                        "reason": "MACD金叉",
                    }
                )
                signals.append(signal)
            
            # 死叉：MACD下穿信号线
            elif (data['macd'].iloc[i] < data['signal_line'].iloc[i] and
                  data['macd'].iloc[i-1] >= data['signal_line'].iloc[i-1]):
                
                signal = Signal(
                    symbol=data['symbol'].iloc[i],
                    signal_type=SignalType.SELL,
                    price=data['close'].iloc[i],
                    quantity=0,
                    timestamp=data['date'].iloc[i],
                    confidence=self._calculate_confidence(data, i, SignalType.SELL),
                    metadata={
                        "macd": float(data['macd'].iloc[i]),
                        "signal_line": float(data['signal_line'].iloc[i]),
                        "histogram": float(data['histogram'].iloc[i]),
                        "reason": "MACD死叉",
                    }
                )
                signals.append(signal)
        
        self.logger.info(f"Generated {len(signals)} MACD signals")
        return signals
    
    def _calculate_macd(self, data: pd.DataFrame) -> pd.DataFrame:
        """计算MACD指标"""
        data = data.copy()
        
        # 计算EMA
        ema_fast = data['close'].ewm(span=self.parameters['fast_period'], adjust=False).mean()
        ema_slow = data['close'].ewm(span=self.parameters['slow_period'], adjust=False).mean()
        
        # MACD线
        data['macd'] = ema_fast - ema_slow
        
        # 信号线
        data['signal_line'] = data['macd'].ewm(span=self.parameters['signal_period'], adjust=False).mean()
        
        # 柱状图
        data['histogram'] = data['macd'] - data['signal_line']
        
        return data
    
    def _calculate_confidence(self, data: pd.DataFrame, i: int, signal_type: SignalType) -> float:
        """计算信号置信度"""
        # 基于柱状图强度
        histogram = abs(data['histogram'].iloc[i])
        
        # 基于趋势强度
        if signal_type == SignalType.BUY:
            trend_strength = data['macd'].iloc[i] > 0
        else:
            trend_strength = data['macd'].iloc[i] < 0
        
        confidence = min(histogram / data['close'].iloc[i] * 100, 1.0)
        if trend_strength:
            confidence = min(confidence * 1.2, 1.0)
        
        return confidence
    
    def validate_parameters(self) -> bool:
        """验证参数"""
        fast = self.parameters.get('fast_period', 12)
        slow = self.parameters.get('slow_period', 26)
        signal = self.parameters.get('signal_period', 9)
        
        if fast <= 0 or slow <= 0 or signal <= 0:
            return False
        if fast >= slow:
            return False
        return True
