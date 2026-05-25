#!/usr/bin/env python3
"""
全市场1分钟K线数据导入脚本 v2

优化点：
1. 按日获取+写入，避免内存溢出
2. 使用COPY批量写入提升性能
3. 支持断点续传
4. 进度实时显示

数据源：通达信 pytdx
- 最近5个月：get_security_bars 精确OHLCV
- 更早历史：get_history_minute_time_data 按日获取（price近似OHLC）

目标表：stock_minute_kline (PostgreSQL)
时间范围：2020-01-01 至今
"""

import argparse
import io
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
        logging.FileHandler("fetch_minute_kline_full.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://wolf:944c65ad900216867595733415329840@localhost/trading_agents",
)

TDX_SERVERS = [
    ("180.153.18.170", 7709),
]

CATEGORY_1MIN = 8
MINUTES_PER_DAY = 240


def normalize_stock_symbol(code: str, market: str | int | None = None) -> str:
    raw = str(code or "").strip().upper()
    if not raw:
        return ""
    if "." in raw:
        return raw
    if len(raw) == 6 and raw.isdigit():
        market_text = str(market or "").lower()
        if market_text in {"1", "sh"}:
            return f"{raw}.SH"
        if raw.startswith(("4", "8")) or raw.startswith("92"):
            return f"{raw}.BJ"
        if raw.startswith(("5", "6", "9")):
            return f"{raw}.SH"
        return f"{raw}.SZ"
    return raw


def symbol_variants(symbol: str) -> tuple[str, ...]:
    normalized = normalize_stock_symbol(symbol)
    variants = {normalized, str(symbol or "").strip().upper()}
    if "." in normalized:
        variants.add(normalized.split(".", 1)[0])
    if normalized.endswith(".BJ"):
        variants.add(f"BJ{normalized.split('.', 1)[0]}")
    return tuple(item for item in variants if item)


def get_tdx_api():
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
    stocks = []
    for start in range(0, 8000, 1000):
        data = api.get_security_list(0, start)
        if not data:
            break
        for s in data:
            code = s["code"]
            if code.startswith(("000", "001", "002", "003", "300", "301")):
                stocks.append((0, code, s["name"]))
    for start in range(0, 28000, 1000):
        data = api.get_security_list(1, start)
        if not data:
            continue
        for s in data:
            code = s["code"]
            if code.startswith(("600", "601", "603", "605", "688", "689")):
                stocks.append((1, code, s["name"]))
    seen = set()
    unique = []
    for m, c, n in stocks:
        if c not in seen:
            seen.add(c)
            unique.append((m, c, n))
    return unique


def get_trading_days_fast(start_date, end_date):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT trade_date FROM stock_daily_kline "
        "WHERE trade_date >= %s AND trade_date <= %s ORDER BY trade_date",
        (start_date, end_date),
    )
    days = [int(row[0].strftime("%Y%m%d")) for row in cur.fetchall()]
    conn.close()
    return days


def fetch_minute_data_history(api, market, code, date_int):
    """获取指定日期的分时数据，返回list of tuples"""
    data = api.get_history_minute_time_data(market, code, date_int)
    if not data or len(data) == 0:
        return []

    year = date_int // 10000
    month = (date_int % 10000) // 100
    day = date_int % 100

    rows = []
    for i, item in enumerate(data):
        price = float(item["price"])
        vol = int(item["vol"]) * 100  # 手转股

        if i < 120:
            hour = 9 + (i + 30) // 60
            minute = (i + 30) % 60
        else:
            idx = i - 120
            hour = 13 + idx // 60
            minute = idx % 60

        trade_time = datetime(year, month, day, hour, minute)
        rows.append((normalize_stock_symbol(code, market), trade_time, price, price, price, price, vol, round(price * vol, 2)))

    return rows


def fetch_recent_bars(api, market, code, existing_max_time=None):
    """获取最近5个月精确1分钟K线"""
    all_bars = []
    for page in range(30):
        data = api.get_security_bars(CATEGORY_1MIN, market, code, page * 800, 800)
        if not data:
            break
        for bar in data:
            trade_time = datetime.strptime(bar["datetime"], "%Y-%m-%d %H:%M")
            if existing_max_time and trade_time <= existing_max_time:
                continue
            all_bars.append((
                normalize_stock_symbol(code, market), trade_time,
                float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"]),
                int(bar["vol"]), float(bar["amount"]),
            ))
    return all_bars


def get_existing_dates(conn, symbol):
    cur = conn.cursor()
    variants = symbol_variants(symbol)
    cur.execute(
        "SELECT DISTINCT DATE(trade_time) FROM stock_minute_kline WHERE symbol = ANY(%s)",
        (list(variants),),
    )
    return {row[0] for row in cur.fetchall()}


def get_existing_max_time(conn, symbol):
    cur = conn.cursor()
    variants = symbol_variants(symbol)
    cur.execute(
        "SELECT MAX(trade_time) FROM stock_minute_kline WHERE symbol = ANY(%s)",
        (list(variants),),
    )
    return cur.fetchone()[0]


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


