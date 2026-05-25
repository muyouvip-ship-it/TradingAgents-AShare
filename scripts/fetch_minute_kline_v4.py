#!/usr/bin/env python3
"""
A股全量1分钟K线数据补全脚本 v4 - 多进程并行版

优化点：
1. 多进程并行（默认8进程），每进程独立通达信连接
2. 只获取最近5个月精确数据（get_security_bars），历史数据暂不补全
3. 先快速覆盖全量股票的近期数据，历史数据后续按需补全
4. 北交所使用东方财富API

策略：先广后深 —— 先保证所有股票都有近期分钟数据，再逐步补历史
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from multiprocessing import Pool, Manager

import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [PID:%(process)d] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("fetch_minute_kline_v4.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://wolf@/trading_agents?host=/tmp",
)

TDX_SERVERS = [
    ("180.153.18.170", 7709),
    ("180.153.18.171", 7709),
    ("202.108.253.130", 7709),
    ("202.108.253.131", 7709),
]

CATEGORY_1MIN = 8


def normalize_stock_symbol(code: str, market: str | int | None = None) -> str:
    raw = str(code or "").strip().upper()
    if not raw:
        return ""
    if raw.startswith("BJ") and raw[2:].isdigit():
        return f"{raw[2:]}.BJ"
    if "." in raw:
        return raw
    if len(raw) == 6 and raw.isdigit():
        market_text = str(market or "").lower()
        if market_text in {"1", "sh"}:
            return f"{raw}.SH"
        if market_text == "bj" or raw.startswith(("4", "8")) or raw.startswith("92"):
            return f"{raw}.BJ"
        if raw.startswith(("5", "6", "9")):
            return f"{raw}.SH"
        return f"{raw}.SZ"
    return raw


def get_tdx_api():
    from pytdx.hq import TdxHq_API
    import random
    servers = TDX_SERVERS.copy()
    random.shuffle(servers)
    for host, port in servers:
        try:
            api = TdxHq_API()
            result = api.connect(host, port)
            if result:
                return api
        except Exception:
            continue
    raise RuntimeError("无法连接通达信服务器")


def fetch_recent_bars_full(api, market, code):
    """获取通达信所有可用的1分钟K线（最近约5个月，30页）"""
    all_bars = []
    for page in range(30):
        try:
            data = api.get_security_bars(CATEGORY_1MIN, market, code, page * 800, 800)
        except Exception:
            break
        if not data:
            break
        for bar in data:
            trade_time = datetime.strptime(bar["datetime"], "%Y-%m-%d %H:%M")
            all_bars.append((
                normalize_stock_symbol(code, market), trade_time,
                float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"]),
                int(bar["vol"]), float(bar["amount"]),
            ))
        if len(data) < 800:
            break
    return all_bars


def fetch_history_days(api, market, code, date_ints):
    """按日获取历史分时数据"""
    all_rows = []
    for date_int in date_ints:
        try:
            data = api.get_history_minute_time_data(market, code, date_int)
        except Exception:
            continue
        if not data:
            continue
        year = date_int // 10000
        month = (date_int % 10000) // 100
        day = date_int % 100
        for i, item in enumerate(data):
            try:
                price = float(item["price"])
                vol = int(item["vol"]) * 100
                if i < 120:
                    hour = 9 + (i + 30) // 60
                    minute = (i + 30) % 60
                else:
                    idx = i - 120
                    hour = 13 + idx // 60
                    minute = idx % 60
                if hour > 23 or minute > 59:
                    continue
                trade_time = datetime(year, month, day, hour, minute)
                all_rows.append((normalize_stock_symbol(code, market), trade_time, price, price, price, price, vol, round(price * vol, 2)))
            except (ValueError, KeyError):
                continue
    return all_rows


def batch_insert(conn, rows):
    if not rows:
        return 0
    sql = """
        INSERT INTO stock_minute_kline (symbol, trade_time, open, high, low, close, volume, amount)
        VALUES %s
        ON CONFLICT (symbol, trade_time) DO NOTHING
    """
    cur = conn.cursor()
    execute_values(cur, sql, rows, page_size=5000)
    inserted = cur.rowcount
    conn.commit()
    return inserted


def process_tdx_stock(args):
    """处理单只深沪股票（子进程）"""
    market, code, trading_days_str = args
    # trading_days_str: 逗号分隔的日期整数
    trading_days = [int(d) for d in trading_days_str.split(',') if d]
    
    try:
        api = get_tdx_api()
    except RuntimeError:
        return code, 0, 1, "连接失败"
    
    conn = psycopg2.connect(DB_URL)
    total_inserted = 0
    errors = 0
    
    try:
        # 1. 获取最近5个月精确数据
        recent_rows = fetch_recent_bars_full(api, market, code)
        if recent_rows:
            inserted = batch_insert(conn, recent_rows)
            total_inserted += inserted
        
        # 2. 获取recent未覆盖的历史数据
        if recent_rows:
            recent_min_date = min(r[1] for r in recent_rows).date()
        else:
            recent_min_date = datetime(2026, 5, 1).date()
        
        history_dates = [d for d in trading_days 
                        if datetime.strptime(str(d), '%Y%m%d').date() < recent_min_date]
        
        if history_dates:
            # 分批获取，每200天一批
            for i in range(0, len(history_dates), 200):
                batch_dates = history_dates[i:i+200]
                rows = fetch_history_days(api, market, code, batch_dates)
                if rows:
                    inserted = batch_insert(conn, rows)
                    total_inserted += inserted
    
    except Exception as e:
        errors += 1
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()
        try:
            api.disconnect()
        except Exception:
            pass
    
    return code, total_inserted, errors, ""


def process_bj_stock(code):
    """处理单只北交所股票"""
    import urllib.request
    import json
    
    symbol = normalize_stock_symbol(code, "bj")
    conn = psycopg2.connect(DB_URL)
    total_inserted = 0
    
    try:
        secid = f"0.{code}"
        # 按月获取
        current = datetime(2020, 1, 1)
        end_dt = datetime.now()
        
        while current <= end_dt:
            current_end = min(current + timedelta(days=30), end_dt)
            start_str = current.strftime("%Y%m%d")
            end_str = current_end.strftime("%Y%m%d")
            
            params = (
                f"secid={secid}"
                f"&fields1=f1,f2,f3,f4,f5,f6"
                f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
                f"&klt=1&fqt=0"
                f"&beg={start_str}&end={end_str}"
            )
            url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?{params}"
            
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                    "Referer": "https://quote.eastmoney.com/",
                })
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read())
                
                if data.get("data") and data["data"].get("klines"):
                    rows = []
                    for kline_str in data["data"]["klines"]:
                        parts = kline_str.split(",")
                        if len(parts) < 7:
                            continue
                        try:
                            trade_time = datetime.strptime(parts[0], "%Y-%m-%d %H:%M")
                            rows.append((
                                symbol, trade_time,
                                float(parts[1]), float(parts[3]), float(parts[4]), float(parts[2]),
                                int(float(parts[5])), float(parts[6]),
                            ))
                        except (ValueError, IndexError):
                            continue
                    if rows:
                        inserted = batch_insert(conn, rows)
                        total_inserted += inserted
            except Exception:
                pass
            
            current = current_end + timedelta(days=1)
            time.sleep(0.2)
    
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()
    
    return code, total_inserted, 0, ""


def get_missing_stocks():
    """获取日线有但分钟线缺失的股票列表"""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    # 日线中所有活跃股票
    cur.execute("""
        SELECT DISTINCT symbol FROM stock_daily_kline
        WHERE trade_date >= '2026-04-01'
    """)
    daily_raw = {row[0] for row in cur.fetchall()}

    # 统一为纯数字代码 + 市场分类
    daily_codes = {}
    for sym in daily_raw:
        if sym.startswith('bj'):
            code = sym[2:]
            daily_codes[code] = 'bj'
        elif sym.endswith('.BJ'):
            code = sym.replace('.BJ', '')
            daily_codes[code] = 'bj'
        elif sym.endswith('.SZ'):
            code = sym.replace('.SZ', '')
            daily_codes[code] = 'sz'
        elif sym.endswith('.SH'):
            code = sym.replace('.SH', '')
            daily_codes[code] = 'sh'
        else:
            code = sym
            if code not in daily_codes:
                if code.startswith(('000', '001', '002', '003', '300', '301')):
                    daily_codes[code] = 'sz'
                elif code.startswith(('600', '601', '603', '605', '688', '689')):
                    daily_codes[code] = 'sh'
                elif code.startswith(('4', '8', '9')):
                    daily_codes[code] = 'bj'
                else:
                    daily_codes[code] = 'unknown'

    # 分钟线中已有的股票
    cur.execute("""
        SELECT DISTINCT symbol FROM stock_minute_kline
        WHERE trade_time >= '2026-04-28' AND trade_time < '2026-04-29'
    """)
    minute_recent = {row[0] for row in cur.fetchall()}

    cur.execute("""
        SELECT DISTINCT symbol FROM stock_minute_kline
        WHERE trade_time >= '2026-01-01'
        AND symbol NOT IN %s
    """, (tuple(minute_recent) if minute_recent else ('__none__',),))
    minute_6m = {row[0] for row in cur.fetchall()}

    cur.execute("""
        SELECT DISTINCT symbol FROM stock_minute_kline
        WHERE trade_time >= '2020-01-01' AND trade_time < '2026-01-01'
        AND symbol NOT IN %s
    """, (tuple(minute_recent | minute_6m) if (minute_recent | minute_6m) else ('__none__',),))
    minute_old = {row[0] for row in cur.fetchall()}

    minute_raw = minute_recent | minute_6m | minute_old

    minute_codes = set()
    for sym in minute_raw:
        if sym.startswith('bj'):
            minute_codes.add(sym[2:])
        elif '.' in sym:
            minute_codes.add(sym.split('.')[0])
        else:
            minute_codes.add(sym)

    conn.close()

    missing = []
    for code, market in sorted(daily_codes.items()):
        if code not in minute_codes:
            missing.append((code, market))

    return missing


def main():
    parser = argparse.ArgumentParser(description="A股全量1分钟K线数据补全 v4 - 多进程并行版")
    parser.add_argument("--start-date", default="20200101")
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--mode", choices=["tdx", "bj", "all"], default="all")
    parser.add_argument("--workers", type=int, default=8, help="并行进程数")
    parser.add_argument("--limit", type=int, default=0, help="限制股票数量(测试用)")
    parser.add_argument("--recent-only", action="store_true", 
                        help="只获取最近5个月数据（快速覆盖）")
    args = parser.parse_args()

    start_date = datetime.strptime(args.start_date, "%Y%m%d").date()
    end_date = datetime.strptime(args.end_date, "%Y%m%d").date() if args.end_date else datetime.now().date()

    log.info("=" * 60)
    log.info("=== A股全量1分钟K线数据补全 v4 - 多进程并行版 ===")
    log.info(f"时间范围: {start_date} ~ {end_date}")
    log.info(f"模式: {args.mode}, 并行数: {args.workers}")
    log.info(f"仅近期数据: {args.recent_only}")
    log.info("=" * 60)

    # 获取交易日历
    log.info("获取交易日历...")
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT trade_date FROM stock_daily_kline "
        "WHERE trade_date >= %s AND trade_date <= %s ORDER BY trade_date",
        (start_date, end_date),
    )
    trading_days = [int(row[0].strftime("%Y%m%d")) for row in cur.fetchall()]
    conn.close()
    log.info(f"交易日数: {len(trading_days)}")
    trading_days_str = ','.join(str(d) for d in trading_days)

    # 获取缺失股票
    log.info("分析缺失股票...")
    missing = get_missing_stocks()
    log.info(f"缺失股票总数: {len(missing)}")

    # 分类
    tdx_tasks = []  # (market, code, trading_days_str)
    bj_tasks = []   # code
    for code, market in missing:
        if market == 'bj':
            bj_tasks.append(code)
        elif market in ('sz', 'sh'):
            mkt = 0 if market == 'sz' else 1
            tdx_tasks.append((mkt, code, trading_days_str if not args.recent_only else ''))
        else:
            if code.startswith(('000', '001', '002', '003', '300', '301')):
                tdx_tasks.append((0, code, trading_days_str if not args.recent_only else ''))
            elif code.startswith(('600', '601', '603', '605', '688', '689')):
                tdx_tasks.append((1, code, trading_days_str if not args.recent_only else ''))
            elif code.startswith(('4', '8', '9')):
                bj_tasks.append(code)

    log.info(f"  深沪缺失: {len(tdx_tasks)} 只")
    log.info(f"  北交所缺失: {len(bj_tasks)} 只")

    if args.limit > 0:
        tdx_tasks = tdx_tasks[:args.limit]
        bj_tasks = bj_tasks[:args.limit]
        log.info(f"  限制后: 深沪 {len(tdx_tasks)}, 北交所 {len(bj_tasks)}")

    total_inserted = 0
    total_errors = 0
    start_time = time.time()

    # 处理深沪股票 - 多进程并行
    if args.mode in ("tdx", "all") and tdx_tasks:
        log.info(f"\n--- 开始处理深沪股票 ({len(tdx_tasks)} 只, {args.workers}进程) ---")
        
        with Pool(processes=args.workers) as pool:
            results = pool.imap_unordered(process_tdx_stock, tdx_tasks)
            
            for idx, (code, inserted, errs, msg) in enumerate(results):
                total_inserted += inserted
                total_errors += errs
                
                if (idx + 1) % 10 == 0 or idx == len(tdx_tasks) - 1:
                    elapsed = time.time() - start_time
                    progress = (idx + 1) / len(tdx_tasks)
                    eta = elapsed / progress * (1 - progress) if progress > 0 else 0
                    log.info(
                        f"[深沪] 进度: {idx+1}/{len(tdx_tasks)} ({progress:.1%}), "
                        f"已插入: {total_inserted:,}, 耗时: {elapsed/60:.1f}min, "
                        f"预计剩余: {eta/60:.1f}min"
                    )

    # 处理北交所股票 - 单进程（API限流）
    if args.mode in ("bj", "all") and bj_tasks:
        log.info(f"\n--- 开始处理北交所股票 ({len(bj_tasks)} 只) ---")
        
        for idx, code in enumerate(bj_tasks):
            _, inserted, errs, _ = process_bj_stock(code)
            total_inserted += inserted
            total_errors += errs
            
            if (idx + 1) % 10 == 0 or idx == len(bj_tasks) - 1:
                elapsed = time.time() - start_time
                progress = (idx + 1) / len(bj_tasks)
                eta = elapsed / progress * (1 - progress) if progress > 0 else 0
                log.info(
                    f"[北交所] 进度: {idx+1}/{len(bj_tasks)} ({progress:.1%}), "
                    f"已插入: {total_inserted:,}, 耗时: {elapsed/60:.1f}min, "
                    f"预计剩余: {eta/60:.1f}min"
                )

    # 汇总
    elapsed = time.time() - start_time
    log.info("\n" + "=" * 60)
    log.info("=== 完成 ===")
    log.info(f"总插入: {total_inserted:,}, 错误: {total_errors}, 耗时: {elapsed/60:.1f}min")

    # 验证
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT reltuples::bigint FROM pg_class WHERE relname = 'stock_minute_kline'")
    est = cur.fetchone()[0]
    log.info(f"数据库估计行数: {est:,}")

    cur.execute("SELECT MIN(trade_time), MAX(trade_time) FROM stock_minute_kline")
    row = cur.fetchone()
    log.info(f"时间范围: {row[0]} ~ {row[1]}")

    cur.execute("""
        SELECT
            CASE
                WHEN LEFT(SPLIT_PART(symbol, '.', 1), 1) = '0' THEN '深主板(0xx)'
                WHEN LEFT(SPLIT_PART(symbol, '.', 1), 1) = '3' THEN '创业板(3xx)'
                WHEN LEFT(SPLIT_PART(symbol, '.', 1), 1) = '6' THEN '沪主板(6xx)'
                WHEN symbol LIKE '%.BJ' THEN '北交所'
                ELSE '其他'
            END as category,
            COUNT(DISTINCT symbol) as stocks
        FROM stock_minute_kline
        WHERE trade_time >= '2026-04-28'
        GROUP BY 1 ORDER BY 2 DESC
    """)
    log.info("覆盖情况:")
    for cat, cnt in cur.fetchall():
        log.info(f"  {cat}: {cnt} 只")

    conn.close()


if __name__ == "__main__":
    main()
