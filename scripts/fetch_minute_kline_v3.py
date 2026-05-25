#!/usr/bin/env python3
"""
A股全量1分钟K线数据补全脚本 v3

功能：
1. 对比日线表和分钟线表，找出缺失的股票
2. 统一symbol格式为带交易所后缀（000001.SZ / 600000.SH / 920000.BJ）
3. 深沪主板+创业板：通过通达信pytdx获取
4. 北交所：通过东方财富API获取
5. 支持断点续传、自动重连
6. 清理旧数据中带后缀的重复记录

目标表：stock_minute_kline (PostgreSQL)
时间范围：2020-01-01 至今
"""

import argparse
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
        logging.FileHandler("fetch_minute_kline_v3.log", encoding="utf-8"),
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
MINUTES_PER_DAY = 240


def normalize_stock_symbol(code: str, market: str | int | None = None) -> str:
    """Return the final-table A-share symbol format."""
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
        if market_text in {"bj"} or raw.startswith(("4", "8")) or raw.startswith("92"):
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


# ============================================================
# 通达信相关
# ============================================================

def get_tdx_api():
    from pytdx.hq import TdxHq_API
    for host, port in TDX_SERVERS:
        try:
            api = TdxHq_API()
            result = api.connect(host, port)
            if result:
                log.info(f"通达信连接成功: {host}:{port}")
                return api
        except Exception:
            continue
    raise RuntimeError("无法连接通达信服务器")


def get_all_a_stocks_from_tdx(api):
    """从通达信获取全量A股列表（深市+沪市，不含北交所）"""
    stocks = []
    # 深市 market=0
    for start in range(0, 8000, 1000):
        data = api.get_security_list(0, start)
        if not data:
            break
        for s in data:
            code = s["code"]
            if code.startswith(("000", "001", "002", "003", "300", "301")):
                stocks.append((0, code, s["name"]))
    # 沪市 market=1
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


# ============================================================
# 东方财富相关（北交所）
# ============================================================

EM_MINUTE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "*/*",
}


