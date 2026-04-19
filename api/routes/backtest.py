"""
策略回测API路由

提供策略回测相关的REST API。
"""

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime
import logging

from tradingagents.backtest.engine import BacktestEngine
from tradingagents.strategies.manager import get_strategy_manager
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False

logger = logging.getLogger(__name__)


def get_stock_data(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    获取股票数据（优先使用AKShare真实数据，失败时使用模拟数据）
    
    Args:
        symbol: 股票代码（如 000001 或 000001.SZ）
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
    
    Returns:
        DataFrame包含 date, open, high, low, close, volume 等列
    """
    # 处理股票代码格式（去掉后缀）
    stock_code = symbol.split('.')[0]
    
    # 尝试使用AKShare获取真实数据
    if AKSHARE_AVAILABLE:
        try:
            logger.info(f"Fetching real stock data for {stock_code} via AKShare...")
            
            # 使用AKShare获取A股日线数据
            df = ak.stock_zh_a_hist(
                symbol=stock_code,
                period="daily",
                start_date=start_date.replace('-', ''),
                end_date=end_date.replace('-', ''),
                adjust="qfq"  # 前复权
            )
            
            if df is not None and not df.empty:
                # 重命名列
                df = df.rename(columns={
                    '日期': 'date',
                    '开盘': 'open',
                    '最高': 'high',
                    '最低': 'low',
                    '收盘': 'close',
                    '成交量': 'volume',
                })
                
                # 转换日期格式
                df['date'] = pd.to_datetime(df['date'])
                
                # 添加股票代码
                df['symbol'] = symbol
                
                # 选择需要的列
                df = df[['date', 'open', 'high', 'low', 'close', 'volume', 'symbol']]
                
                logger.info(f"Successfully fetched {len(df)} records from AKShare")
                return df
        except Exception as e:
            logger.warning(f"Failed to fetch data from AKShare: {e}, falling back to simulated data")
    
    # 使用模拟数据作为备选
    logger.info("Using simulated stock data")
    return generate_simulated_data(symbol, start_date, end_date)


def generate_simulated_data(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    生成模拟股票数据（用于测试或数据源不可用时）
    """
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    
    dates = []
    current = start
    while current <= end:
        # 只生成工作日的数据
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)
    
    # 生成模拟价格数据（随机游走）
    np.random.seed(42)
    base_price = 50.0
    prices = [base_price]
    for i in range(len(dates) - 1):
        change = np.random.normal(0, 0.02)
        new_price = prices[-1] * (1 + change)
        prices.append(new_price)
    
    # 创建DataFrame
    data = pd.DataFrame({
        'date': dates,
        'open': prices,
        'high': [p * 1.02 for p in prices],
        'low': [p * 0.98 for p in prices],
        'close': prices,
        'volume': [1000000] * len(dates),
        'symbol': [symbol] * len(dates),
    })
    
    return data


# Pydantic 模型定义
class StrategyBacktestRequest(BaseModel):
    """策略回测请求"""
    strategy_id: str = Field(..., description="策略ID")
    symbol: str = Field(..., description="股票代码")
    start_date: str = Field(..., description="开始日期 (YYYY-MM-DD)")
    end_date: str = Field(..., description="结束日期 (YYYY-MM-DD)")
    initial_capital: float = Field(1000000.0, description="初始资金")


class BacktestMetricsResponse(BaseModel):
    """回测指标响应"""
    total_return: float
    annual_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    volatility: float


class BacktestResultResponse(BaseModel):
    """回测结果响应"""
    strategy_id: str
    strategy_name: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    metrics: BacktestMetricsResponse
    total_trades: int
    trades: list
    portfolio_values: list


# 创建路由器
router = APIRouter(prefix="/v1/backtest", tags=["backtest"])


@router.post("/run", response_model=BacktestResultResponse)
async def run_strategy_backtest(request: StrategyBacktestRequest):
    """
    运行策略回测

    - **strategy_id**: 策略ID
    - **symbol**: 股票代码
    - **start_date**: 开始日期
    - **end_date**: 结束日期
    - **initial_capital**: 初始资金
    """
    try:
        # 验证策略是否存在
        strategy_manager = get_strategy_manager()
        strategy = strategy_manager.get_strategy(request.strategy_id)

        if not strategy:
            raise HTTPException(status_code=404, detail=f"Strategy not found: {request.strategy_id}")

        # 获取股票数据
        logger.info(f"Fetching stock data for {request.symbol}...")
        stock_data = get_stock_data(
            symbol=request.symbol,
            start_date=request.start_date,
            end_date=request.end_date,
        )

        if stock_data.empty:
            raise HTTPException(status_code=400, detail="No stock data available for the given parameters")

        # 运行回测
        logger.info(f"Running backtest for strategy {request.strategy_id}...")
        engine = BacktestEngine(initial_capital=request.initial_capital)
        result = engine.run_backtest(
            strategy_id=request.strategy_id,
            data=stock_data,
            start_date=request.start_date,
            end_date=request.end_date,
        )

        # 返回结果
        return BacktestResultResponse(
            strategy_id=result['strategy_id'],
            strategy_name=result['strategy_name'],
            start_date=str(result['start_date']),
            end_date=str(result['end_date']),
            initial_capital=result['initial_capital'],
            final_capital=result['final_capital'],
            metrics=BacktestMetricsResponse(**result['metrics']),
            total_trades=result['total_trades'],
            trades=result['trades'][:100],  # 限制返回的交易记录数量
            portfolio_values=result['portfolio_values'][:500],  # 限制返回的组合价值数量
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Backtest failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Backtest failed: {str(e)}")
