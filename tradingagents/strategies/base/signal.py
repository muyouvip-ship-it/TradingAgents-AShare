"""
信号模块

定义交易信号相关的类和工具函数。
"""

from typing import Optional
from tradingagents.strategies.base.strategy_base import Signal, SignalType, SignalStrength

__all__ = ['Signal', 'SignalType', 'SignalStrength']


def create_buy_signal(
    reason: str,
    confidence: float = 0.7,
    strength: SignalStrength = SignalStrength.MODERATE,
    metadata: Optional[dict] = None
) -> Signal:
    """
    创建买入信号

    Args:
        reason: 买入原因
        confidence: 信号置信度 (0.0-1.0)
        strength: 信号强度
        metadata: 额外元数据

    Returns:
        Signal对象
    """
    return Signal(
        type=SignalType.BUY,
        strength=strength,
        confidence=confidence,
        reason=reason,
        metadata=metadata or {}
    )


def create_sell_signal(
    reason: str,
    confidence: float = 0.7,
    strength: SignalStrength = SignalStrength.MODERATE,
    metadata: Optional[dict] = None
) -> Signal:
    """
    创建卖出信号

    Args:
        reason: 卖出原因
        confidence: 信号置信度 (0.0-1.0)
        strength: 信号强度
        metadata: 额外元数据

    Returns:
        Signal对象
    """
    return Signal(
        type=SignalType.SELL,
        strength=strength,
        confidence=confidence,
        reason=reason,
        metadata=metadata or {}
    )


def create_hold_signal(
    reason: str = "保持当前仓位",
    confidence: float = 0.5,
    metadata: Optional[dict] = None
) -> Signal:
    """
    创建持有信号

    Args:
        reason: 持有原因
        confidence: 信号置信度
        metadata: 额外元数据

    Returns:
        Signal对象
    """
    return Signal(
        type=SignalType.HOLD,
        strength=SignalStrength.MODERATE,
        confidence=confidence,
        reason=reason,
        metadata=metadata or {}
    )
