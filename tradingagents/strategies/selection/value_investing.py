"""
价值投资策略

基于基本面指标筛选低估值、高质量的股票。
核心指标：PE、PB、ROE、股息率、负债率
"""

from typing import Any, Dict, List, Optional
import pandas as pd

from tradingagents.strategies.base.strategy_base import (
    StrategyBase,
    StrategyType,
    Signal,
    SignalType,
    SignalStrength,
)
from tradingagents.strategies.base.signal import create_buy_signal, create_hold_signal


class ValueInvestingStrategy(StrategyBase):
    """
    价值投资策略

    选股标准：
    1. PE市盈率 < 阈值（默认15）
    2. PB市净率 < 阈值（默认1.5）
    3. ROE净资产收益率 > 阈值（默认15%）
    4. 股息率 > 阈值（默认3%）
    5. 资产负债率 < 阈值（默认60%）

    满足条件越多，信号越强
    """

    DEFAULT_PARAMS = {
        'pe_threshold': 15,           # PE阈值
        'pb_threshold': 1.5,          # PB阈值
        'roe_threshold': 0.15,        # ROE阈值（15%）
        'dividend_yield_threshold': 0.03,  # 股息率阈值（3%）
        'debt_ratio_threshold': 0.6,  # 资产负债率阈值（60%）
        'max_stocks': 20,             # 最多选股数量
        'min_score': 3,               # 最低满足条件数
    }

    def __init__(
        self,
        strategy_id: str = "value_investing",
        name: str = "价值投资策略",
        parameters: Optional[Dict[str, Any]] = None,
    ):
        params = {**self.DEFAULT_PARAMS, **(parameters or {})}
        super().__init__(
            strategy_id=strategy_id,
            name=name,
            strategy_type=StrategyType.SELECTION,
            description="基于基本面指标的选股策略，筛选低估值、高质量的股票",
            parameters=params,
        )

    def validate_parameters(self) -> bool:
        """验证参数有效性"""
        try:
            # 检查必需参数
            required_keys = ['pe_threshold', 'pb_threshold', 'roe_threshold']
            for key in required_keys:
                if key not in self.parameters:
                    return False

            # 检查参数范围
            if self.parameters['pe_threshold'] <= 0:
                return False
            if self.parameters['pb_threshold'] <= 0:
                return False
            if not (0 <= self.parameters['roe_threshold'] <= 1):
                return False

            return True
        except Exception:
            return False

    def generate_signals(self, data: pd.DataFrame, **kwargs) -> List[Signal]:
        """
        生成选股信号

        Args:
            data: 股票基本面数据，需包含以下列：
                - symbol: 股票代码
                - pe: 市盈率
                - pb: 市净率
                - roe: 净资产收益率
                - dividend_yield: 股息率
                - debt_ratio: 资产负债率
                - name: 股票名称（可选）

        Returns:
            选股信号列表
        """
        signals = []

        if data.empty or 'symbol' not in data.columns:
            return signals

        for _, row in data.iterrows():
            try:
                symbol = row.get('symbol', '')
                name = row.get('name', symbol)

                # 计算满足的条件数
                score = 0
                reasons = []

                # PE条件
                pe = row.get('pe')
                if pe is not None and pe > 0 and pe < self.parameters['pe_threshold']:
                    score += 1
                    reasons.append(f"PE({pe:.1f})<{self.parameters['pe_threshold']}")

                # PB条件
                pb = row.get('pb')
                if pb is not None and pb > 0 and pb < self.parameters['pb_threshold']:
                    score += 1
                    reasons.append(f"PB({pb:.2f})<{self.parameters['pb_threshold']}")

                # ROE条件
                roe = row.get('roe')
                if roe is not None and roe > self.parameters['roe_threshold']:
                    score += 1
                    reasons.append(f"ROE({roe*100:.1f}%)>{self.parameters['roe_threshold']*100}%")

                # 股息率条件
                div_yield = row.get('dividend_yield')
                if div_yield is not None and div_yield > self.parameters['dividend_yield_threshold']:
                    score += 1
                    reasons.append(f"股息率({div_yield*100:.2f}%)>{self.parameters['dividend_yield_threshold']*100}%")

                # 负债率条件
                debt_ratio = row.get('debt_ratio')
                if debt_ratio is not None and debt_ratio < self.parameters['debt_ratio_threshold']:
                    score += 1
                    reasons.append(f"负债率({debt_ratio*100:.1f}%)<{self.parameters['debt_ratio_threshold']*100}%")

                # 生成信号
                if score >= self.parameters['min_score']:
                    strength = SignalStrength.STRONG if score >= 4 else SignalStrength.MODERATE
                    confidence = score / 5.0  # 置信度 = 满足条件数 / 总条件数

                    signal = create_buy_signal(
                        reason=f"{name}: {', '.join(reasons)} (得分:{score}/5)",
                        confidence=confidence,
                        strength=strength,
                        metadata={
                            'symbol': symbol,
                            'name': name,
                            'score': score,
                            'pe': pe,
                            'pb': pb,
                            'roe': roe,
                            'dividend_yield': div_yield,
                            'debt_ratio': debt_ratio,
                        }
                    )
                    signals.append(signal)

            except Exception as e:
                # 跳过异常数据
                continue

        # 按得分排序，取前N个
        signals.sort(key=lambda s: s.metadata.get('score', 0), reverse=True)
        return signals[:self.parameters['max_stocks']]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ValueInvestingStrategy':
        """从字典创建策略实例"""
        return cls(
            strategy_id=data.get('strategy_id', 'value_investing'),
            name=data.get('name', '价值投资策略'),
            parameters=data.get('parameters'),
        )
