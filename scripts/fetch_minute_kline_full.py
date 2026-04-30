#!/usr/bin/env python3
"""
全市场1分钟K线数据导入脚本

数据源：通达信 pytdx
- 最近5个月：用 get_security_bars 获取精确OHLCV
- 更早历史：用 get_history_minute_time_data 按日获取（price近似OHLC）

目标表：stock_minute_kline (PostgreSQL)
时间范围：2020-01-01 至今
"""

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("fetch_minute_kline_full.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# 数据库连接
DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://wolf:944c65ad900216867595733415329840@localhost/trading_agents",
)

# 通达信服务器列表
TDX_SERVERS = [
    ("180.153.18.170", 7709),
]

# 1分钟K线 category
CATEGORY_1MIN = 8

# 每天交易分钟数
MINUTES_PER_DAY = 240


def get_tdx_api():
    """获取通达信API连接"""
    from pytdx.hq import TdxHq_API

    for host, port in TDX_SERVERS:
        try:
            api = TdxHq_API()
            result = api.connect(host, port)
            if result:
                return api
        except Exception:
            continue
    raise RuntimeError("无法连接通达信服务器")


def get_all_a_stocks(api):
    """获取全市场A股列表 (market, code, name)"""
    stocks = []

    # 深市
    for start in range(0, 8000, 1000):
        data = api.get_security_list(0, start)
        if not data:
            break
        for s in data:
            code = s["code"]
            if code.startswith(("000", "001", "002", "003", "300", "301")):
                stocks.append((0, code, s["name"]))

    # 沪市
    for start in range(0, 28000, 1000):
        data = api.get_security_list(1, start)
        if not data:
            continue
        for s in data:
            code = s["code"]
            if code.startswith(("600", "601", "603", "605", "688", "689")):
                stocks.append((1, code, s["name"]))

    # 去重
    seen = set()
    unique = []
    for m, c, n in stocks:
        if c not in seen:
            seen.add(c)
            unique.append((m, c, n))

    return unique


def get_trading_days(start_date, end_date):
    """获取交易日列表（使用pytdx获取，跳过非交易日）"""
    api = get_tdx_api()
    trading_days = []

    current = start_date
    while current <= end_date:
        # 只检查工作日
        if current.weekday() < 5:
            date_int = int(current.strftime("%Y%m%d"))
            # 用平安银行(000001)检查是否有数据
            data = api.get_history_minute_time_data(0, "000001", date_int)
            if data and len(data) > 0:
                trading_days.append(date_int)
        current += timedelta(days=1)

    api.disconnect()
    return trading_days