def process_symbol(api, market, code, name, trading_days, start_date_int, end_date_int, mode, resume):
    """处理单只股票：获取+写入，返回(inserted, errors)"""
    conn = psycopg2.connect(DB_URL)
    total_inserted = 0
    errors = 0

    try:
        # 获取已有数据信息
        existing_dates = set()
        existing_max_time = None
        if resume:
            existing_dates = get_existing_dates(conn, code)
            existing_max_time = get_existing_max_time(conn, code)

        # 1. 先获取最近5个月的精确数据
        if mode in ("recent", "full"):
            recent_rows = fetch_recent_bars(api, market, code, existing_max_time)
            if recent_rows:
                inserted = batch_insert(conn, recent_rows)
                total_inserted += inserted
                log.info(f"  {code} 最近数据: {len(recent_rows)}条, 写入{inserted}条")

        # 2. 按日获取历史数据
        if mode in ("history", "full"):
            # 过滤需要获取的交易日
            dates_to_fetch = []
            for date_int in trading_days:
                if date_int < start_date_int or date_int > end_date_int:
                    continue
                date_str = str(date_int)
                date_obj = datetime.strptime(date_str, "%Y%m%d").date()
                if resume and date_obj in existing_dates:
                    continue
                dates_to_fetch.append(date_int)

            if dates_to_fetch:
                # 批量获取，每50天写入一次
                batch_rows = []
                for idx, date_int in enumerate(dates_to_fetch):
                    try:
                        rows = fetch_minute_data_history(api, market, code, date_int)
                        if rows:
                            batch_rows.extend(rows)
                    except Exception as e:
                        errors += 1
                        if errors <= 3:
                            log.warning(f"  {code} 日期{date_int}获取失败: {e}")

                    # 每50天或最后一批写入
                    if len(batch_rows) >= 12000 or idx == len(dates_to_fetch) - 1:
                        if batch_rows:
                            inserted = batch_insert(conn, batch_rows)
                            total_inserted += inserted
                            batch_rows = []

                if dates_to_fetch:
                    log.info(f"  {code} 历史: {len(dates_to_fetch)}天待获取, 写入{total_inserted}条")

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
    parser = argparse.ArgumentParser(description="全市场1分钟K线数据导入 v2")
    parser.add_argument("--start-date", default="20200101")
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--symbols", nargs="*", help="指定股票代码")
    parser.add_argument("--limit", type=int, default=0, help="限制股票数量")
    parser.add_argument("--mode", choices=["history", "recent", "full"], default="full")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", action="store_false", dest="resume")
    args = parser.parse_args()

    start_date = datetime.strptime(args.start_date, "%Y%m%d").date()
    end_date = datetime.strptime(args.end_date, "%Y%m%d").date() if args.end_date else datetime.now().date()
    start_date_int = int(args.start_date)
    end_date_int = int(end_date.strftime("%Y%m%d"))

    log.info("=== 全市场1分钟K线数据导入 v2 ===")
    log.info(f"时间范围: {start_date} ~ {end_date}, 模式: {args.mode}")

    # 交易日历
    log.info("获取交易日历...")
    trading_days = get_trading_days_fast(start_date, end_date)
    log.info(f"交易日数: {len(trading_days)}")

    # 股票列表
    log.info("获取A股列表...")
    api = get_tdx_api()
    all_stocks = get_all_a_stocks(api)
    api.disconnect()
    log.info(f"A股总数: {len(all_stocks)}")

    if args.symbols:
        all_stocks = [s for s in all_stocks if s[1] in args.symbols]
    if args.limit > 0:
        all_stocks = all_stocks[: args.limit]

    log.info(f"待处理: {len(all_stocks)} 只")

    if args.dry_run:
        total_bars = len(all_stocks) * len(trading_days) * MINUTES_PER_DAY
        log.info(f"预估: {total_bars:,} 条")
        return

    # 逐只处理（共享一个通达信连接，断线自动重连）
    total_inserted = 0
    total_errors = 0
    start_time = time.time()
    api = get_tdx_api()

    def ensure_api():
        nonlocal api
        try:
            api.get_security_count(0)
        except Exception:
            log.warning("通达信连接断开，正在重连...")
            try:
                api.disconnect()
            except Exception:
                pass
            api = get_tdx_api()
        return api

    for idx, (market, code, name) in enumerate(all_stocks):
        # 每50只股票检查一次连接
        if idx % 50 == 0:
            api = ensure_api()

        log.info(f"[{idx+1}/{len(all_stocks)}] {code} {name}")
        try:
            inserted, errs = process_symbol(
                api, market, code, name, trading_days, start_date_int, end_date_int, args.mode, args.resume
            )
            total_inserted += inserted
            total_errors += errs
        except Exception as e:
            log.error(f"  {code} 异常: {e}")
            total_errors += 1
            # 重连
            try:
                api.disconnect()
            except Exception:
                pass
            api = get_tdx_api()

        # 进度
        elapsed = time.time() - start_time
        progress = (idx + 1) / len(all_stocks)
        eta = elapsed / progress * (1 - progress) if progress > 0 else 0
        if (idx + 1) % 10 == 0 or idx == len(all_stocks) - 1:
            log.info(
                f"进度: {idx+1}/{len(all_stocks)} ({progress:.1%}), "
                f"已插入: {total_inserted:,}, 耗时: {elapsed/60:.1f}min, "
                f"预计剩余: {eta/60:.1f}min"
            )

    try:
        api.disconnect()
    except Exception:
        pass

    elapsed = time.time() - start_time
    log.info(f"\n=== 完成 ===")
    log.info(f"总插入: {total_inserted:,}, 错误: {total_errors}, 耗时: {elapsed/60:.1f}min")

    # 验证
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(trade_time), MAX(trade_time) FROM stock_minute_kline")
    row = cur.fetchone()
    log.info(f"数据库: {row[0]:,}条, {row[1]}只, {row[2]} ~ {row[3]}")
    conn.close()


if __name__ == "__main__":
    main()
