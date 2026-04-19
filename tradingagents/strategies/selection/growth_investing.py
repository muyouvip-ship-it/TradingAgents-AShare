"""
成长投资策略

基于成长指标筛选高增长的优质公司。
核心指标：营收增长率、净利润增长率、PEG、毛利率
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


class GrowthInvestingStrategy(StrategyBase):
    """
    成长投资策略

    选股标准：
    1. 营收增长率 > 阈值（默认20%）
    2. 净利润增长率 > 阈值（默认25%）
    3. PEG < 阈值（默认1.5）
    4. 毛利率 > 阈值（默认30%）
    5. ROE > 阈值（默认15%）

    满足条件越多，信号越强
    """

    DEFAULT_PARAMS = {
        'revenue_growth_threshold': 0.2,    # 营收增长率阈值（20%）
        'profit_growth_threshold': 0.25,    # 净利润增长率阈值（25%）
        'peg_threshold': 1.5,               # PEG阈值
        'gross_margin_threshold': 0.3,      # 毛利率阈值（30%）
        'roe_threshold': 0.15,              # ROE阈值（15%）
        'max_stocks': 20,                   # 最多选股数量
        'min_score': 3,                     # 最低满足条件数
    }

    def __init__(
        self,
        strategy_id: str = "growth_investing",
        name: str = "成长投资策略",
        parameters: Optional[Dict[str, Any]] = None,
    ):
        params = {**self.DEFAULT_PARAMS, **(parameters or {})}
        super().__init__(
            strategy_id=strategy_id,
            name=name,
            strategy_type=StrategyType.SELECTION,
            description="基于成长指标的选股策略，筛选高增长的优质公司",
            parameters=params,
        )

    def validate_parameters(self) -> bool:
        """验证参数有效性"""
        try:
            required_keys = ['revenue_growth_threshold', 'profit_growth_threshold']
            for key in required_keys:
                if key not in self.parameters:
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
                - revenue_growth: 营收增长率
                - profit_growth: 净利润增长率
                - peg: PEG比率
                - gross_margin: 毛利率
                - roe: 净资产收益率
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

                score = 0
                reasons = []

                # 营收增长率
                rev_growth = row.get('revenue_growth')
                if rev_growth is not None and rev_growth > self.parameters['revenue_growth_threshold']:
                    score += 1
                    reasons.append(f"营收增长({rev_growth*100:.1f}%)>{self.parameters['revenue_growth_threshold']*100}%")

                # 净利润增长率
                profit_growth = row.get('profit_growth')
                if profit_growth is not None and profit_growth > self.parameters['profit_growth_threshold']:
                    score += 1
                    reasons.append(f"利润增长({profit_growth*100:.1f}%)>{self.parameters['profit_growth_threshold']*100}%")

                # PEG
                peg = row.get('peg')
                if peg is not None and peg > 0 and peg < self.parameters['peg_threshold']:
                    score += 1
                    reasons.append(f"PEG({peg:.2f})<{self.parameters['peg_threshold']}")

                # 毛利率
                gross_margin = row.get('gross_margin')
                if gross_margin is not None and gross_margin > self.parameters['gross_margin_threshold']:
                    score += 1
                    reasons.append(f"毛利率({gross_margin*100:.1f}%)>{self.parameters['gross_margin_threshold']*100}%")

                # ROE
                roe = row.get('roe')
                if roe is not None and roe > self.parameters['roe_threshold']:
                    score += 1
                    reasons.append(f"ROE({roe*100:.1f}%)>{self.parameters['roe_threshold']*100}%")

                # 生成信号
                if score >= self.parameters['min_score']:
                    strength = SignalStrength.STRONG if score >= 4 else SignalStrength.MODERATE
                    confidence = score / 5.0

                    signal = create_buy_signal(
                        reason=f"{name}: {', '.join(reasons)} (得分:{score}/5)",
                        confidence=confidence,
                        strength=strength,
                        metadata={
                            'symbol': symbol,
                            'name': name,
                            'score': score,
                            'revenue_growth': rev_growth,
                            'profit_growth': profit_growth,
                            'peg': peg,
                            'gross_margin': gross_margin,
                            'roe': roe,
                        }
                    )
                    signals.append(signal)

            except Exception:
                continue

        signals.sort(key=lambda s: s.metadata.get('score', 0), reverse=True)
        return signals[:self.parameters['max_stocks']]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GrowthInvestingStrategy':
        """从字典创建策略实例"""
        return cls(
            strategy_id=data.get('strategy_id', 'growth_investing'),
            name=data.get('name', '成长投资策略'),
            parameters=data.get('parameters'),
        )
