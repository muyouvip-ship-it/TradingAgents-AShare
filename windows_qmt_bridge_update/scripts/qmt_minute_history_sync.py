from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from api.core.env import load_project_env
except Exception:
    def load_project_env() -> None:
        return None


DEFAULT_OUTPUT_ROOT = Path("data/qmt_minute_history")
DEFAULT_SECTOR = "all_a"
UNIVERSE_ALIASES: dict[str, list[str]] = {
    "all_a": ["沪深京A股", "沪深A股", "深沪A股", "A股"],
    "hs_a": ["沪深A股", "深沪A股", "A股"],
    "bj_a": ["北证A股", "北交所", "北京A股"],
}


@dataclass
class WindowExportResult:
    symbol: str
    start_time: str
    end_time: str
    rows: int
    output_path: str | None
    imported_rows: int
    skipped: bool = False
    error: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="使用 QMT xtdata 下载全市场 1 分钟 K 线，优先落地分区文件，并可选入库 PostgreSQL。")
    parser.add_argument("--period", default="1m", help="K 线周期，默认 1m")
    parser.add_argument("--start-date", default="2000-01-01", help="开始日期，格式 YYYY-MM-DD")
    parser.add_argument("--end-date", default=datetime.now().strftime("%Y-%m-%d"), help="结束日期，格式 YYYY-MM-DD")
    parser.add_argument("--sector", default=DEFAULT_SECTOR, help="股票池别名或 QMT 板块名称，默认 all_a")
    parser.add_argument("--symbols", nargs="*", default=None, help="直接指定股票代码列表，优先级高于 --sector")
    parser.add_argument("--symbols-file", default=None, help="股票列表文件，每行一个代码")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="本地分区文件根目录")
    parser.add_argument("--format", choices=("parquet", "csv"), default="parquet", help="导出文件格式")
    parser.add_argument("--window-days", type=int, default=365, help="按窗口切分历史数据，默认 365 天")
    parser.add_argument("--limit-symbols", type=int, default=0, help="仅处理前 N 只股票，0 表示全部")
    parser.add_argument("--batch-sleep", type=float, default=0.0, help="每只股票之间额外暂停秒数")
    parser.add_argument("--force", action="store_true", help="覆盖已有分区文件")
    parser.add_argument("--import-db", action="store_true", help="导出后同步写入数据库 stock_minute_kline")
    parser.add_argument("--import-existing-only", action="store_true", help="只导入已存在的分区文件，不调用 xtdata 下载")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""), help="数据库连接串，默认读取环境变量 DATABASE_URL")
    parser.add_argument("--manifest-name", default="manifest.jsonl", help="执行清单文件名")
    parser.add_argument("--retry-times", type=int, default=2, help="单个窗口下载失败后的重试次数，默认 2")
    parser.add_argument("--retry-sleep", type=float, default=1.0, help="单个窗口重试间隔秒数，默认 1")
    parser.add_argument("--dry-run", action="store_true", help="只解析股票列表和任务窗口，不执行下载")
    return parser.parse_args()


