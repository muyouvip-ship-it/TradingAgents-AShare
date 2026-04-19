"""
策略优化器

提供参数优化、网格搜索、多策略组合等功能。
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import pandas as pd
import numpy as np
from itertools import product
import asyncio

from tradingagents.strategies.manager import get_strategy_manager
from tradingagents.backtest.engine import BacktestEngine

logger = logging.getLogger(__name__)


class StrategyOptimizer:
    """策略优化器"""
    
    def __init__(self):
        self.strategy_manager = get_strategy_manager()
        self.optimization_history: Dict[str, List[Dict]] = {}
    
    def grid_search(
        self,
        strategy_id: str,
        symbol: str,
        start_date: str,
        end_date: str,
        param_grid: Dict[str, List[Any]],
        initial_capital: float = 1000000.0,
        metric: str = "total_return",
        top_n: int = 10,
    ) -> List[Dict]:
        """
        参数网格搜索
        
        Args:
            strategy_id: 策略ID
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            param_grid: 参数网格，如 {"fast_period": [5, 10, 15], "slow_period": [20, 30, 40]}
            initial_capital: 初始资金
            metric: 优化指标（total_return, sharpe_ratio, max_drawdown）
            top_n: 返回前N个最佳参数组合
        
        Returns:
            优化结果列表
        """
        logger.info(f"Starting grid search for strategy {strategy_id}")
        
        # 验证策略
        strategy = self.strategy_manager.get_strategy(strategy_id)
        if not strategy:
            raise ValueError(f"Strategy not found: {strategy_id}")
        
        # 生成参数组合
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        combinations = list(product(*param_values))
        
        logger.info(f"Testing {len(combinations)} parameter combinations")
        
        results = []
        
        # 测试每个参数组合
        for i, params in enumerate(combinations):
            param_dict = dict(zip(param_names, params))
            
            try:
                # 创建临时策略实例
                temp_strategy = strategy.__class__(parameters=param_dict)
                
                # 运行回测
                engine = BacktestEngine(initial_capital=initial_capital)
                result = engine.run_backtest(
                    strategy_id=f"{strategy_id}_temp_{i}",
                    data=None,  # 由引擎获取
                    start_date=start_date,
                    end_date=end_date,
                    strategy_instance=temp_strategy,
                    symbol=symbol,
                )
                
                # 记录结果
                result_entry = {
                    "params": param_dict,
                    "metrics": result["metrics"],
                    "final_capital": result["final_capital"],
                    "total_trades": result["total_trades"],
                }
                results.append(result_entry)
                
            except Exception as e:
                logger.warning(f"Failed to test params {param_dict}: {e}")
                continue
        
        # 排序结果
        if metric == "max_drawdown":
            # 最大回撤越小越好
            results.sort(key=lambda x: x["metrics"][metric])
        else:
            # 其他指标越大越好
            results.sort(key=lambda x: x["metrics"][metric], reverse=True)
        
        # 保存历史
        if strategy_id not in self.optimization_history:
            self.optimization_history[strategy_id] = []
        self.optimization_history[strategy_id].append({
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "param_grid": param_grid,
            "total_combinations": len(combinations),
            "successful_tests": len(results),
            "top_results": results[:top_n],
        })
        
        logger.info(f"Grid search completed. Top {min(top_n, len(results))} results returned.")
        
        return results[:top_n]
    
    def compare_strategies(
        self,
        strategy_ids: List[str],
        symbol: str,
        start_date: str,
        end_date: str,
        initial_capital: float = 1000000.0,
    ) -> pd.DataFrame:
        """
        策略对比分析
        
        Args:
            strategy_ids: 策略ID列表
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            initial_capital: 初始资金
        
        Returns:
            对比结果DataFrame
        """
        logger.info(f"Comparing strategies: {strategy_ids}")
        
        results = []
        
        for strategy_id in strategy_ids:
            try:
                strategy = self.strategy_manager.get_strategy(strategy_id)
                if not strategy:
                    logger.warning(f"Strategy not found: {strategy_id}")
                    continue
                
                # 运行回测
                engine = BacktestEngine(initial_capital=initial_capital)
                result = engine.run_backtest(
                    strategy_id=strategy_id,
                    data=None,
                    start_date=start_date,
                    end_date=end_date,
                    strategy_instance=strategy,
                    symbol=symbol,
                )
                
                results.append({
                    "strategy_id": strategy_id,
                    "strategy_name": strategy.name,
                    "total_return": result["metrics"]["total_return"],
                    "annual_return": result["metrics"]["annual_return"],
                    "sharpe_ratio": result["metrics"]["sharpe_ratio"],
                    "max_drawdown": result["metrics"]["max_drawdown"],
                    "win_rate": result["metrics"]["win_rate"],
                    "total_trades": result["total_trades"],
                    "final_capital": result["final_capital"],
                })
                
            except Exception as e:
                logger.error(f"Error testing strategy {strategy_id}: {e}")
                continue
        
        # 创建对比DataFrame
        df = pd.DataFrame(results)
        
        logger.info(f"Comparison completed for {len(results)} strategies")
        
        return df
    
    def multi_strategy_portfolio(
        self,
        strategy_weights: Dict[str, float],
        symbol: str,
        start_date: str,
        end_date: str,
        initial_capital: float = 1000000.0,
    ) -> Dict:
        """
        多策略组合回测
        
        Args:
            strategy_weights: 策略权重映射，如 {"ma_cross": 0.4, "macd": 0.6}
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            initial_capital: 初始资金
        
        Returns:
            组合回测结果
        """
        logger.info(f"Running multi-strategy portfolio with weights: {strategy_weights}")
        
        # 验证权重
        total_weight = sum(strategy_weights.values())
        if abs(total_weight - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0, got {total_weight}")
        
        # 对每个策略单独回测
        strategy_results = {}
        
        for strategy_id, weight in strategy_weights.items():
            strategy = self.strategy_manager.get_strategy(strategy_id)
            if not strategy:
                raise ValueError(f"Strategy not found: {strategy_id}")
            
            # 运行回测
            capital = initial_capital * weight
            engine = BacktestEngine(initial_capital=capital)
            result = engine.run_backtest(
                strategy_id=strategy_id,
                data=None,
                start_date=start_date,
                end_date=end_date,
                strategy_instance=strategy,
                symbol=symbol,
            )
            
            strategy_results[strategy_id] = {
                "weight": weight,
                "result": result,
            }
        
        # 组合结果
        portfolio_metrics = self._calculate_portfolio_metrics(strategy_results, initial_capital)
        
        logger.info(f"Portfolio backtest completed. Total return: {portfolio_metrics['total_return']:.2%}")
        
        return {
            "strategy_results": strategy_results,
            "portfolio_metrics": portfolio_metrics,
        }
    
    def _calculate_portfolio_metrics(
        self,
        strategy_results: Dict,
        initial_capital: float,
    ) -> Dict:
        """计算组合指标"""
        total_final_capital = sum(
            sr["result"]["final_capital"]
            for sr in strategy_results.values()
        )
        
        total_return = (total_final_capital - initial_capital) / initial_capital
        
        # 简化计算（实际应该考虑相关性）
        weighted_sharpe = sum(
            sr["weight"] * sr["result"]["metrics"]["sharpe_ratio"]
            for sr in strategy_results.values()
        )
        
        weighted_max_drawdown = max(
            sr["result"]["metrics"]["max_drawdown"]
            for sr in strategy_results.values()
        )
        
        return {
            "initial_capital": initial_capital,
            "final_capital": total_final_capital,
            "total_return": total_return,
            "sharpe_ratio": weighted_sharpe,
            "max_drawdown": weighted_max_drawdown,
        }


# 全局优化器实例
_optimizer: Optional[StrategyOptimizer] = None


def get_optimizer() -> StrategyOptimizer:
    """获取全局优化器实例"""
    global _optimizer
    if _optimizer is None:
        _optimizer = StrategyOptimizer()
    return _optimizer
