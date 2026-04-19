#!/usr/bin/env python3
"""
简化版回测测试
直接测试回测引擎
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
import numpy as np
from datetime import datetime
from tradingagents.backtest.engine_v2 import BacktestEngine

print("=" * 70)
print("  回测引擎测试")
print("=" * 70)

# 生成模拟数据
print("\n1. 生成模拟数据...")
start_date = datetime(2025, 1, 1)
end_date = datetime(2026, 4, 18)
dates = pd.date_range(start_date, end_date, freq='B')
stocks = ['000001.SZ', '000002.SZ', '000333.SZ']

data_list = []
for stock in stocks:
    base_price = np.random.uniform(10, 100)
    prev_close = base_price
    
    for i, date in enumerate(dates):
        if i > 0:
            close = prev_close * (1 + np.random.uniform(-0.03, 0.03))
        else:
            close = base_price
        
        prev_close = close
        
        data_list.append({
            'date': date,
            'symbol': stock,
            'open': close * (1 + np.random.uniform(-0.01, 0.01)),
            'high': close * (1 + np.random.uniform(0, 0.02)),
            'low': close * (1 - np.random.uniform(0, 0.02)),
            'close': close,
            'volume': np.random.randint(1000000, 10000000),
        })

data = pd.DataFrame(data_list)
print(f"   生成数据: {len(data)} 条")
print(f"   时间范围: {start_date.date()} 至 {end_date.date()}")
print(f"   股票数量: {len(stocks)}")

# 创建回测引擎
print("\n2. 创建回测引擎...")
engine = BacktestEngine(
    initial_capital=1000000.0,
    commission_rate=0.0003,
    slippage_rate=0.001,
    stamp_duty=0.001,
)
print("   初始资金: ¥1,000,000")

# 定义策略
strategy = {
    'id': 'test-001',
    'name': '测试策略',
    'indicators': [],
    'entry_rules': [
        {'name': '随机入场', 'condition': 'random < 0.1', 'parameters': {}}
    ],
    'exit_rules': [],
    'risk_rules': {
        'stop_loss': 0.05,
        'take_profit': 0.15,
        'max_positions': 10,
    }
}

# 运行回测
print("\n3. 运行回测...")
try:
    result = engine.run_backtest(
        strategy=strategy,
        data=data,
        start_date=start_date,
        end_date=end_date,
        backtest_mode='indicator_driven',
    )
    
    print("\n✅ 回测完成!")
    print("=" * 70)
    print(f"策略名称: {result.strategy_name}")
    print(f"初始资金: ¥{result.initial_capital:,.2f}")
    print(f"最终资金: ¥{result.final_capital:,.2f}")
    print("=" * 70)
    print("\n📊 绩效指标:")
    print(f"  总收益率:     {result.total_return:.2%}")
    print(f"  年化收益率:   {result.annual_return:.2%}")
    print(f"  夏普比率:     {result.sharpe_ratio:.2f}")
    print(f"  最大回撤:     {result.max_drawdown:.2%}")
    print("=" * 70)
    print("\n📈 交易统计:")
    print(f"  总交易次数:   {result.total_trades}")
    print(f"  盈利次数:     {result.winning_trades}")
    print(f"  亏损次数:     {result.losing_trades}")
    print(f"  胜率:         {result.win_rate:.2%}")
    print("=" * 70)
    
except Exception as e:
    print(f"\n❌ 回测失败: {e}")
    import traceback
    traceback.print_exc()