def fetch_bj_minute_kline_em(code, start_date, end_date, max_retries=3):
    """从东方财富获取北交所1分钟K线"""
    import urllib.request
    import json

    secid = f"0.{code}"
    params = (
        f"secid={secid}"
        f"&fields1=f1,f2,f3,f4,f5,f6"
        f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        f"&klt=1&fqt=0"
        f"&beg={start_date}&end={end_date}"
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
            rows = []
            for kline_str in klines:
                parts = kline_str.split(",")
                if len(parts) < 7:
                    continue
                try:
                    trade_time = datetime.strptime(parts[0], "%Y-%m-%d %H:%M")
                except ValueError:
                    continue
                open_p = float(parts[1]) if parts[1] else 0
                close_p = float(parts[2]) if parts[2] else 0
                high_p = float(parts[3]) if parts[3] else 0
                low_p = float(parts[4]) if parts[4] else 0
                vol = int(float(parts[5])) if parts[5] else 0
                amt = float(parts[6]) if parts[6] else 0
                symbol = normalize_stock_symbol(code, "bj")
                rows.append((symbol, trade_time, open_p, high_p, low_p, close_p, vol, amt))
            return rows
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep((attempt + 1) * 2)
            else:
                log.warning(f"  {code} 东方财富获取失败: {e}")
                return []


# ============================================================
# 数据库相关
# ============================================================

def get_trading_days(start_date, end_date):
    """从日线表获取交易日历"""
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


def get_missing_stocks():
    """获取日线有但分钟线缺失的股票列表（统一为纯数字代码）"""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    # 日线中所有活跃股票 - 统一去重为纯数字代码
    cur.execute("""
        SELECT DISTINCT symbol FROM stock_daily_kline
        WHERE trade_date >= '2026-04-01'
    """)
    daily_raw = {row[0] for row in cur.fetchall()}

    # 统一为纯数字代码 + 市场分类
    daily_codes = {}  # code -> 'sz'/'sh'/'bj'
    for sym in daily_raw:
        if sym.startswith('bj'):
            code = sym[2:]
            daily_codes[code] = 'bj'
        elif sym.endswith('.BJ'):
            code = sym.replace('.BJ', '')
            daily_codes[code] = 'bj'
        elif sym.endswith('.SZ'):
            code = sym.replace('.SZ', '')
            if code not in daily_codes or daily_codes[code] == 'sz':
                daily_codes[code] = 'sz'
        elif sym.endswith('.SH'):
            code = sym.replace('.SH', '')
            if code not in daily_codes or daily_codes[code] == 'sh':
                daily_codes[code] = 'sh'
        else:
            # 纯数字，根据前缀推断市场
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

    # 分钟线中已有的股票 - 查所有有数据的symbol
    # 用高效方式：查分钟线中所有distinct symbol（利用索引）
    # 分两步：先查最近的（快），再查历史的（可能慢但只查不在最近的）
    cur.execute("""
        SELECT DISTINCT symbol FROM stock_minute_kline
        WHERE trade_time >= '2026-04-28' AND trade_time < '2026-04-29'
    """)
    minute_recent = {row[0] for row in cur.fetchall()}

    # 补充：查分钟线中所有有数据但最近不在的symbol
    # 用更高效的方式 - 查最近6个月的数据
    cur.execute("""
        SELECT DISTINCT symbol FROM stock_minute_kline
        WHERE trade_time >= '2026-01-01'
        AND symbol NOT IN %s
    """, (tuple(minute_recent) if minute_recent else ('__none__',),))
    minute_6m = {row[0] for row in cur.fetchall()}

    # 再查更早的数据（2020-2025），只查不在已有集合中的
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

    # 找出缺失的
    missing = []
    for code, market in sorted(daily_codes.items()):
        if code not in minute_codes:
            missing.append((code, market))

    return missing


def get_existing_max_time(conn, symbol):
    """获取该股票已有的最大时间"""
    cur = conn.cursor()
    variants = symbol_variants(symbol)
    cur.execute(
        "SELECT MAX(trade_time) FROM stock_minute_kline WHERE symbol = ANY(%s)",
        (list(variants),),
    )
    return cur.fetchone()[0]


def get_existing_dates(conn, symbol):
    """获取该股票已有的交易日"""
    cur = conn.cursor()
    variants = symbol_variants(symbol)
    cur.execute(
        "SELECT DISTINCT DATE(trade_time) FROM stock_minute_kline "
        "WHERE symbol = ANY(%s)",
        (list(variants),),
    )
    return {row[0] for row in cur.fetchall()}


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


# ============================================================
# 数据获取 - 通达信
# ============================================================

def fetch_minute_data_history(api, market, code, date_int):
    """获取指定日期的分时数据（历史，price近似OHLC）"""
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
    """获取最近5个月精确1分钟K线（限制5页=4000条≈17个交易日）"""
    all_bars = []
    for page in range(5):  # 减少到5页，避免超时
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
        if len(data) < 800:
            break
    return all_bars


# ============================================================
# 处理单只股票 - 通达信
# ============================================================

def process_tdx_stock(api, market, code, name, trading_days, start_date_int, end_date_int, resume, is_new=True):
    """处理单只深沪股票。is_new=True表示全新股票，跳过已有数据查询"""
    conn = psycopg2.connect(DB_URL)
    total_inserted = 0
    errors = 0

    try:
        existing_max_time = None
        if resume and not is_new:
            existing_max_time = get_existing_max_time(conn, code)

        # 1. 获取最近数据的精确K线（快速，5页≈17个交易日）
        recent_rows = fetch_recent_bars(api, market, code, existing_max_time)
        if recent_rows:
            inserted = batch_insert(conn, recent_rows)
            total_inserted += inserted

        # 2. 按日获取历史数据（补全recent未覆盖的部分）
        # 计算recent覆盖到的最早日期
        recent_min_date = None
        if recent_rows:
            recent_min_date = min(r[1] for r in recent_rows).date()

        dates_to_fetch = []
        for date_int in trading_days:
            if date_int < start_date_int or date_int > end_date_int:
                continue
            date_str = str(date_int)
            date_obj = datetime.strptime(date_str, "%Y%m%d").date()
            # 跳过recent已覆盖的日期
            if recent_min_date and date_obj >= recent_min_date:
                continue
            # 跳过已有数据
            if existing_max_time and date_obj <= existing_max_time.date():
                continue
            dates_to_fetch.append(date_int)

        if dates_to_fetch:
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

                if len(batch_rows) >= 12000 or idx == len(dates_to_fetch) - 1:
                    if batch_rows:
                        inserted = batch_insert(conn, batch_rows)
                        total_inserted += inserted
                        batch_rows = []

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


# ============================================================
# 处理单只股票 - 北交所
# ============================================================

def process_bj_stock(code, start_date, end_date, resume=True, is_new=True):
    """处理单只北交所股票。is_new=True表示全新股票，跳过已有数据查询"""
    symbol = normalize_stock_symbol(code, "bj")
    conn = psycopg2.connect(DB_URL)
    total_inserted = 0
    errors = 0

    try:
        if resume and not is_new:
            existing_max = get_existing_max_time(conn, symbol)
            if existing_max:
                new_start = (existing_max + timedelta(days=1)).strftime("%Y%m%d")
                if new_start > end_date:
                    return 0, 0
                start_date = new_start

        current_start = datetime.strptime(start_date, "%Y%m%d")
        end_dt = datetime.strptime(end_date, "%Y%m%d")

        while current_start <= end_dt:
            current_end = min(current_start + timedelta(days=30), end_dt)
            start_str = current_start.strftime("%Y%m%d")
            end_str = current_end.strftime("%Y%m%d")

            rows = fetch_bj_minute_kline_em(code, start_str, end_str)
            if rows:
                inserted = batch_insert(conn, rows)
                total_inserted += inserted

            current_start = current_end + timedelta(days=1)
            time.sleep(0.3)

    except Exception as e:
        log.error(f"  {code} 北交所处理失败: {e}")
        errors += 1
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()

    return total_inserted, errors


# ============================================================
# 清理重复数据
# ============================================================

def cleanup_duplicate_symbols():
    """保留旧参数入口，实际清理由专用 dry-run 脚本执行，避免误删大表数据。"""
    log.warning(
        "--cleanup 已停用。请使用 scripts/normalize_stock_minute_symbols.py 先 dry-run，确认后再分批 --apply。"
    )


# ============================================================
# 主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="A股全量1分钟K线数据补全 v3")
    parser.add_argument("--start-date", default="20200101")
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--mode", choices=["tdx", "bj", "all"], default="all",
                        help="tdx=深沪, bj=北交所, all=全部")
    parser.add_argument("--cleanup", action="store_true", help="先清理重复数据")
    parser.add_argument("--limit", type=int, default=0, help="限制股票数量(测试用)")
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", action="store_false", dest="resume")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    start_date = datetime.strptime(args.start_date, "%Y%m%d").date()
    end_date = datetime.strptime(args.end_date, "%Y%m%d").date() if args.end_date else datetime.now().date()
    start_date_int = int(args.start_date)
    end_date_int = int(end_date.strftime("%Y%m%d"))

    log.info("=" * 60)
    log.info("=== A股全量1分钟K线数据补全 v3 ===")
    log.info(f"时间范围: {start_date} ~ {end_date}, 模式: {args.mode}")
    log.info("=" * 60)

    # 1. 清理重复数据
    if args.cleanup:
        cleanup_duplicate_symbols()

    # 2. 获取交易日历
    log.info("获取交易日历...")
    trading_days = get_trading_days(start_date, end_date)
    log.info(f"交易日数: {len(trading_days)}")

    # 3. 获取缺失股票列表
    log.info("分析缺失股票...")
    missing = get_missing_stocks()
    log.info(f"缺失股票总数: {len(missing)}")

    # 分类 - missing是(code, market)元组
    tdx_missing = []  # 深沪股票: (market_int, code)
    bj_missing = []   # 北交所: code
    for code, market in missing:
        if market == 'bj':
            bj_missing.append(code)
        elif market in ('sz', 'sh'):
            # sz -> market=0, sh -> market=1
            mkt = 0 if market == 'sz' else 1
            tdx_missing.append((mkt, code))
        else:
            # unknown - 根据代码前缀推断
            if code.startswith(('000', '001', '002', '003', '300', '301')):
                tdx_missing.append((0, code))
            elif code.startswith(('600', '601', '603', '605', '688', '689')):
                tdx_missing.append((1, code))
            elif code.startswith(('4', '8', '9')):
                bj_missing.append(code)
            else:
                log.warning(f"  未知类型: {code} ({market})")

    log.info(f"  深沪缺失: {len(tdx_missing)} 只")
    log.info(f"  北交所缺失: {len(bj_missing)} 只")

    if args.limit > 0:
        tdx_missing = tdx_missing[:args.limit]
        bj_missing = bj_missing[:args.limit]
        log.info(f"  限制后: 深沪 {len(tdx_missing)}, 北交所 {len(bj_missing)}")

    if args.dry_run:
        log.info("=== DRY RUN ===")
        log.info(f"深沪缺失股票: {[(m,c) for m,c in tdx_missing[:20]]}...")
        log.info(f"北交所缺失股票: {bj_missing[:20]}...")
        return

    total_inserted = 0
    total_errors = 0
    start_time = time.time()

    # 4. 处理深沪股票
    if args.mode in ("tdx", "all") and tdx_missing:
        log.info(f"\n--- 开始处理深沪股票 ({len(tdx_missing)} 只) ---")
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

        for idx, (market, code) in enumerate(tdx_missing):
            if idx % 50 == 0:
                api = ensure_api()

            try:
                inserted, errs = process_tdx_stock(
                    api, market, code, code, trading_days, start_date_int, end_date_int, args.resume
                )
                total_inserted += inserted
                total_errors += errs
            except Exception as e:
                log.error(f"  {code} 异常: {e}")
                total_errors += 1
                try:
                    api.disconnect()
                except Exception:
                    pass
                api = get_tdx_api()

            # 进度
            elapsed = time.time() - start_time
            progress = (idx + 1) / len(tdx_missing)
            eta = elapsed / progress * (1 - progress) if progress > 0 else 0
            if (idx + 1) % 5 == 0 or idx == len(tdx_missing) - 1:
                log.info(
                    f"[深沪] 进度: {idx+1}/{len(tdx_missing)} ({progress:.1%}), "
                    f"已插入: {total_inserted:,}, 耗时: {elapsed/60:.1f}min, "
                    f"预计剩余: {eta/60:.1f}min"
                )

        try:
            api.disconnect()
        except Exception:
            pass

    # 5. 处理北交所股票
    if args.mode in ("bj", "all") and bj_missing:
        log.info(f"\n--- 开始处理北交所股票 ({len(bj_missing)} 只) ---")
        end_date_str = end_date.strftime("%Y%m%d")

        for idx, code in enumerate(bj_missing):
            try:
                inserted, errs = process_bj_stock(
                    code, args.start_date, end_date_str, args.resume
                )
                total_inserted += inserted
                total_errors += errs
            except Exception as e:
                log.error(f"  {code} 北交所异常: {e}")
                total_errors += 1

            elapsed = time.time() - start_time
            progress = (idx + 1) / len(bj_missing)
            eta = elapsed / progress * (1 - progress) if progress > 0 else 0
            if (idx + 1) % 10 == 0 or idx == len(bj_missing) - 1:
                log.info(
                    f"[北交所] 进度: {idx+1}/{len(bj_missing)} ({progress:.1%}), "
                    f"已插入: {total_inserted:,}, 耗时: {elapsed/60:.1f}min, "
                    f"预计剩余: {eta/60:.1f}min"
                )

            time.sleep(0.3)

    # 6. 汇总
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

    # 按板块统计
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