def main() -> int:
    load_project_env()
    args = parse_args()
    xtdata = _import_xtdata()
    output_root = Path(args.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / args.manifest_name

    symbols = _resolve_symbols(xtdata, args)
    if args.limit_symbols and args.limit_symbols > 0:
        symbols = symbols[: args.limit_symbols]

    if not symbols:
        print("[qmt-minute-sync] 未解析到任何股票列表", file=sys.stderr)
        return 2

    print(f"[qmt-minute-sync] universe={len(symbols)} period={args.period} start={args.start_date} end={args.end_date}")
    windows = list(_iter_time_windows(args.start_date, args.end_date, args.window_days))
    print(f"[qmt-minute-sync] windows={len(windows)} sample_symbols={symbols[:5]}")

    if args.dry_run:
        print("[qmt-minute-sync] dry-run 模式，不执行下载")
        return 0

    engine = None
    if args.import_db:
        database_url = (args.database_url or "").strip()
        if not database_url:
            print("[qmt-minute-sync] --import-db 需要 DATABASE_URL", file=sys.stderr)
            return 2
        try:
            from sqlalchemy import create_engine
        except Exception as exc:
            print(f"[qmt-minute-sync] --import-db 需要 sqlalchemy: {exc}", file=sys.stderr)
            return 2
        engine = create_engine(database_url)
        _ensure_minute_table(engine)

    summary = {
        "symbols_total": len(symbols),
        "windows_total": len(windows),
        "started_at": _iso_now(),
        "period": args.period,
        "output_root": str(output_root),
        "format": args.format,
    }
    _append_manifest(manifest_path, {"type": "run_started", **summary})

    total_rows = 0
    total_imported_rows = 0
    failures = 0

    for index, symbol in enumerate(symbols, start=1):
        print(f"[qmt-minute-sync] ({index}/{len(symbols)}) symbol={symbol}")
        for start_time, end_time in windows:
            result = _process_symbol_window(
                xtdata=xtdata,
                symbol=symbol,
                period=args.period,
                start_time=start_time,
                end_time=end_time,
                output_root=output_root,
                file_format=args.format,
                force=args.force,
                engine=engine,
                import_existing_only=args.import_existing_only,
                retry_times=args.retry_times,
                retry_sleep=args.retry_sleep,
            )
            _append_manifest(manifest_path, {"type": "window", **asdict(result)})
            if result.error:
                failures += 1
                print(f"[qmt-minute-sync] error symbol={symbol} window={start_time}->{end_time}: {result.error}", file=sys.stderr)
            else:
                total_rows += result.rows
                total_imported_rows += result.imported_rows
        if args.batch_sleep > 0:
            time.sleep(args.batch_sleep)

    finished = {
        "type": "run_finished",
        "finished_at": _iso_now(),
        "symbols_total": len(symbols),
        "windows_total": len(windows),
        "rows_total": total_rows,
        "imported_rows_total": total_imported_rows,
        "failures": failures,
    }
    _append_manifest(manifest_path, finished)
    print(json.dumps(finished, ensure_ascii=False, indent=2))
    return 0 if failures == 0 else 1


def _import_xtdata():
    try:
        from xtquant import xtdata
    except Exception as exc:
        raise SystemExit(f"[qmt-minute-sync] xtdata 不可用，请确认已安装 xtquant 且在 QMT Windows 环境执行: {exc}") from exc
    return xtdata


def _resolve_symbols(xtdata: Any, args: argparse.Namespace) -> list[str]:
    if args.symbols:
        return sorted({_normalize_symbol(item) for item in args.symbols if _normalize_symbol(item)})
    if args.symbols_file:
        path = Path(args.symbols_file).expanduser()
        if not path.exists():
            raise SystemExit(f"[qmt-minute-sync] symbols 文件不存在: {path}")
        items = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return sorted({_normalize_symbol(item) for item in items if _normalize_symbol(item)})

    sector_key = str(args.sector or DEFAULT_SECTOR).strip()
    candidates = UNIVERSE_ALIASES.get(sector_key, [sector_key])
    union: set[str] = set()
    errors: list[str] = []
    for candidate in candidates:
        try:
            items = xtdata.get_stock_list_in_sector(candidate) or []
            normalized = {_normalize_symbol(item) for item in items if _normalize_symbol(item)}
            if normalized:
                union.update(normalized)
                print(f"[qmt-minute-sync] sector={candidate} count={len(normalized)}")
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")
    if union:
        return sorted(union)
    if errors:
        raise SystemExit("[qmt-minute-sync] 无法从 QMT 获取股票列表: " + " | ".join(errors))
    return []


def _iter_time_windows(start_date: str, end_date: str, window_days: int):
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    step = max(int(window_days or 365), 1)
    current = start
    while current <= end:
        window_end = min(current + timedelta(days=step - 1), end)
        yield current.strftime("%Y%m%d000000"), window_end.strftime("%Y%m%d235959")
        current = window_end + timedelta(days=1)


def _process_symbol_window(
    *,
    xtdata: Any,
    symbol: str,
    period: str,
    start_time: str,
    end_time: str,
    output_root: Path,
    file_format: str,
    force: bool,
    engine,
    import_existing_only: bool,
    retry_times: int,
    retry_sleep: float,
) -> WindowExportResult:
    output_path = _build_output_path(output_root, symbol, start_time, end_time, file_format)
    if output_path.exists() and not force:
        imported_rows = _import_partition_to_db(output_path, engine, file_format) if engine is not None else 0
        return WindowExportResult(
            symbol=symbol,
            start_time=start_time,
            end_time=end_time,
            rows=0,
            output_path=str(output_path),
            imported_rows=imported_rows,
            skipped=True,
        )
    if import_existing_only:
        return WindowExportResult(
            symbol=symbol,
            start_time=start_time,
            end_time=end_time,
            rows=0,
            output_path=str(output_path),
            imported_rows=0,
            skipped=True,
            error="import_existing_only 模式下分区文件不存在",
        )

    attempts = max(retry_times, 0) + 1
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            _download_history_window(xtdata, symbol, period, start_time, end_time)
            raw = _read_history_window(xtdata, symbol, period, start_time, end_time)
            frame = _normalize_history_frame(raw, symbol)
            if frame.empty:
                return WindowExportResult(symbol=symbol, start_time=start_time, end_time=end_time, rows=0, output_path=None, imported_rows=0)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            _write_partition(frame, output_path, file_format)
            imported_rows = _import_frame_to_db(frame, engine) if engine is not None else 0
            return WindowExportResult(
                symbol=symbol,
                start_time=start_time,
                end_time=end_time,
                rows=len(frame),
                output_path=str(output_path),
                imported_rows=imported_rows,
            )
        except Exception as exc:
            last_error = str(exc)
            if attempt < attempts:
                print(
                    f"[qmt-minute-sync] retry symbol={symbol} window={start_time}->{end_time} attempt={attempt}/{attempts - 1}",
                    file=sys.stderr,
                )
                time.sleep(max(retry_sleep, 0.0))
                continue
    return WindowExportResult(
        symbol=symbol,
        start_time=start_time,
        end_time=end_time,
        rows=0,
        output_path=str(output_path),
        imported_rows=0,
        error=last_error,
    )


def _download_history_window(xtdata: Any, symbol: str, period: str, start_time: str, end_time: str) -> None:
    downloader = getattr(xtdata, "download_history_data2", None) or getattr(xtdata, "download_history_data", None)
    if downloader is None:
        raise RuntimeError("xtdata 未提供 download_history_data / download_history_data2")
    try:
        downloader(symbol, period, start_time=start_time, end_time=end_time)
    except TypeError:
        downloader(symbol, period, start_time, end_time)


def _read_history_window(xtdata: Any, symbol: str, period: str, start_time: str, end_time: str):
    reader = getattr(xtdata, "get_market_data_ex", None) or getattr(xtdata, "get_market_data", None)
    if reader is None:
        raise RuntimeError("xtdata 未提供 get_market_data_ex / get_market_data")
    fields = ["time", "open", "high", "low", "close", "volume", "amount"]
    try:
        return reader(
            field_list=fields,
            stock_list=[symbol],
            period=period,
            start_time=start_time,
            end_time=end_time,
            count=-1,
            dividend_type="none",
            fill_data=False,
        )
    except TypeError:
        return reader(fields, [symbol], period, start_time, end_time, -1, "none", False)


def _normalize_history_frame(payload: Any, symbol: str) -> pd.DataFrame:
    frame = _extract_symbol_frame(payload, symbol)
    if frame is None:
        return pd.DataFrame(columns=["symbol", "trade_time", "open", "high", "low", "close", "volume", "amount"])
    if not isinstance(frame, pd.DataFrame):
        frame = pd.DataFrame(frame)
    data = frame.copy()
    if "time" not in data.columns:
        if isinstance(data.index, pd.DatetimeIndex):
            data = data.reset_index().rename(columns={data.columns[0]: "time"})
        elif "trade_time" in data.columns:
            data["time"] = data["trade_time"]
        elif "datetime" in data.columns:
            data["time"] = data["datetime"]
        elif data.index.name:
            data = data.reset_index().rename(columns={data.index.name: "time"})
    rename_map = {
        "Time": "time",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
        "Amount": "amount",
    }
    data = data.rename(columns=rename_map)
    required = ["time", "open", "high", "low", "close", "volume", "amount"]
    for column in required:
        if column not in data.columns:
            data[column] = None
    data["trade_time"] = data["time"].map(_normalize_time_value)
    data["symbol"] = _normalize_symbol(symbol)
    numeric_columns = ["open", "high", "low", "close", "volume", "amount"]
    for column in numeric_columns:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=["trade_time", "open", "high", "low", "close"], how="any")
    data["trade_time"] = pd.to_datetime(data["trade_time"]).dt.tz_localize(None)
    data["volume"] = data["volume"].fillna(0).astype("int64")
    data["amount"] = data["amount"].fillna(0.0).astype(float)
    data = data.sort_values("trade_time").drop_duplicates(["symbol", "trade_time"], keep="last")
    return data[["symbol", "trade_time", "open", "high", "low", "close", "volume", "amount"]].reset_index(drop=True)


