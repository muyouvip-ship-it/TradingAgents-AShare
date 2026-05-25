#!/usr/bin/env python3
"""
北交所1分钟K线数据导入脚本

数据源：东方财富 push2his API（直接HTTP请求，不依赖AKShare）
北交所股票secid格式：0.{code}（与深市相同market=0，但代码以4/8/9开头）

目标表：stock_minute_kline (PostgreSQL)
时间范围：2020-01-01 至今
"""

import argparse
import io
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta

import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("fetch_bj_minute_kline.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://wolf:944c65ad900216867595733415329840@localhost/trading_agents",
)

# 东方财富分钟K线API
EM_MINUTE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "*/*",
}

# 北交所股票代码前缀
BJ_PREFIXES = ("4", "8", "9")

# 东方财富分钟K线字段映射
# klines格式: "时间,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率"
KLINE_FIELDS = ["trade_time", "open", "close", "high", "low", "volume", "amount", "amplitude", "pct_change", "change", "turnover"]


def get_bj_stock_list():
    """从数据库日K线表获取北交所股票列表"""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT symbol FROM stock_daily_kline WHERE symbol LIKE 'bj%' ORDER BY symbol"
    )
    stocks = [row[0] for row in cur.fetchall()]
    conn.close()
    log.info(f"从日K线表获取到 {len(stocks)} 只北交所股票")
    return stocks


def get_bj_stock_list_from_em():
    """从东方财富获取北交所股票列表（备用）"""
    import urllib.request

    url = "https://82.push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5000&po=1&np=1&fltt=2&invt=2&fid=f3&fs=b:BK0832&fields=f12,f14"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            if data.get("data") and data["data"].get("diff"):
                stocks = []
                for item in data["data"]["diff"]:
                    code = item.get("f12", "")
                    name = item.get("f14", "")
                    if code:
                        stocks.append((code, name))
                log.info(f"从东方财富获取到 {len(stocks)} 只北交所股票")
                return stocks
    except Exception as e:
        log.warning(f"从东方财富获取北交所列表失败: {e}")
    return []


def bj_symbol_to_code(symbol: str) -> str:
    """Return the bare numeric code from bj920000 / 920000.BJ / 920000."""
    normalized = str(symbol or "").strip().upper()
    if normalized.startswith("BJ"):
        return normalized[2:]
    if normalized.endswith(".BJ"):
        return normalized.split(".", 1)[0]
    return normalized


def code_to_bj_symbol(code: str) -> str:
    """Return final-table BJ symbol format."""
    normalized = bj_symbol_to_code(code)
    return f"{normalized}.BJ" if normalized else ""


def fetch_minute_kline_em(code: str, start_date: str, end_date: str, max_retries=3) -> list:
    """
    从东方财富获取1分钟K线数据
    
    code: 纯数字代码（如 920000）
    start_date: YYYYMMDD
    end_date: YYYYMMDD
    """
    import urllib.request

    # 北交所在东方财富的secid格式: 0.{code}
    secid = f"0.{code}"
    
    params = (
        f"secid={secid}"
        f"&fields1=f1,f2,f3,f4,f5,f6"
        f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        f"&klt=1"  # 1分钟
        f"&fqt=0"  # 不复权
        f"&beg={start_date}"
        f"&end={end_date}"
    )
    
    url = f"{EM_MINUTE_URL}?{params}"
    
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                
            if not data.get("data") or not data["data"].get("klines"):
                return []
            
            klines = data["data"]["klines"]
            stock_name = data["data"].get("name", "")
            
            rows = []
            for kline_str in klines:
                parts = kline_str.split(",")
                if len(parts) < 7:
                    continue
                
                trade_time_str = parts[0]  # "2026-04-30 09:31"
                try:
                    trade_time = datetime.strptime(trade_time_str, "%Y-%m-%d %H:%M")
                except ValueError:
                    continue
                
                open_price = float(parts[1]) if parts[1] else 0
                close_price = float(parts[2]) if parts[2] else 0
                high_price = float(parts[3]) if parts[3] else 0
                low_price = float(parts[4]) if parts[4] else 0
                volume = int(float(parts[5])) if parts[5] else 0
                amount = float(parts[6]) if parts[6] else 0
                
                # 使用bj前缀的symbol格式
                symbol = code_to_bj_symbol(code)
                rows.append((symbol, trade_time, open_price, high_price, low_price, close_price, volume, amount))
            
            return rows
            
        except Exception as e:
            if attempt < max_retries - 1:
                wait = (attempt + 1) * 2
                log.warning(f"  {code} 获取失败(第{attempt+1}次): {e}, {wait}秒后重试")
                time.sleep(wait)
            else:
                log.error(f"  {code} 获取失败(已重试{max_retries}次): {e}")
                return []


def get_trading_days(start_date, end_date):
    """从数据库获取交易日历"""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT trade_date FROM stock_daily_kline "
        "WHERE trade_date >= %s AND trade_date <= %s ORDER BY trade_date",
        (start_date, end_date),
    )
    days = [row[0] for row in cur.fetchall()]
    conn.close()
    return days


