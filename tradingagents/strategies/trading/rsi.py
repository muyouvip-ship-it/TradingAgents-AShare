"""
RSI策略

基于RSI指标的交易策略。
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import pandas as pd
import numpy as np

from tradingagents.strategies.base.strategy_base import StrategyBase, StrategyType
from tradingagents.strategies.base.signal import Signal, SignalType


class RSIStrategy(StrategyBase):
    """RSI策略 - 基于RSI指标的超买超卖信号"""
    
    def __init__(
        self,
        strategy_id: str = "rsi",
        name: str = "RSI策略",
        description: str = "基于RSI指标的交易策略，在超买超卖区域生成买卖信号",
        parameters: Optional[Dict[str, Any]] = None,
    ):
        default_params = {
            "period": 14,
            "oversold_threshold": 30,
            "overbought_threshold": 70,
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
        """生成RSI交易信号"""
        signals = []
        
        # 计算RSI
        data = self._calculate_rsi(data)
        
        # 生成信号
        for i in range(1, len(data)):
            rsi = data['rsi'].iloc[i]
            prev_rsi = data['rsi'].iloc[i-1]
            
            # 超卖反弹：RSI从下向上突破超卖线
            if (rsi > self.parameters['oversold_threshold'] and
                prev_rsi <= self.parameters['oversold_threshold']):
                
                signal = Signal(
                    symbol=data['symbol'].iloc[i],
                    signal_type=SignalType.BUY,
                    price=data['close'].iloc[i],
                    quantity=0,
                    timestamp=data['date'].iloc[i],
                    confidence=self._calculate_confidence(data, i, SignalType.BUY),
                    metadata={
                        "rsi": float(rsi),
                        "reason": "RSI超卖反弹",
                    }
                )
                signals.append(signal)
            
            # 超买回落：RSI从上向下跌破超买线
            elif (rsi < self.parameters['overbought_threshold'] and
                  prev_rsi >= self.parameters['overbought_threshold']):
                
                signal = Signal(
                    symbol=data['symbol'].iloc[i],
                    signal_type=SignalType.SELL,
                    price=data['close'].iloc[i],
                    quantity=0,
                    timestamp=data['date'].iloc[i],
                    confidence=self._calculate_confidence(data, i, SignalType.SELL),
                    metadata={
                        "rsi": float(rsi),
                        "reason": "RSI超买回落",
                    }
                )
                signals.append(signal)
        
        self.logger.info(f"Generated {len(signals)} RSI signals")
        return signals
    
    def _calculate_rsi(self, data: pd.DataFrame) -> pd.DataFrame:
        """计算RSI指标"""
        data = data.copy()
        
        # 计算价格变化
        delta = data['close'].diff()
        
        # 分离上涨和下跌
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        # 计算平均上涨和下跌
        avg_gain = gain.rolling(window=self.parameters['period'], min_periods=1).mean()
        avg_loss = loss.rolling(window=self.parameters['period'], min_periods=1).mean()
        
        # 计算RS
        rs = avg_gain / avg_loss
        
        # 计算RSI
        data['rsi'] = 100 - (100 / (1 + rs))
        
        return data
    
    def _calculate_confidence(self, data: pd.DataFrame, i: int, signal_type: SignalType) -> float:
        """计算信号置信度"""
        rsi = data['rsi'].iloc[i]
        
        # RSI越极端，置信度越高
        if signal_type == SignalType.BUY:
            confidence = (self.parameters['oversold_threshold'] - rsi) / self.parameters['oversold_threshold']
        else:
            confidence = (rsi - self.parameters['overbought_threshold']) / (100 - self.parameters['overbought_threshold'])
        
        return min(max(confidence, 0.5), 1.0)
    
    def validate_parameters(self) -> bool:
        """验证参数"""
        period = self.parameters.get('period', 14)
        oversold = self.parameters.get('oversold_threshold', 30)
        overbought = self.parameters.get('overbought_threshold', 70)
        
        if period <= 0:
            return False
        if oversold >= overbought:
            return False
        if oversold < 0 or overbought > 100:
            return False
        return True
