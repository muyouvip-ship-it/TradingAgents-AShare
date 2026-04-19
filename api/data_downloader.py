"""
真实数据下载模块 - 使用AKShare下载股票数据
"""

import akshare as ak
import pandas as pd
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy import text
import asyncio
import logging

logger = logging.getLogger(__name__)


class DataDownloader:
    """数据下载器"""
    
    def __init__(self, db_session):
        self.db = db_session
    
    def check_existing_data(self, symbol: str, data_type: str, start_date: date, end_date: date) -> Dict[str, Any]:
        """检查数据库中已有的数据范围"""
        try:
            if data_type == 'daily_kline':
                # 检查股票日K线数据
                query = text("""
                    SELECT MIN(trade_date) as min_date, MAX(trade_date) as max_date, COUNT(*) as count
                    FROM stock_daily_kline 
                    WHERE symbol = :symbol 
                      AND trade_date >= :start_date 
                      AND trade_date <= :end_date
                """)
            elif data_type == 'index_data':
                # 检查指数数据
                query = text("""
                    SELECT MIN(trade_date) as min_date, MAX(trade_date) as max_date, COUNT(*) as count
                    FROM index_daily_data 
                    WHERE symbol = :symbol 
                      AND trade_date >= :start_date 
                      AND trade_date <= :end_date
                """)
            else:
                return {"exists": False, "complete": False}
            
            result = self.db.execute(query, {
                "symbol": symbol,
                "start_date": start_date,
                "end_date": end_date
            })
            row = result.fetchone()
            
            if row and row.count > 0:
                # 计算日期范围内的预期交易日数量（大约）
                expected_days = (end_date - start_date).days
                # 粗略估算：每周5个交易日
                expected_trading_days = int(expected_days * 5 / 7)
                
                # 如果已有数据 >= 预期交易日的80%，认为数据完整
                is_complete = row.count >= expected_trading_days * 0.8
                
                return {
                    "exists": True,
                    "complete": is_complete,
                    "min_date": row.min_date,
                    "max_date": row.max_date,
                    "count": row.count
                }
            
            return {"exists": False, "complete": False}
            
        except Exception as e:
            logger.error(f"检查已有数据失败 {symbol}: {e}")
            return {"exists": False, "complete": False}

        
    async def download_daily_kline(self, symbol: str, start_date: date, end_date: date, force: bool = False) -> Dict[str, Any]:
        """下载股票日K线数据 - 使用新浪接口"""
        try:
            # 检查是否已有数据
            if not force:
                existing = self.check_existing_data(symbol, 'daily_kline', start_date, end_date)
                if existing['complete']:
                    logger.info(f"股票 {symbol} 数据已存在且完整，跳过下载")
                    return {"success": True, "records": existing['count'], "skipped": True}
                elif existing['exists']:
                    logger.info(f"股票 {symbol} 部分数据已存在，将增量更新")
            
            logger.info(f"开始下载 {symbol} 日K线数据: {start_date} ~ {end_date}")
            
            # 使用新浪接口（更稳定）
            # 新浪接口没有日期参数，会返回所有历史数据
            df = ak.stock_zh_a_daily(symbol=f"sh{symbol}" if symbol.startswith('6') else f"sz{symbol}", adjust="qfq")
            
            if df.empty:
                logger.warning(f"股票 {symbol} 没有数据")
                return {"success": False, "records": 0, "error": "无数据"}
            
            # 筛选日期范围
            df['date'] = pd.to_datetime(df['date'])
            start_datetime = pd.to_datetime(start_date)
            end_datetime = pd.to_datetime(end_date)
            df_filtered = df[(df['date'] >= start_datetime) & (df['date'] <= end_datetime)]
            
            if df_filtered.empty:
                logger.warning(f"股票 {symbol} 在指定日期范围内没有数据")
                return {"success": False, "records": 0, "error": "日期范围内无数据"}
            
            # 数据清洗和入库
            records_inserted = 0
            for _, row in df_filtered.iterrows():
                try:
                    insert_query = text("""
                        INSERT INTO stock_daily_kline 
                        (symbol, trade_date, open, high, low, close, volume, amount, turnover_rate)
                        VALUES (:symbol, :trade_date, :open, :high, :low, :close, :volume, :amount, :turnover_rate)
                        ON CONFLICT (symbol, trade_date) DO UPDATE SET
                            open = EXCLUDED.open,
                            high = EXCLUDED.high,
                            low = EXCLUDED.low,
                            close = EXCLUDED.close,
                            volume = EXCLUDED.volume,
                            amount = EXCLUDED.amount,
                            turnover_rate = EXCLUDED.turnover_rate,
                            updated_at = NOW()
                    """)
                    
                    self.db.execute(insert_query, {
                        "symbol": symbol,
                        "trade_date": row['date'].date(),
                        "open": float(row['open']) if pd.notna(row['open']) else None,
                        "high": float(row['high']) if pd.notna(row['high']) else None,
                        "low": float(row['low']) if pd.notna(row['low']) else None,
                        "close": float(row['close']) if pd.notna(row['close']) else None,
                        "volume": int(row['volume']) if pd.notna(row['volume']) else None,
                        "amount": float(row['amount']) if pd.notna(row['amount']) else None,
                        "turnover_rate": float(row['turnover']) if pd.notna(row['turnover']) else None
                    })
                    records_inserted += 1
                except Exception as e:
                    logger.error(f"插入数据失败 {symbol} {row['date']}: {e}")
                    continue
            
            self.db.commit()
            logger.info(f"成功下载 {symbol} 日K线数据 {records_inserted} 条")
            return {"success": True, "records": records_inserted}
            
        except Exception as e:
            logger.error(f"下载 {symbol} 日K线数据失败: {e}")
            return {"success": False, "records": 0, "error": str(e)}
    
    async def download_index_data(self, symbol: str, start_date: date, end_date: date) -> Dict[str, Any]:
        """下载指数数据 - 使用新浪接口"""
        try:
            logger.info(f"开始下载指数 {symbol} 数据: {start_date} ~ {end_date}")
            
            # 使用新浪接口
            df = ak.stock_zh_index_daily(symbol=f"sh{symbol}" if symbol.startswith('000') or symbol.startswith('9') else f"sz{symbol}")
            
            if df.empty:
                logger.warning(f"指数 {symbol} 没有数据")
                return {"success": False, "records": 0, "error": "无数据"}
            
            # 筛选日期范围
            df['date'] = pd.to_datetime(df['date'])
            start_datetime = pd.to_datetime(start_date)
            end_datetime = pd.to_datetime(end_date)
            df_filtered = df[(df['date'] >= start_datetime) & (df['date'] <= end_datetime)]
            
            if df_filtered.empty:
                logger.warning(f"指数 {symbol} 在指定日期范围内没有数据")
                return {"success": False, "records": 0, "error": "日期范围内无数据"}
            
            # 数据入库
            records_inserted = 0
            for _, row in df_filtered.iterrows():
                try:
                    insert_query = text("""
                        INSERT INTO index_daily_data 
                        (symbol, trade_date, open, high, low, close, volume, amount)
                        VALUES (:symbol, :trade_date, :open, :high, :low, :close, :volume, :amount)
                        ON CONFLICT (symbol, trade_date) DO UPDATE SET
                            open = EXCLUDED.open,
                            high = EXCLUDED.high,
                            low = EXCLUDED.low,
                            close = EXCLUDED.close,
                            volume = EXCLUDED.volume,
                            amount = EXCLUDED.amount,
                            updated_at = NOW()
                    """)
                    
                    self.db.execute(insert_query, {
                        "symbol": symbol,
                        "trade_date": row['date'].date(),
                        "open": float(row['open']) if pd.notna(row['open']) else None,
                        "high": float(row['high']) if pd.notna(row['high']) else None,
                        "low": float(row['low']) if pd.notna(row['low']) else None,
                        "close": float(row['close']) if pd.notna(row['close']) else None,
                        "volume": int(row['volume']) if pd.notna(row['volume']) else None,
                        "amount": float(row['amount']) if pd.notna(row['amount']) else None
                    })
                    records_inserted += 1
                except Exception as e:
                    logger.error(f"插入指数数据失败 {symbol} {row['date']}: {e}")
                    continue
            
            self.db.commit()
            logger.info(f"成功下载指数 {symbol} 数据 {records_inserted} 条")
            return {"success": True, "records": records_inserted}
            
        except Exception as e:
            logger.error(f"下载指数 {symbol} 数据失败: {e}")
            return {"success": False, "records": 0, "error": str(e)}
    
    def get_all_stock_symbols(self) -> List[str]:
        """获取所有A股股票代码"""
        try:
            # 使用AKShare获取A股股票列表
            df = ak.stock_info_a_code_name()
            # 只返回A股代码（排除北交所等）
            symbols = [code for code in df['code'].tolist() if code.startswith(('0', '3', '6'))]
            logger.info(f"获取到 {len(symbols)} 只A股股票")
            return symbols
        except Exception as e:
            logger.error(f"获取股票列表失败: {e}")
            return []
    
    def get_main_index_symbols(self) -> List[str]:
        """获取主要指数代码"""
        return ['000001', '399001', '000300', '000016', '000905', '399006']
        # 上证指数、深证成指、沪深300、上证50、中证500、创业板指
    
    async def download_minute_kline(self, symbol: str, start_date: date, end_date: date, force: bool = False) -> Dict[str, Any]:
        """下载股票1分钟K线数据 - 使用AKShare东方财富接口"""
        import time
        import random
        
        # 添加请求延时，避免API限流
        await asyncio.sleep(random.uniform(0.5, 1.5))
        
        try:
            logger.info(f"开始下载 {symbol} 1分钟K线数据: {start_date} ~ {end_date}")

            # AKShare的分钟K线接口限制：只能获取最近30天的数据
            days_diff = (end_date - start_date).days
            if days_diff > 30:
                logger.warning(f"股票 {symbol} 分钟K线数据范围超过30天，自动调整为最近30天")
                end_date = date.today()
                start_date = end_date - timedelta(days=30)

            # 使用东方财富分钟K线接口（带重试机制）
            max_retries = 3
            df = None
            for attempt in range(max_retries):
                try:
                    df = ak.stock_zh_a_hist_min_em(symbol=symbol, period='1', adjust='qfq')
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 2  # 递增等待时间：2s, 4s, 6s
                        logger.warning(f"股票 {symbol} 第{attempt+1}次请求失败，{wait_time}秒后重试: {e}")
                        await asyncio.sleep(wait_time)
                    else:
                        raise e

            if df.empty:
                logger.warning(f"股票 {symbol} 没有1分钟K线数据")
                return {"success": False, "records": 0, "error": "无数据"}

            # 处理时间格式
            df['时间'] = pd.to_datetime(df['时间'])

            # 筛选日期范围
            start_datetime = pd.to_datetime(start_date)
            end_datetime = pd.to_datetime(end_date) + timedelta(days=1)
            df_filtered = df[(df['时间'] >= start_datetime) & (df['时间'] < end_datetime)]

            if df_filtered.empty:
                logger.warning(f"股票 {symbol} 在指定日期范围内没有1分钟K线数据")
                return {"success": False, "records": 0, "error": "日期范围内无数据"}

            # 批量数据准备
            records_data = []
            for _, row in df_filtered.iterrows():
                try:
                    records_data.append({
                        "symbol": symbol,
                        "trade_time": row['时间'],
                        "open": float(row['开盘']) if pd.notna(row['开盘']) else None,
                        "high": float(row['最高']) if pd.notna(row['最高']) else None,
                        "low": float(row['最低']) if pd.notna(row['最低']) else None,
                        "close": float(row['收盘']) if pd.notna(row['收盘']) else None,
                        "volume": int(row['成交量']) if pd.notna(row['成交量']) else None,
                        "amount": float(row['成交额']) if pd.notna(row['成交额']) else None
                    })
                except Exception as e:
                    logger.error(f"准备1分钟K线数据失败 {symbol} {row['时间']}: {e}")
                    continue

            # 批量插入
            if records_data:
                values_list = []
                for rec in records_data:
                    values_list.append(f"('{rec['symbol']}', '{rec['trade_time']}', {rec['open']}, {rec['high']}, {rec['low']}, {rec['close']}, {rec['volume']}, {rec['amount']})")
                
                insert_sql = f"""
                    INSERT INTO stock_minute_kline
                    (symbol, trade_time, open, high, low, close, volume, amount)
                    VALUES {', '.join(values_list)}
                    ON CONFLICT (symbol, trade_time) DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        amount = EXCLUDED.amount,
                        created_at = NOW()
                """
                
                try:
                    self.db.execute(text(insert_sql))
                    self.db.commit()
                    logger.info(f"成功下载 {symbol} 1分钟K线数据 {len(records_data)} 条")
                    return {"success": True, "records": len(records_data)}
                except Exception as e:
                    logger.error(f"批量插入1分钟K线数据失败 {symbol}: {e}")
                    # 回滚并尝试逐条插入
                    self.db.rollback()
                    
                    records_inserted = 0
                    for rec in records_data:
                        try:
                            insert_query = text("""
                                INSERT INTO stock_minute_kline
                                (symbol, trade_time, open, high, low, close, volume, amount)
                                VALUES (:symbol, :trade_time, :open, :high, :low, :close, :volume, :amount)
                                ON CONFLICT (symbol, trade_time) DO UPDATE SET
                                    open = EXCLUDED.open,
                                    high = EXCLUDED.high,
                                    low = EXCLUDED.low,
                                    close = EXCLUDED.close,
                                    volume = EXCLUDED.volume,
                                    amount = EXCLUDED.amount,
                                    created_at = NOW()
                            """)
                            self.db.execute(insert_query, rec)
                            records_inserted += 1
                        except Exception as e2:
                            logger.error(f"逐条插入失败 {symbol} {rec['trade_time']}: {e2}")
                            continue
                    
                    self.db.commit()
                    logger.info(f"成功下载 {symbol} 1分钟K线数据 {records_inserted} 条（逐条插入）")
                    return {"success": True, "records": records_inserted}
            else:
                return {"success": False, "records": 0, "error": "无有效数据"}

        except Exception as e:
            logger.error(f"下载 {symbol} 1分钟K线数据失败: {e}")
            return {"success": False, "records": 0, "error": str(e)}