def get_existing_max_time(conn, symbol):
    """获取该股票已有的最大时间"""
    cur = conn.cursor()
    code = bj_symbol_to_code(symbol)
    variants = [code_to_bj_symbol(code), f"bj{code}", code]
    cur.execute(
        "SELECT MAX(trade_time) FROM stock_minute_kline WHERE symbol = ANY(%s)",
        (variants,),
    )
    return cur.fetchone()[0]


def batch_insert(conn, rows):
    """批量插入数据"""
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


def process_symbol(code: str, start_date: str, end_date: str, resume: bool = True):
    """处理单只北交所股票"""
    symbol = code_to_bj_symbol(code)
    conn = psycopg2.connect(DB_URL)
    total_inserted = 0
    errors = 0
    
    try:
        # 检查已有数据
        if resume:
            existing_max = get_existing_max_time(conn, symbol)
            if existing_max:
                # 从已有最大时间的下一天开始
                new_start = (existing_max + timedelta(days=1)).strftime("%Y%m%d")
                if new_start > end_date:
                    log.info(f"  {code} 已是最新，跳过")
                    return 0, 0
                start_date = new_start
                log.info(f"  {code} 断点续传: 从 {start_date} 开始")
        
        # 东方财富API限制：每次最多返回约320条1分钟K线（约1.5个交易日）
        # 按月获取
        current_start = datetime.strptime(start_date, "%Y%m%d")
        end_dt = datetime.strptime(end_date, "%Y%m%d")
        
        while current_start <= end_dt:
            # 每次获取1个月的数据
            current_end = min(
                current_start + timedelta(days=30),
                end_dt,
            )
            start_str = current_start.strftime("%Y%m%d")
            end_str = current_end.strftime("%Y%m%d")
            
            rows = fetch_minute_kline_em(code, start_str, end_str)
            if rows:
                inserted = batch_insert(conn, rows)
                total_inserted += inserted
            
            # 移动到下一个月
            current_start = current_end + timedelta(days=1)
            
            # 请求间隔，避免被封
            time.sleep(0.5)
    
    except Exception as e:
        log.error(f"  {code} 处理失败: {e}")
        errors += 1
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()
    
    return total_inserted, errors


def main():
    parser = argparse.ArgumentParser(description="北交所1分钟K线数据导入")
    parser.add_argument("--start-date", default="20200101", help="开始日期 YYYYMMDD")
    parser.add_argument("--end-date", default=None, help="结束日期 YYYYMMDD")
    parser.add_argument("--symbols", nargs="*", help="指定股票代码（纯数字）")
    parser.add_argument("--limit", type=int, default=0, help="限制股票数量")
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", action="store_false", dest="resume")
    parser.add_argument("--delay", type=float, default=0.5, help="请求间隔秒数")
    args = parser.parse_args()
    
    end_date = args.end_date or datetime.now().strftime("%Y%m%d")
    
    log.info("=== 北交所1分钟K线数据导入 ===")
    log.info(f"时间范围: {args.start_date} ~ {end_date}")
    
    # 获取北交所股票列表
    if args.symbols:
        stocks = args.symbols
    else:
        # 从数据库日K线表获取
        bj_symbols = get_bj_stock_list()
        stocks = [bj_symbol_to_code(s) for s in bj_symbols]
    
    if args.limit > 0:
        stocks = stocks[:args.limit]
    
    log.info(f"待处理: {len(stocks)} 只北交所股票")
    
    if not stocks:
        log.warning("没有找到北交所股票，退出")
        return
    
    # 逐只处理
    total_inserted = 0
    total_errors = 0
    start_time = time.time()
    
    for idx, code in enumerate(stocks):
        log.info(f"[{idx+1}/{len(stocks)}] {code}")
        try:
            inserted, errs = process_symbol(
                code, args.start_date, end_date, args.resume
            )
            total_inserted += inserted
            total_errors += errs
        except Exception as e:
            log.error(f"  {code} 异常: {e}")
            total_errors += 1
        
        # 进度
        elapsed = time.time() - start_time
        progress = (idx + 1) / len(stocks)
        eta = elapsed / progress * (1 - progress) if progress > 0 else 0
        if (idx + 1) % 10 == 0 or idx == len(stocks) - 1:
            log.info(
                f"进度: {idx+1}/{len(stocks)} ({progress:.1%}), "
                f"已插入: {total_inserted:,}, 耗时: {elapsed/60:.1f}min, "
                f"预计剩余: {eta/60:.1f}min"
            )
        
        # 请求间隔
        time.sleep(args.delay)
    
    elapsed = time.time() - start_time
    log.info(f"\n=== 完成 ===")
    log.info(f"总插入: {total_inserted:,}, 错误: {total_errors}, 耗时: {elapsed/60:.1f}min")
    
    # 验证
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*), COUNT(DISTINCT symbol) FROM stock_minute_kline WHERE symbol LIKE 'bj%'"
    )
    row = cur.fetchone()
    log.info(f"北交所分钟K线: {row[0]:,}条, {row[1]}只")
    conn.close()


if __name__ == "__main__":
    main()
