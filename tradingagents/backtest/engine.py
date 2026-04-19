"""
回测引擎

实现策略回测的核心逻辑。
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import logging

from tradingagents.strategies.base.strategy_base import Signal, SignalType
from tradingagents.strategies.manager import get_strategy_manager

logger = logging.getLogger(__name__)


class BacktestEngine:
    """
    回测引擎

    功能：
    - 根据策略信号模拟交易
    - 计算收益、风险指标
    - 生成回测报告
    """

    def __init__(
        self,
        initial_capital: float = 1000000.0,
        commission_rate: float = 0.0003,  # 佣金率 0.03%
        slippage_rate: float = 0.0001,    # 滑点率 0.01%
    ):
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate

    def run_backtest(
        self,
        strategy_id: str,
        data: pd.DataFrame,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        运行回测

        Args:
            strategy_id: 策略ID
            data: 价格数据（需包含 date, close, volume 等列）
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            回测结果字典
        """
        # 获取策略
        strategy_manager = get_strategy_manager()
        strategy = strategy_manager.get_strategy(strategy_id)

        if not strategy:
            raise ValueError(f"Strategy not found: {strategy_id}")

        # 数据过滤
        if start_date:
            data = data[data['date'] >= start_date]
        if end_date:
            data = data[data['date'] <= end_date]

        if data.empty:
            raise ValueError("No data available for backtest")

        # 生成信号
        signals = strategy.generate_signals(data)

        # 模拟交易
        portfolio_values = []
        cash = self.initial_capital
        position = 0  # 持仓数量
        trades = []

        for i, row in data.iterrows():
            current_date = row['date']
            close_price = row['close']

            # 检查是否有信号
            signal = self._get_signal_for_date(signals, current_date)

            if signal:
                if signal.signal_type == SignalType.BUY and cash > 0:
                    # 买入
                    buy_price = close_price * (1 + self.slippage_rate)
                    shares = int(cash / buy_price)
                    if shares > 0:
                        commission = shares * buy_price * self.commission_rate
                        cost = shares * buy_price + commission
                        cash -= cost
                        position += shares
                        trades.append({
                            'date': current_date,
                            'type': 'BUY',
                            'price': buy_price,
                            'shares': shares,
                            'commission': commission,
                        })

                elif signal.signal_type == SignalType.SELL and position > 0:
                    # 卖出
                    sell_price = close_price * (1 - self.slippage_rate)
                    revenue = position * sell_price
                    commission = revenue * self.commission_rate
                    cash += revenue - commission
                    trades.append({
                        'date': current_date,
                        'type': 'SELL',
                        'price': sell_price,
                        'shares': position,
                        'commission': commission,
                    })
                    position = 0

            # 计算当前组合价值
            portfolio_value = cash + position * close_price
            portfolio_values.append({
                'date': current_date,
                'value': portfolio_value,
                'cash': cash,
                'position': position,
                'price': close_price,
            })

        # 计算绩效指标
        df_values = pd.DataFrame(portfolio_values)
        metrics = self._calculate_metrics(df_values)

        return {
            'strategy_id': strategy_id,
            'strategy_name': strategy.name,
            'start_date': start_date or data['date'].min(),
            'end_date': end_date or data['date'].max(),
            'initial_capital': self.initial_capital,
            'final_capital': df_values['value'].iloc[-1],
            'metrics': metrics,
            'trades': trades,
            'portfolio_values': df_values.to_dict('records'),
            'total_trades': len(trades),
        }

    def _get_signal_for_date(self, signals: List[Signal], date) -> Optional[Signal]:
        """获取指定日期的信号"""
        for signal in signals:
            if signal.metadata and signal.metadata.get('date') == str(date):
                return signal
        return None

    def _calculate_metrics(self, df: pd.DataFrame) -> Dict[str, float]:
        """计算绩效指标"""
        if df.empty:
            return {}

        # 计算收益率
        returns = df['value'].pct_change().dropna()

        # 总收益率
        total_return = (df['value'].iloc[-1] - self.initial_capital) / self.initial_capital

        # 年化收益率
        days = (pd.to_datetime(df['date'].iloc[-1]) - pd.to_datetime(df['date'].iloc[0])).days
        annual_return = (1 + total_return) ** (365 / max(days, 1)) - 1 if days > 0 else 0

        # 夏普比率
        sharpe_ratio = 0.0
        if not returns.empty and returns.std() > 0:
            sharpe_ratio = (returns.mean() * 252) / (returns.std() * np.sqrt(252))

        # 最大回撤
        cummax = df['value'].cummax()
        drawdown = (df['value'] - cummax) / cummax
        max_drawdown = drawdown.min()

        # 胜率
        winning_days = (returns > 0).sum()
        total_days = len(returns)
        win_rate = winning_days / total_days if total_days > 0 else 0

        # 盈亏比
        profit_factor = 0.0
        if not returns.empty:
            profits = returns[returns > 0].sum()
            losses = abs(returns[returns < 0].sum())
            profit_factor = profits / losses if losses > 0 else 0

        # 波动率
        volatility = returns.std() * np.sqrt(252) if not returns.empty else 0

        return {
            'total_return': float(total_return),
            'annual_return': float(annual_return),
            'sharpe_ratio': float(sharpe_ratio),
            'max_drawdown': float(max_drawdown),
            'win_rate': float(win_rate),
            'profit_factor': float(profit_factor),
            'volatility': float(volatility),
            'total_trades': len([t for t in [] if t.get('type') == 'BUY']),  # 临时占位
        }