def _extract_symbol_frame(payload: Any, symbol: str) -> pd.DataFrame | None:
    if payload is None:
        return None
    if isinstance(payload, pd.DataFrame):
        return payload
    if isinstance(payload, dict):
        candidates = [symbol, _normalize_symbol(symbol), symbol.split(".")[0], symbol.lower(), _normalize_symbol(symbol).lower()]
        for key in candidates:
            value = payload.get(key)
            if isinstance(value, pd.DataFrame):
                return value
            if isinstance(value, dict):
                return pd.DataFrame(value)
            if isinstance(value, list):
                return pd.DataFrame(value)
        if len(payload) == 1:
            only = next(iter(payload.values()))
            if isinstance(only, pd.DataFrame):
                return only
            if isinstance(only, dict):
                return pd.DataFrame(only)
            if isinstance(only, list):
                return pd.DataFrame(only)
        if any(name in payload for name in ("time", "open", "close")):
            return pd.DataFrame(payload)
    if isinstance(payload, list):
        return pd.DataFrame(payload)
    return None


def _normalize_time_value(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, (int, float)):
        number = int(value)
        digits = len(str(abs(number)))
        if digits >= 18:
            return datetime.fromtimestamp(number / 1_000_000_000.0)
        if digits >= 16:
            return datetime.fromtimestamp(number / 1_000_000.0)
        if digits >= 13:
            return datetime.fromtimestamp(number / 1000.0)
        if digits >= 10:
            return datetime.fromtimestamp(number)
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _build_output_path(output_root: Path, symbol: str, start_time: str, end_time: str, file_format: str) -> Path:
    year = start_time[:4]
    ext = "parquet" if file_format == "parquet" else "csv"
    return output_root / f"period=1m" / f"year={year}" / f"symbol={symbol}" / f"{symbol}_{start_time}_{end_time}.{ext}"