def get_trading_days_fast(start_date, end_date):
    """快速获取交易日列表（从数据库stock_daily_kline获取）"""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT trade_date 
        FROM stock_daily_kline 
        WHERE trade_date >= %s AND trade_date <= %s
        ORDER BY trade_date
        """,
        (start_date, end_date),
    )
    days = [row[0].strftime("%Y%m%d") for row in cur.fetchall()]
    conn.close()
    return [int(d) for d in days]


def fetch_minute_data_bars(api, market, code, max_pages=30):
    """
    用get_security_bars获取最近5个月的精确1分钟K线
    返回: list of (symbol, trade_time, open, high, low, close, volume, amount)
    """
    all_bars = []
    for page in range(max_pages):
        data = api.get_security_bars(CATEGORY_1MIN, market, code, page * 800, 800)
        if not data:
            break
        for bar in data:
            dt = bar["datetime"]
            # 解析datetime格式: "2026-04-30 13:21"
            trade_time = datetime.strptime(dt, "%Y-%m-%d %H:%M")
            all_bars.append(
                (
                    code,
                    trade_time,
                    float(bar["open"]),
                    float(bar["high"]),
                    float(bar["low"]),
                    float(bar["close"]),
                    int(bar["vol"]),
                    float(bar["amount"]),
                )
            )
    return all_bars


def fetch_minute_data_history(api, market, code, date_int):
    """
    用get_history_minute_time_data获取指定日期的分时数据
    返回: list of (symbol, trade_time, open, high, low, close, volume, amount)
    """
    data = api.get_history_minute_time_data(market, code, date_int)
    if not data or len(data) == 0:
        return []

    # 解析日期
    year = date_int // 10000
    month = (date_int % 10000) // 100
    day = date_int % 100

    rows = []
    for i, item in enumerate(data):
        price = float(item["price"])
        vol = int(item["vol"]) * 100  # 手数转股数

        # 计算时间
        # 0-119: 9:30-11:29 (上午)
        # 120-239: 13:00-14:59 (下午)
        if i < 120:
            hour = 9 + (i + 30) // 60
            minute = (i + 30) % 60
        else:
            idx = i - 120
            hour = 13 + idx // 60
            minute = idx % 60

        trade_time = datetime(year, month, day, hour, minute)

        # 用price近似OHLC（1分钟内波动极小）
        rows.append(
            (
                code,
                trade_time,
                price,  # open
                price,  # high
                price,  # low
                price,  # close
                vol,
                round(price * vol, 2),  # amount估算
            )
        )

    return rows


def get_existing_data_range(conn, symbol):
    """获取数据库中已有数据的日期范围"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT MIN(trade_time), MAX(trade_time) 
        FROM stock_minute_kline 
        WHERE symbol = %s
        """,
        (symbol,),
    )
    row = cur.fetchone()
    return row[0], row[1]


def get_existing_dates(conn, symbol):
    """获取数据库中已有的交易日集合"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT DATE(trade_time) 
        FROM stock_minute_kline 
        WHERE symbol = %s
        """,
        (symbol,),
    )
    return {row[0] for row in cur.fetchall()}


def batch_insert(conn, rows):
    """批量插入数据，使用ON CONFLICT跳过已存在记录"""
    if not rows:
        return 0

    sql = """
        INSERT INTO stock_minute_kline (symbol, trade_time, open, high, low, close, volume, amount)
        VALUES %s
        ON CONFLICT (symbol, trade_time) DO NOTHING
    """

    # 转换为元组列表
    values = [
        (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7])
        for r in rows
    ]

    cur = conn.cursor()
    execute_values(cur, sql, values, page_size=5000)
    inserted = cur.rowcount
    conn.commit()
    return inserted


def fetch_symbol_history(market, code, start_date_int, end_date_int, trading_days, existing_dates):
    """
    获取单只股票的历史1分钟数据
    返回: list of rows
    """
    api = get_tdx_api()
    all_rows = []

    try:
        for date_int in trading_days:
            # 跳过已有数据
            date_str = str(date_int)
            date_obj = datetime.strptime(date_str, "%Y%m%d").date()
            if date_obj in existing_dates:
                continue

            # 跳过范围外的日期
            if date_int < start_date_int or date_int > end_date_int:
                continue

            rows = fetch_minute_data_history(api, market, code, date_int)
            if rows:
                all_rows.extend(rows)

    except Exception as e:
        log.warning(f"获取 {code} 历史数据出错: {e}")
    finally:
        api.disconnect()

    return all_rows


def fetch_symbol_recent(market, code, existing_max_time):
    """
    获取单只股票最近5个月的精确1分钟K线
    只获取比已有数据更新的部分
    返回: list of rows
    """
    api = get_tdx_api()
    all_rows = []

    try:
        # 获取最近5个月数据
        bars = fetch_minute_data_bars(api, market, code, max_pages=30)

        # 过滤掉已有数据
        if existing_max_time:
            bars = [b for b in bars if b[1] > existing_max_time]

        all_rows.extend(bars)

    except Exception as e:
        log.warning(f"获取 {code} 最近数据出错: {e}")
    finally:
        api.disconnect()

    return all_rows


def main():
    parser = argparse.ArgumentParser(description="全市场1分钟K线数据导入")
    parser.add_argument("--start-date", default="20200101", help="起始日期 YYYYMMDD")
    parser.add_argument("--end-date", default=None, help="结束日期 YYYYMMDD，默认今天")
    parser.add_argument("--symbols", nargs="*", help="指定股票代码列表")
    parser.add_argument("--limit", type=int, default=0, help="限制股票数量，0=全部")
    parser.add_argument("--workers", type=int, default=3, help="并发工作线程数")
    parser.add_argument("--batch-size", type=int, default=50, help="每批写入的股票数")
    parser.add_argument("--mode", choices=["history", "recent", "full"], default="full",
                        help="history=只获取历史分时数据, recent=只获取最近5个月, full=两者都获取")
    parser.add_argument("--dry-run", action="store_true", help="只统计不实际写入")
    parser.add_argument("--resume", action="store_true", help="从断点续传（跳过已有数据）")
    args = parser.parse_args()

    start_date = datetime.strptime(args.start_date, "%Y%m%d").date()
    end_date = datetime.strptime(args.end_date, "%Y%m%d").date() if args.end_date else datetime.now().date()
    start_date_int = int(args.start_date)
    end_date_int = int(end_date.strftime("%Y%m%d"))

    log.info(f"=== 全市场1分钟K线数据导入 ===")
    log.info(f"时间范围: {start_date} ~ {end_date}")
    log.info(f"模式: {args.mode}")

    # 获取交易日历
    log.info("获取交易日历...")
    trading_days = get_trading_days_fast(start_date, end_date)
    log.info(f"交易日数: {len(trading_days)}")

    # 获取股票列表
    log.info("获取A股列表...")
    api = get_tdx_api()
    all_stocks = get_all_a_stocks(api)
    api.disconnect()
    log.info(f"A股总数: {len(all_stocks)}")

    # 过滤股票
    if args.symbols:
        all_stocks = [s for s in all_stocks if s[1] in args.symbols]
    if args.limit > 0:
        all_stocks = all_stocks[: args.limit]

    log.info(f"待处理股票数: {len(all_stocks)}")

    if args.dry_run:
        # 估算数据量
        total_bars = len(all_stocks) * len(trading_days) * MINUTES_PER_DAY
        log.info(f"预估总数据量: {total_bars:,} 条 ({total_bars * 60 / 1024 / 1024:.1f} MB)")
        return

    # 连接数据库
    conn = psycopg2.connect(DB_URL)

    # 统计
    total_inserted = 0
    total_errors = 0
    start_time = time.time()

    # 分批处理
    for batch_start in range(0, len(all_stocks), args.batch_size):
        batch = all_stocks[batch_start : batch_start + args.batch_size]
        batch_num = batch_start // args.batch_size + 1
        total_batches = (len(all_stocks) + args.batch_size - 1) // args.batch_size

        log.info(f"--- 批次 {batch_num}/{total_batches} ({len(batch)} 只股票) ---")

        # 并发获取数据
        all_rows = []
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {}
            for market, code, name in batch:
                # 获取已有数据范围
                existing_dates = set()
                existing_max_time = None
                if args.resume:
                    try:
                        existing_dates = get_existing_dates(conn, code)
                        _, existing_max_time = get_existing_data_range(conn, code)
                    except Exception:
                        pass

                if args.mode in ("history", "full"):
                    f = executor.submit(
                        fetch_symbol_history,
                        market,
                        code,
                        start_date_int,
                        end_date_int,
                        trading_days,
                        existing_dates,
                    )
                    futures[f] = (code, "history")

                if args.mode in ("recent", "full"):
                    f = executor.submit(
                        fetch_symbol_recent,
                        market,
                        code,
                        existing_max_time,
                    )
                    futures[f] = (code, "recent")

            for f in as_completed(futures):
                code, mode = futures[f]
                try:
                    rows = f.result()
                    if rows:
                        all_rows.extend(rows)
                        log.info(f"  {code} ({mode}): {len(rows)} 条")
                except Exception as e:
                    log.error(f"  {code} ({mode}) 失败: {e}")
                    total_errors += 1

        # 批量写入
        if all_rows:
            try:
                inserted = batch_insert(conn, all_rows)
                total_inserted += inserted
                log.info(f"  批次写入: {inserted} 条 (总计: {total_inserted:,})")
            except Exception as e:
                log.error(f"  批次写入失败: {e}")
                total_errors += 1
                conn.rollback()

        # 进度
        elapsed = time.time() - start_time
        progress = min(batch_start + args.batch_size, len(all_stocks)) / len(all_stocks)
        eta = elapsed / progress * (1 - progress) if progress > 0 else 0
        log.info(
            f"  进度: {progress:.1%}, 已耗时: {elapsed/60:.1f}分钟, 预计剩余: {eta/60:.1f}分钟"
        )

    # 最终统计
    elapsed = time.time() - start_time
    log.info(f"\n=== 导入完成 ===")
    log.info(f"总插入: {total_inserted:,} 条")
    log.info(f"总错误: {total_errors}")
    log.info(f"总耗时: {elapsed/60:.1f} 分钟")

    # 验证
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(trade_time), MAX(trade_time) FROM stock_minute_kline"
    )
    row = cur.fetchone()
    log.info(f"数据库状态: {row[0]:,} 条, {row[1]} 只股票, {row[2]} ~ {row[3]}")

    conn.close()


if __name__ == "__main__":
    main()
