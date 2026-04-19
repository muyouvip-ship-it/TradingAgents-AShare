"""
回测引擎核心模块

提供策略回测的核心功能，包括：
- 指标计算
- 信号生成
- 交易模拟
- 绩效计算
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
import logging

from tradingagents.backtest.indicators import IndicatorCalculator, ConditionParser

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    trade_id: str
    symbol: str
    direction: str
    price: float
    quantity: int
    amount: float
    timestamp: datetime
    commission: float
    slippage: float
    reason: str
    pnl: float = 0.0


@dataclass
class Position:
    symbol: str
    quantity: int
    avg_price: float
    current_price: float
    market_value: float
    pnl: float
    pnl_pct: float
    open_time: datetime
    highest_price: float = 0.0


@dataclass
class PendingOrder:
    symbol: str
    side: str  # buy / sell
    signal_date: datetime
    execute_date: datetime
    reason: str


@dataclass
class BacktestResult:
    job_id: str
    strategy_id: str
    strategy_name: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    total_return: float
    annual_return: float
    benchmark_return: float
    max_drawdown: float
    max_drawdown_duration: int
    volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    avg_holding_days: float
    max_positions: int
    equity_curve: List[Dict] = field(default_factory=list)
    drawdown_curve: List[Dict] = field(default_factory=list)
    trade_list: List[Dict] = field(default_factory=list)
    position_history: List[Dict] = field(default_factory=list)


class BacktestEngine:
    def __init__(
        self,
        initial_capital: float = 1000000.0,
        commission_rate: float = 0.0003,
        slippage_rate: float = 0.001,
        stamp_duty: float = 0.001,
    ):
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate
        self.stamp_duty = stamp_duty

        self.cash = initial_capital
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.equity_curve: List[Dict] = []
        self.pending_orders: List[PendingOrder] = []

        self.max_positions = 10
        self.max_single_position_pct = 0.3
        self.stop_loss_pct = 0.05
        self.take_profit_pct = 0.15
        self.trailing_stop_pct = 0.03
        self.max_daily_loss_pct = 0.03

        self.daily_pnl = 0.0
        self.daily_start_equity = initial_capital
        self.trading_dates: List[pd.Timestamp] = []

    def reset(self):
        self.cash = self.initial_capital
        self.positions = {}
        self.trades = []
        self.equity_curve = []
        self.pending_orders = []
        self.daily_pnl = 0.0
        self.daily_start_equity = self.initial_capital
        self.trading_dates = []

    def run_backtest(
        self,
        strategy: Dict,
        data: pd.DataFrame,
        start_date: datetime,
        end_date: datetime,
        backtest_mode: str = "indicator_driven",
    ) -> BacktestResult:
        logger.info(f"开始回测: {strategy['name']}, 模式: {backtest_mode}")
        self.reset()
        self._apply_risk_rules(strategy.get('risk_rules', {}))

        data = data.copy()
        data['date'] = pd.to_datetime(data['date'])
        data = IndicatorCalculator.calculate_all_indicators(
            data,
            strategy.get('indicators', [])
        )

        # 只使用真实存在于数据中的交易日
        self.trading_dates = sorted(
            d for d in pd.to_datetime(data['date'].dropna().unique())
            if pd.Timestamp(start_date) <= d <= pd.Timestamp(end_date)
        )

        for date in self.trading_dates:
            daily_data = data[data['date'] == date]
            if daily_data.empty:
                continue

            # 0. T+1 开盘成交：先执行前一交易日产生的待执行订单
            self._execute_pending_orders(daily_data, date)

            # 1. 持仓风控检查（基于当日价格；若触发则挂到下一交易日执行）
            self._check_positions(daily_data, date)

            # 2. 盘后生成买入信号，挂到下一交易日开盘执行
            buy_signals = self._generate_signals(strategy, data, 'entry', date)
            if buy_signals:
                for sig in buy_signals:
                    next_date = self._get_next_trading_date(date)
                    if next_date is not None:
                        self._queue_order(sig['symbol'], 'buy', date, next_date, sig.get('reason', 'entry_rule'))

            # 3. 盘后生成卖出信号，挂到下一交易日开盘执行
            if self.positions:
                sell_signals = self._generate_signals(strategy, data, 'exit', date)
                for sig in sell_signals:
                    if sig['symbol'] in self.positions:
                        next_date = self._get_next_trading_date(date)
                        if next_date is not None:
                            self._queue_order(sig['symbol'], 'sell', date, next_date, sig.get('reason', 'exit_rule'))

            # 4. 更新净值（收盘口径）
            self._update_equity(daily_data, date)

            if pd.Timestamp(date).weekday() == 4:
                self.daily_pnl = 0.0
                self.daily_start_equity = self._calculate_equity(daily_data)

        result = self._calculate_performance(strategy, start_date, end_date)
        logger.info(f"回测完成: 总收益率 {result.total_return:.2%}")
        return result

    def _apply_risk_rules(self, risk_rules: Dict):
        if not risk_rules:
            return
        self.max_positions = risk_rules.get('max_positions', 10)
        self.stop_loss_pct = risk_rules.get('stop_loss', 0.05)
        self.take_profit_pct = risk_rules.get('take_profit', 0.15)
        self.trailing_stop_pct = risk_rules.get('trailing_stop', 0.03)
        self.max_daily_loss_pct = risk_rules.get('max_daily_loss', 0.03)

    def _get_next_trading_date(self, current_date: datetime):
        current_ts = pd.Timestamp(current_date)
        for d in self.trading_dates:
            if d > current_ts:
                return d
        return None

    def _queue_order(self, symbol: str, side: str, signal_date: datetime, execute_date: datetime, reason: str):
        if side == 'buy':
            if symbol in self.positions:
                return
            if any(o.symbol == symbol and o.side == 'buy' and o.execute_date == execute_date for o in self.pending_orders):
                return
        else:
            if symbol not in self.positions:
                return
            if any(o.symbol == symbol and o.side == 'sell' and o.execute_date == execute_date for o in self.pending_orders):
                return

        self.pending_orders.append(PendingOrder(
            symbol=symbol,
            side=side,
            signal_date=pd.Timestamp(signal_date),
            execute_date=pd.Timestamp(execute_date),
            reason=reason,
        ))

    def _execute_pending_orders(self, daily_data: pd.DataFrame, date: datetime):
        current_ts = pd.Timestamp(date)
        to_run = [o for o in self.pending_orders if pd.Timestamp(o.execute_date) == current_ts]
        if not to_run:
            return

        remaining = []
        for order in self.pending_orders:
            if pd.Timestamp(order.execute_date) != current_ts:
                remaining.append(order)
                continue

            if order.side == 'buy':
                self._execute_buy(order.symbol, daily_data, current_ts, order.reason)
            elif order.side == 'sell':
                self._execute_sell(order.symbol, daily_data, current_ts, order.reason)

        self.pending_orders = remaining

    def _check_positions(self, daily_data: pd.DataFrame, date: datetime):
        positions_to_close = []
        for symbol, position in self.positions.items():
            stock_data = daily_data[daily_data['symbol'] == symbol]
            if stock_data.empty:
                continue

            current_price = stock_data['close'].iloc[0]
            position.current_price = current_price
            if current_price > position.highest_price:
                position.highest_price = current_price

            position.pnl = (current_price - position.avg_price) * position.quantity
            position.pnl_pct = (current_price - position.avg_price) / position.avg_price

            if position.pnl_pct <= -self.stop_loss_pct:
                positions_to_close.append((symbol, 'stop_loss'))
                continue
            if self.take_profit_pct and position.pnl_pct >= self.take_profit_pct:
                positions_to_close.append((symbol, 'take_profit'))
                continue
            if self.trailing_stop_pct:
                drawdown_from_high = (position.highest_price - current_price) / position.highest_price
                if drawdown_from_high >= self.trailing_stop_pct:
                    positions_to_close.append((symbol, 'trailing_stop'))

        for symbol, reason in positions_to_close:
            next_date = self._get_next_trading_date(date)
            if next_date is not None:
                self._queue_order(symbol, 'sell', date, next_date, reason)

    def _generate_signals(
        self,
        strategy: Dict,
        all_data: pd.DataFrame,
        signal_type: str,
        date: datetime,
    ) -> List[Dict]:
        signals = []

        if signal_type == 'entry':
            rules = strategy.get('entry_rules', [])
            symbols_to_check = all_data[all_data['date'] == date]['symbol'].unique()
        else:
            rules = strategy.get('exit_rules', [])
            symbols_to_check = list(self.positions.keys())

        if not rules:
            return signals

        daily_data = all_data[all_data['date'] == date]
        if daily_data.empty:
            return signals

        for symbol in symbols_to_check:
            stock_history = all_data[
                (all_data['symbol'] == symbol) &
                (all_data['date'] <= date)
            ].copy()

            if len(stock_history) < 30:
                continue

            matched_rule = None
            for rule in rules:
                if self._check_condition(rule, stock_history, strategy.get('indicators', [])):
                    matched_rule = rule
                    break

            if matched_rule is not None:
                current_price = daily_data[daily_data['symbol'] == symbol]['close'].iloc[0]
                signals.append({
                    'symbol': symbol,
                    'price': current_price,
                    'date': date,
                    'reason': matched_rule.get('name', f'{signal_type}_rule'),
                })

        return signals

    def _check_condition(
        self,
        rule: Dict,
        stock_data: pd.DataFrame,
        indicators: List[Dict],
    ) -> bool:
        condition = rule.get('condition', '')
        if not condition:
            return False

        symbol = stock_data['symbol'].iloc[-1] if 'symbol' in stock_data.columns else None
        position = None
        if symbol and symbol in self.positions:
            pos = self.positions[symbol]
            position = {
                'entry_price': pos.avg_price,
                'highest_price': pos.highest_price,
            }

        try:
            return ConditionParser.parse_and_evaluate(condition, stock_data, position)
        except Exception as e:
            logger.error(f"Error evaluating condition '{condition}': {e}")
            return False

    def _execute_buy(self, symbol: str, daily_data: pd.DataFrame, date: datetime, reason: str):
        stock_data = daily_data[daily_data['symbol'] == symbol]
        if stock_data.empty or symbol in self.positions:
            return

        price = float(stock_data['open'].iloc[0])  # T+1 开盘成交

        if len(self.positions) >= self.max_positions:
            return

        available_cash = self.cash * self.max_single_position_pct
        quantity = int(available_cash / price / 100) * 100
        if quantity <= 0:
            return

        actual_amount = quantity * price
        actual_commission = actual_amount * self.commission_rate
        actual_slippage = actual_amount * self.slippage_rate
        total_cost = actual_amount + actual_commission + actual_slippage
        if total_cost > self.cash:
            return

        self.positions[symbol] = Position(
            symbol=symbol,
            quantity=quantity,
            avg_price=price,
            current_price=price,
            market_value=actual_amount,
            pnl=0.0,
            pnl_pct=0.0,
            open_time=pd.Timestamp(date),
            highest_price=price,
        )

        self.cash -= total_cost
        trade = Trade(
            trade_id=f"{pd.Timestamp(date).strftime('%Y%m%d')}_{symbol}_BUY",
            symbol=symbol,
            direction='buy',
            price=price,
            quantity=quantity,
            amount=actual_amount,
            timestamp=pd.Timestamp(date),
            commission=actual_commission,
            slippage=actual_slippage,
            reason=reason,
        )
        self.trades.append(trade)

    def _execute_sell(self, symbol: str, daily_data: pd.DataFrame, date: datetime, reason: str):
        if symbol not in self.positions:
            return

        stock_data = daily_data[daily_data['symbol'] == symbol]
        if stock_data.empty:
            return

        position = self.positions[symbol]
        price = float(stock_data['open'].iloc[0])  # T+1 开盘成交
        amount = position.quantity * price
        commission = amount * self.commission_rate
        stamp_duty = amount * self.stamp_duty
        slippage = amount * self.slippage_rate
        pnl = (price - position.avg_price) * position.quantity - commission - stamp_duty - slippage

        self.cash += (amount - commission - stamp_duty - slippage)
        self.daily_pnl += pnl

        trade = Trade(
            trade_id=f"{pd.Timestamp(date).strftime('%Y%m%d')}_{symbol}_SELL",
            symbol=symbol,
            direction='sell',
            price=price,
            quantity=position.quantity,
            amount=amount,
            timestamp=pd.Timestamp(date),
            commission=commission,
            slippage=slippage,
            reason=reason,
            pnl=pnl,
        )
        self.trades.append(trade)
        del self.positions[symbol]

    def _update_equity(self, daily_data: pd.DataFrame, date: datetime):
        total_equity = self._calculate_equity(daily_data)
        self.equity_curve.append({
            'date': pd.Timestamp(date).isoformat(),
            'equity': total_equity,
            'cash': self.cash,
            'positions_value': total_equity - self.cash,
        })

    def _calculate_equity(self, daily_data: pd.DataFrame) -> float:
        positions_value = 0.0
        for symbol, position in self.positions.items():
            stock_data = daily_data[daily_data['symbol'] == symbol]
            if stock_data.empty:
                positions_value += position.market_value
                continue
            current_price = float(stock_data['close'].iloc[0])
            position.market_value = position.quantity * current_price
            positions_value += position.market_value
        return self.cash + positions_value

    def _calculate_performance(self, strategy: Dict, start_date: datetime, end_date: datetime) -> BacktestResult:
        equity_df = pd.DataFrame(self.equity_curve)
        if equity_df.empty:
            final_capital = self.initial_capital
            total_return = 0.0
            annual_return = 0.0
            max_drawdown = 0.0
            max_drawdown_duration = 0
            volatility = 0.0
            sharpe_ratio = 0.0
            sortino_ratio = 0.0
            calmar_ratio = 0.0
        else:
            equity_df['returns'] = equity_df['equity'].pct_change().fillna(0.0)
            final_capital = float(equity_df['equity'].iloc[-1])
            total_return = (final_capital / self.initial_capital) - 1
            total_days = max((pd.Timestamp(end_date) - pd.Timestamp(start_date)).days, 1)
            annual_return = (1 + total_return) ** (365 / total_days) - 1 if total_return > -1 else -1

            equity_df['cummax'] = equity_df['equity'].cummax()
            equity_df['drawdown'] = (equity_df['equity'] - equity_df['cummax']) / equity_df['cummax']
            max_drawdown = abs(float(equity_df['drawdown'].min())) if not equity_df.empty else 0.0
            max_drawdown_duration = int((equity_df['drawdown'] < 0).sum())
            volatility = float(equity_df['returns'].std() * np.sqrt(252)) if len(equity_df) > 1 else 0.0
            sharpe_ratio = float((equity_df['returns'].mean() / equity_df['returns'].std()) * np.sqrt(252)) if len(equity_df) > 1 and equity_df['returns'].std() > 0 else 0.0
            downside_returns = equity_df['returns'][equity_df['returns'] < 0]
            sortino_ratio = float((equity_df['returns'].mean() / downside_returns.std()) * np.sqrt(252)) if len(downside_returns) > 1 and downside_returns.std() > 0 else 0.0
            calmar_ratio = float(annual_return / max_drawdown) if max_drawdown > 0 else 0.0

        sell_trades = [t for t in self.trades if t.direction == 'sell']
        winning_trades = len([t for t in sell_trades if t.pnl > 0])
        losing_trades = len([t for t in sell_trades if t.pnl <= 0])
        win_rate = winning_trades / len(sell_trades) if sell_trades else 0.0
        avg_win = float(np.mean([t.pnl for t in sell_trades if t.pnl > 0])) if winning_trades else 0.0
        avg_loss = float(np.mean([t.pnl for t in sell_trades if t.pnl <= 0])) if losing_trades else 0.0
        profit_factor = abs(avg_win * winning_trades / (avg_loss * losing_trades)) if losing_trades and avg_loss != 0 else 0.0

        holding_days = []
        buy_map = {}
        for t in self.trades:
            key = (t.symbol, t.direction)
            if t.direction == 'buy':
                buy_map[t.symbol] = pd.Timestamp(t.timestamp)
            elif t.direction == 'sell' and t.symbol in buy_map:
                holding_days.append((pd.Timestamp(t.timestamp) - buy_map[t.symbol]).days)
                del buy_map[t.symbol]

        trade_list = [{
            'trade_id': t.trade_id,
            'symbol': t.symbol,
            'direction': t.direction,
            'price': t.price,
            'quantity': t.quantity,
            'amount': t.amount,
            'timestamp': pd.Timestamp(t.timestamp).isoformat(),
            'pnl': t.pnl,
            'reason': t.reason,
        } for t in self.trades]

        drawdown_curve = []
        if not equity_df.empty and 'drawdown' in equity_df.columns:
            drawdown_curve = [{
                'date': row['date'],
                'drawdown': float(row['drawdown'])
            } for _, row in equity_df.iterrows()]

        return BacktestResult(
            job_id='manual',
            strategy_id=strategy.get('id', ''),
            strategy_name=strategy.get('name', ''),
            start_date=pd.Timestamp(start_date),
            end_date=pd.Timestamp(end_date),
            initial_capital=self.initial_capital,
            final_capital=final_capital,
            total_return=float(total_return),
            annual_return=float(annual_return),
            benchmark_return=0.0,
            max_drawdown=float(max_drawdown),
            max_drawdown_duration=max_drawdown_duration,
            volatility=float(volatility),
            sharpe_ratio=float(sharpe_ratio),
            sortino_ratio=float(sortino_ratio),
            calmar_ratio=float(calmar_ratio),
            total_trades=len(sell_trades),
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=float(win_rate),
            avg_win=float(avg_win),
            avg_loss=float(avg_loss),
            profit_factor=float(profit_factor),
            max_consecutive_wins=0,
            max_consecutive_losses=0,
            avg_holding_days=float(np.mean(holding_days)) if holding_days else 0.0,
            max_positions=self.max_positions,
            equity_curve=self.equity_curve,
            drawdown_curve=drawdown_curve,
            trade_list=trade_list,
            position_history=[],
        )