def _write_partition(frame: pd.DataFrame, output_path: Path, file_format: str) -> None:
    if file_format == "parquet":
        frame.to_parquet(output_path, index=False)
        return
    frame.to_csv(output_path, index=False, encoding="utf-8-sig")


def _import_partition_to_db(output_path: Path, engine, file_format: str) -> int:
    if engine is None:
        return 0
    frame = pd.read_parquet(output_path) if file_format == "parquet" else pd.read_csv(output_path, parse_dates=["trade_time"])
    return _import_frame_to_db(frame, engine)


def _ensure_minute_table(engine) -> None:
    try:
        from sqlalchemy import text
    except Exception as exc:
        raise RuntimeError(f"缺少 sqlalchemy，无法创建 minute 表: {exc}") from exc
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS stock_minute_kline (
                    id BIGSERIAL PRIMARY KEY,
                    symbol VARCHAR(20) NOT NULL,
                    trade_time TIMESTAMP NOT NULL,
                    open DOUBLE PRECISION,
                    high DOUBLE PRECISION,
                    low DOUBLE PRECISION,
                    close DOUBLE PRECISION,
                    volume BIGINT,
                    amount DOUBLE PRECISION,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(symbol, trade_time)
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_stock_minute_kline_symbol_time ON stock_minute_kline(symbol, trade_time)"))


def _import_frame_to_db(frame: pd.DataFrame, engine) -> int:
    if engine is None or frame.empty:
        return 0
    dialect = engine.url.get_backend_name()
    if dialect != "postgresql":
        raise RuntimeError(f"当前仅支持 PostgreSQL 批量导入，实际为 {dialect}")

    try:
        import psycopg2.extras
    except Exception as exc:
        raise RuntimeError(f"缺少 psycopg2.extras，无法批量入库: {exc}") from exc

    records = []
    now = datetime.now()
    for row in frame.itertuples(index=False):
        records.append(
            (
                row.symbol,
                row.trade_time.to_pydatetime() if isinstance(row.trade_time, pd.Timestamp) else row.trade_time,
                _safe_float(row.open),
                _safe_float(row.high),
                _safe_float(row.low),
                _safe_float(row.close),
                int(row.volume or 0),
                _safe_float(row.amount),
                now,
                now,
            )
        )
    if not records:
        return 0

    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cursor:
            psycopg2.extras.execute_values(
                cursor,
                """
                INSERT INTO stock_minute_kline (
                    symbol, trade_time, open, high, low, close, volume, amount, created_at, updated_at
                ) VALUES %s
                ON CONFLICT (symbol, trade_time) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    amount = EXCLUDED.amount,
                    updated_at = EXCLUDED.updated_at
                """,
                records,
                page_size=5000,
            )
        raw_conn.commit()
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        raw_conn.close()
    return len(records)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except Exception:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _normalize_symbol(raw: Any) -> str:
    text = str(raw or "").strip().upper()
    if not text:
        return ""
    if "." in text:
        return text
    if len(text) == 6:
        if text.startswith("6"):
            return f"{text}.SH"
        if text.startswith(("0", "3")):
            return f"{text}.SZ"
        if text.startswith(("4", "8")):
            return f"{text}.BJ"
    return text


def _append_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
