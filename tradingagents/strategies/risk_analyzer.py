"""
风险分析器

提供VaR计算、压力测试、蒙特卡洛模拟等风险分析功能。
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import pandas as pd
import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)


class RiskAnalyzer:
    """风险分析器"""
    
    def __init__(self):
        pass
    
    def calculate_var(
        self,
        returns: pd.Series,
        confidence_level: float = 0.95,
        method: str = "historical",
        holding_period: int = 1,
    ) -> Dict:
        """
        计算VaR（风险价值）
        
        Args:
            returns: 收益率序列
            confidence_level: 置信水平（0.95表示95%）
            method: 计算方法（historical, parametric, monte_carlo）
            holding_period: 持有期（天数）
        
        Returns:
            VaR计算结果
        """
        if method == "historical":
            var = self._historical_var(returns, confidence_level)
        elif method == "parametric":
            var = self._parametric_var(returns, confidence_level)
        elif method == "monte_carlo":
            var = self._monte_carlo_var(returns, confidence_level)
        else:
            raise ValueError(f"Unknown method: {method}")
        
        # 调整持有期
        var_adjusted = var * np.sqrt(holding_period)
        
        return {
            "var": var_adjusted,
            "var_percentage": var_adjusted * 100,
            "confidence_level": confidence_level,
            "method": method,
            "holding_period": holding_period,
            "interpretation": f"在{confidence_level*100}%置信水平下，持有{holding_period}天的最大损失不超过{abs(var_adjusted)*100:.2f}%",
        }
    
    def _historical_var(self, returns: pd.Series, confidence_level: float) -> float:
        """历史模拟法计算VaR"""
        return returns.quantile(1 - confidence_level)
    
    def _parametric_var(self, returns: pd.Series, confidence_level: float) -> float:
        """参数法计算VaR（假设正态分布）"""
        mean = returns.mean()
        std = returns.std()
        z_score = stats.norm.ppf(1 - confidence_level)
        return mean + z_score * std
    
    def _monte_carlo_var(self, returns: pd.Series, confidence_level: float) -> float:
        """蒙特卡洛模拟法计算VaR"""
        mean = returns.mean()
        std = returns.std()
        
        # 生成10000个随机收益
        np.random.seed(42)
        simulated_returns = np.random.normal(mean, std, 10000)
        
        return np.percentile(simulated_returns, (1 - confidence_level) * 100)
    
    def stress_test(
        self,
        portfolio_values: pd.DataFrame,
        scenarios: Optional[List[Dict]] = None,
    ) -> Dict:
        """
        压力测试
        
        Args:
            portfolio_values: 组合价值数据
            scenarios: 压力场景列表，格式：
                [
                    {"name": "市场崩盘", "price_change": -0.20},
                    {"name": "大幅上涨", "price_change": 0.15},
                ]
        
        Returns:
            压力测试结果
        """
        if scenarios is None:
            scenarios = [
                {"name": "轻度下跌", "price_change": -0.05},
                {"name": "中度下跌", "price_change": -0.10},
                {"name": "严重下跌", "price_change": -0.20},
                {"name": "市场崩盘", "price_change": -0.30},
                {"name": "轻度上涨", "price_change": 0.05},
                {"name": "中度上涨", "price_change": 0.10},
                {"name": "大幅上涨", "price_change": 0.20},
            ]
        
        current_value = portfolio_values['value'].iloc[-1]
        results = []
        
        for scenario in scenarios:
            price_change = scenario['price_change']
            new_value = current_value * (1 + price_change)
            pnl = new_value - current_value
            
            results.append({
                "scenario": scenario['name'],
                "price_change": price_change,
                "new_portfolio_value": new_value,
                "pnl": pnl,
                "pnl_percentage": price_change * 100,
            })
        
        return {
            "current_portfolio_value": current_value,
            "scenarios": results,
        }
    
    def monte_carlo_simulation(
        self,
        returns: pd.Series,
        initial_value: float,
        days: int = 252,
        simulations: int = 1000,
    ) -> Dict:
        """
        蒙特卡洛模拟
        
        Args:
            returns: 历史收益率序列
            initial_value: 初始组合价值
            days: 模拟天数
            simulations: 模拟次数
        
        Returns:
            模拟结果
        """
        # 计算收益率统计量
        mean_return = returns.mean()
        std_return = returns.std()
        
        # 模拟路径
        np.random.seed(42)
        paths = np.zeros((simulations, days + 1))
        paths[:, 0] = initial_value
        
        for i in range(simulations):
            daily_returns = np.random.normal(mean_return, std_return, days)
            
            for j in range(days):
                paths[i, j + 1] = paths[i, j] * (1 + daily_returns[j])
        
        # 计算统计量
        final_values = paths[:, -1]
        
        return {
            "initial_value": initial_value,
            "final_values_mean": np.mean(final_values),
            "final_values_std": np.std(final_values),
            "final_values_min": np.min(final_values),
            "final_values_max": np.max(final_values),
            "percentile_5": np.percentile(final_values, 5),
            "percentile_25": np.percentile(final_values, 25),
            "percentile_50": np.percentile(final_values, 50),
            "percentile_75": np.percentile(final_values, 75),
            "percentile_95": np.percentile(final_values, 95),
            "probability_of_loss": np.sum(final_values < initial_value) / simulations,
            "expected_return": (np.mean(final_values) - initial_value) / initial_value,
        }
    
    def calculate_risk_metrics(
        self,
        portfolio_values: pd.DataFrame,
    ) -> Dict:
        """
        计算完整的风险指标
        
        Args:
            portfolio_values: 组合价值数据
        
        Returns:
            风险指标字典
        """
        # 计算收益率
        returns = portfolio_values['value'].pct_change().dropna()
        
        # VaR
        var_95 = self.calculate_var(returns, 0.95, "historical")
        var_99 = self.calculate_var(returns, 0.99, "historical")
        
        # CVaR (条件VaR，Expected Shortfall)
        cvar_95 = returns[returns <= returns.quantile(0.05)].mean()
        
        # 最大回撤
        cumulative = (1 + returns).cumprod()
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        max_drawdown = drawdown.min()
        
        # 压力测试
        stress_results = self.stress_test(portfolio_values)
        
        # 蒙特卡洛模拟
        mc_results = self.monte_carlo_simulation(returns, portfolio_values['value'].iloc[0])
        
        return {
            "var_95": var_95,
            "var_99": var_99,
            "cvar_95": cvar_95,
            "max_drawdown": max_drawdown,
            "stress_test": stress_results,
            "monte_carlo": mc_results,
            "summary": {
                "volatility": returns.std() * np.sqrt(252),  # 年化波动率
                "skewness": returns.skew(),
                "kurtosis": returns.kurtosis(),
                "var_ratio": var_99['var'] / var_95['var'],  # VaR比率
            }
        }


# 全局风险分析器实例
_analyzer: Optional[RiskAnalyzer] = None


def get_risk_analyzer() -> RiskAnalyzer:
    """获取全局风险分析器实例"""
    global _analyzer
    if _analyzer is None:
        _analyzer = RiskAnalyzer()
    return _analyzer
