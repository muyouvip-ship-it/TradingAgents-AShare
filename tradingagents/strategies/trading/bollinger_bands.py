"""
布林带策略

基于布林带指标的交易策略。
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import pandas as pd
import numpy as np

from tradingagents.strategies.base.strategy_base import StrategyBase, StrategyType
from tradingagents.strategies.base.signal import Signal, SignalType


class BollingerBandsStrategy(StrategyBase):
    """布林带策略 - 基于布林带的突破交易"""
    
    def __init__(
        self,
        strategy_id: str = "bollinger_bands",
        name: str = "布林带策略",
        description: str = "基于布林带指标的交易策略，在价格突破布林带时生成信号",
        parameters: Optional[Dict[str, Any]] = None,
    ):
        default_params = {
            "period": 20,
            "std_dev": 2.0,
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
        """生成布林带交易信号"""
        signals = []
        
        # 计算布林带
        data = self._calculate_bollinger_bands(data)
        
        # 生成信号
        for i in range(1, len(data)):
            price = data['close'].iloc[i]
            upper_band = data['upper_band'].iloc[i]
            lower_band = data['lower_band'].iloc[i]
            middle_band = data['middle_band'].iloc[i]
            
            # 价格跌破下轨后反弹
            if (data['close'].iloc[i-1] <= data['lower_band'].iloc[i-1] and
                price > lower_band):
                
                signal = Signal(
                    symbol=data['symbol'].iloc[i],
                    signal_type=SignalType.BUY,
                    price=price,
                    quantity=0,
                    timestamp=data['date'].iloc[i],
                    confidence=self._calculate_confidence(data, i, SignalType.BUY),
                    metadata={
                        "price": float(price),
                        "lower_band": float(lower_band),
                        "middle_band": float(middle_band),
                        "reason": "价格跌破下轨后反弹",
                    }
                )
                signals.append(signal)
            
            # 价格突破上轨后回落
            elif (data['close'].iloc[i-1] >= data['upper_band'].iloc[i-1] and
                  price < upper_band):
                
                signal = Signal(
                    symbol=data['symbol'].iloc[i],
                    signal_type=SignalType.SELL,
                    price=price,
                    quantity=0,
                    timestamp=data['date'].iloc[i],
                    confidence=self._calculate_confidence(data, i, SignalType.SELL),
                    metadata={
                        "price": float(price),
                        "upper_band": float(upper_band),
                        "middle_band": float(middle_band),
                        "reason": "价格突破上轨后回落",
                    }
                )
                signals.append(signal)
        
        self.logger.info(f"Generated {len(signals)} Bollinger Bands signals")
        return signals
    
    def _calculate_bollinger_bands(self, data: pd.DataFrame) -> pd.DataFrame:
        """计算布林带指标"""
        data = data.copy()
        
        # 中轨（移动平均）
        data['middle_band'] = data['close'].rolling(window=self.parameters['period']).mean()
        
        # 标准差
        std = data['close'].rolling(window=self.parameters['period']).std()
        
        # 上轨和下轨
        data['upper_band'] = data['middle_band'] + (std * self.parameters['std_dev'])
        data['lower_band'] = data['middle_band'] - (std * self.parameters['std_dev'])
        
        return data
    
    def _calculate_confidence(self, data: pd.DataFrame, i: int, signal_type: SignalType) -> float:
        """计算信号置信度"""
        price = data['close'].iloc[i]
        middle_band = data['middle_band'].iloc[i]
        
        # 距离中轨越远，置信度越高
        distance = abs(price - middle_band) / middle_band
        confidence = min(distance * 10, 1.0)
        
        return confidence
    
    def validate_parameters(self) -> bool:
        """验证参数"""
        period = self.parameters.get('period', 20)
        std_dev = self.parameters.get('std_dev', 2.0)
        
        if period <= 0:
            return False
        if std_dev <= 0:
            return False
        return True
