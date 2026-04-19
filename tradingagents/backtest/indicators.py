"""
技术指标计算模块

提供各种技术指标的计算功能，用于回测引擎。
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class IndicatorCalculator:
    """技术指标计算器"""

    @staticmethod
    def calculate_macd(
        data: pd.DataFrame,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9
    ) -> pd.DataFrame:
        """计算MACD指标"""
        data = data.copy()
        ema_fast = data['close'].ewm(span=fast_period, adjust=False).mean()
        ema_slow = data['close'].ewm(span=slow_period, adjust=False).mean()
        data['macd'] = ema_fast - ema_slow
        data['macd_signal'] = data['macd'].ewm(span=signal_period, adjust=False).mean()
        data['macd_histogram'] = data['macd'] - data['macd_signal']
        return data

    @staticmethod
    def calculate_ma(
        data: pd.DataFrame,
        periods: List[int] = [5, 10, 20, 60]
    ) -> pd.DataFrame:
        """计算移动平均线"""
        data = data.copy()
        for period in periods:
            data[f'ma{period}'] = data['close'].rolling(window=period).mean()
        return data

    @staticmethod
    def calculate_volume_ma(
        data: pd.DataFrame,
        period: int = 20
    ) -> pd.DataFrame:
        """计算成交量移动平均"""
        data = data.copy()
        data['volume_ma'] = data['volume'].rolling(window=period).mean()
        return data

    @staticmethod
    def calculate_rsi(
        data: pd.DataFrame,
        period: int = 14
    ) -> pd.DataFrame:
        """计算RSI指标"""
        data = data.copy()
        delta = data['close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        rs = avg_gain / avg_loss
        data['rsi'] = 100 - (100 / (1 + rs))
        return data

    @staticmethod
    def calculate_bollinger_bands(
        data: pd.DataFrame,
        period: int = 20,
        std_dev: float = 2.0
    ) -> pd.DataFrame:
        """计算布林带"""
        data = data.copy()
        data['bb_middle'] = data['close'].rolling(window=period).mean()
        data['bb_std'] = data['close'].rolling(window=period).std()
        data['bb_upper'] = data['bb_middle'] + std_dev * data['bb_std']
        data['bb_lower'] = data['bb_middle'] - std_dev * data['bb_std']
        data['bb_width'] = (data['bb_upper'] - data['bb_lower']) / data['bb_middle']
        return data

    @staticmethod
    def calculate_atr(
        data: pd.DataFrame,
        period: int = 14
    ) -> pd.DataFrame:
        """计算ATR（平均真实波幅）"""
        data = data.copy()
        high_low = data['high'] - data['low']
        high_close = abs(data['high'] - data['close'].shift())
        low_close = abs(data['low'] - data['close'].shift())
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        data['atr'] = true_range.rolling(window=period).mean()
        return data

    @staticmethod
    def _calculate_all_indicators_single_symbol(
        data: pd.DataFrame,
        strategy_indicators: List[Dict] = None
    ) -> pd.DataFrame:
        """对单个 symbol 计算所有指标，避免多股票串值污染。"""
        data = data.copy()
        if 'date' in data.columns:
            data['date'] = pd.to_datetime(data['date'])
            data = data.sort_values('date').reset_index(drop=True)

        # 默认计算常用指标
        data = IndicatorCalculator.calculate_macd(data)
        data = IndicatorCalculator.calculate_ma(data, periods=[5, 10, 20, 60])
        data = IndicatorCalculator.calculate_volume_ma(data)
        data = IndicatorCalculator.calculate_rsi(data)
        data = IndicatorCalculator.calculate_bollinger_bands(data)
        data = IndicatorCalculator.calculate_atr(data)

        # 如果策略指定了指标配置，按配置重算/补算
        if strategy_indicators:
            for indicator_config in strategy_indicators:
                indicator_name = indicator_config.get('name', '').upper()
                params = indicator_config.get('parameters', {})

                if indicator_name == 'MACD':
                    data = IndicatorCalculator.calculate_macd(
                        data,
                        fast_period=params.get('fast', params.get('fast_period', 12)),
                        slow_period=params.get('slow', params.get('slow_period', 26)),
                        signal_period=params.get('signal', params.get('signal_period', 9))
                    )
                elif indicator_name == 'MA':
                    if 'periods' in params:
                        periods = params.get('periods', [5, 10, 20, 60])
                    elif 'period' in params:
                        periods = sorted(set([5, 10, 20, 60, params['period']]))
                    else:
                        periods = [5, 10, 20, 60]
                    data = IndicatorCalculator.calculate_ma(data, periods=periods)
                elif indicator_name == 'VOL_MA':
                    data = IndicatorCalculator.calculate_volume_ma(
                        data,
                        period=params.get('period', 20)
                    )
                elif indicator_name == 'RSI':
                    data = IndicatorCalculator.calculate_rsi(
                        data,
                        period=params.get('period', 14)
                    )
                elif indicator_name in ('BOLLINGER_BANDS', 'BOLL', 'BB'):
                    data = IndicatorCalculator.calculate_bollinger_bands(
                        data,
                        period=params.get('period', 20),
                        std_dev=params.get('std_dev', 2.0)
                    )

        return data

    @staticmethod
    def calculate_all_indicators(
        data: pd.DataFrame,
        strategy_indicators: List[Dict] = None
    ) -> pd.DataFrame:
        """
        计算所有需要的指标。
        多股票时按 symbol 分组分别计算，避免指标串值污染。
        """
        data = data.copy()
        if 'date' in data.columns:
            data['date'] = pd.to_datetime(data['date'])

        if 'symbol' in data.columns:
            results = []
            for _, group in data.groupby('symbol', sort=False):
                group_result = IndicatorCalculator._calculate_all_indicators_single_symbol(
                    group,
                    strategy_indicators
                )
                results.append(group_result)
            data = pd.concat(results, ignore_index=True)
            data = data.sort_values(['date', 'symbol']).reset_index(drop=True)
        else:
            data = IndicatorCalculator._calculate_all_indicators_single_symbol(
                data,
                strategy_indicators
            )

        logger.info(f"Calculated all indicators for {len(data)} rows")
        return data


class ConditionParser:
    """条件解析器"""

    @staticmethod
    def parse_and_evaluate(
        condition: str,
        data: pd.DataFrame,
        position: Optional[Dict] = None
    ) -> bool:
        if not condition:
            return False

        try:
            normalized = condition.strip()
            if ConditionParser._evaluate_function_condition(normalized, data, position):
                return True
            condition_replaced = ConditionParser._replace_variables(normalized, data, position)
            result = ConditionParser._safe_evaluate(condition_replaced)
            return result
        except Exception as e:
            logger.warning(f"Condition evaluation failed: {condition}, error: {e}")
            return False

    @staticmethod
    def _evaluate_function_condition(
        condition: str,
        data: pd.DataFrame,
        position: Optional[Dict] = None
    ) -> bool:
        if isinstance(data, pd.DataFrame):
            if len(data) < 2:
                return False
            current = data.iloc[-1]
            previous = data.iloc[-2]
        else:
            return False

        def _val(row, expr: str) -> float:
            expr = expr.strip()
            if expr == 'entry_price' and position:
                return float(position.get('entry_price', 0))
            if expr == 'highest_price' and position:
                return float(position.get('highest_price', 0))
            try:
                return float(row.get(expr, expr))
            except Exception:
                return float(expr)

        import re
        m = re.fullmatch(r'(cross_above|cross_below)\(([^,]+),([^\)]+)\)', condition.replace(' ', ''))
        if not m:
            return False

        fn, left_expr, right_expr = m.group(1), m.group(2), m.group(3)
        prev_left = _val(previous, left_expr)
        prev_right = _val(previous, right_expr)
        curr_left = _val(current, left_expr)
        curr_right = _val(current, right_expr)

        if fn == 'cross_above':
            return prev_left <= prev_right and curr_left > curr_right
        if fn == 'cross_below':
            return prev_left >= prev_right and curr_left < curr_right
        return False

    @staticmethod
    def _replace_variables(
        condition: str,
        data: pd.DataFrame,
        position: Optional[Dict] = None
    ) -> str:
        if isinstance(data, pd.DataFrame):
            if len(data) < 1:
                return "False"
            current = data.iloc[-1]
            previous = data.iloc[-2] if len(data) >= 2 else current
        else:
            return "False"

        replacements = {
            'macd': str(current.get('macd', 0)),
            'signal': str(current.get('macd_signal', 0)),
            'macd_prev': str(previous.get('macd', 0)),
            'signal_prev': str(previous.get('macd_signal', 0)),
            'macd_histogram': str(current.get('macd_histogram', 0)),
            'ma5': str(current.get('ma5', 0)),
            'ma10': str(current.get('ma10', 0)),
            'ma20': str(current.get('ma20', 0)),
            'ma60': str(current.get('ma60', 0)),
            'close': str(current.get('close', 0)),
            'open': str(current.get('open', 0)),
            'high': str(current.get('high', 0)),
            'low': str(current.get('low', 0)),
            'volume': str(current.get('volume', 0)),
            'volume_ma': str(current.get('volume_ma', 0)),
            'rsi': str(current.get('rsi', 0)),
            'bb_upper': str(current.get('bb_upper', 0)),
            'bb_middle': str(current.get('bb_middle', 0)),
            'bb_lower': str(current.get('bb_lower', 0)),
            'atr': str(current.get('atr', 0)),
        }

        if position:
            replacements['entry_price'] = str(position.get('entry_price', 0))
            replacements['highest_price'] = str(position.get('highest_price', 0))

        result = condition
        for var, value in replacements.items():
            result = result.replace(var, value)
        return result

    @staticmethod
    def _safe_evaluate(condition: str) -> bool:
        condition = condition.replace(' AND ', ' and ')
        condition = condition.replace(' OR ', ' or ')

        if ' and ' in condition:
            parts = condition.split(' and ')
            return all(ConditionParser._evaluate_single(p.strip()) for p in parts)
        elif ' or ' in condition:
            parts = condition.split(' or ')
            return any(ConditionParser._evaluate_single(p.strip()) for p in parts)
        else:
            return ConditionParser._evaluate_single(condition)

    @staticmethod
    def _evaluate_single(condition: str) -> bool:
        operators = ['>=', '<=', '>', '<', '==', '!=']
        for op in operators:
            if op in condition:
                parts = condition.split(op)
                if len(parts) == 2:
                    try:
                        left = float(parts[0].strip())
                        right = float(parts[1].strip())
                        if op == '>=':
                            return left >= right
                        elif op == '<=':
                            return left <= right
                        elif op == '>':
                            return left > right
                        elif op == '<':
                            return left < right
                        elif op == '==':
                            return left == right
                        elif op == '!=':
                            return left != right
                    except ValueError:
                        return False
        return False
