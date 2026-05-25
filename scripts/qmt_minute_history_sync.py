from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing as mp
import os
import queue
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

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
EXCLUDED_STOCK_SYMBOLS = {
    "000001.SH",
    "399001.SZ",
    "399006.SZ",
    "000300.SH",
    "000905.SH",
    "000852.SH",
    "000688.SH",
    "899050.BJ",
}
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


@dataclass
class SymbolSyncSummary:
    symbol: str
    rows: int
    imported_rows: int
    windows: int
    empty_windows: int
    failed_windows: int
    status: str
    first_success_start: str | None = None
    last_success_end: str | None = None


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
    parser.add_argument("--skip-export", action="store_true", help="不写项目分区文件，直接从 QMT 读取后入库")
    parser.add_argument("--import-existing-only", action="store_true", help="只导入已存在的分区文件，不调用 xtdata 下载")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""), help="数据库连接串，默认读取环境变量 DATABASE_URL")
    parser.add_argument("--manifest-name", default="manifest.jsonl", help="执行清单文件名")
    parser.add_argument("--retry-times", type=int, default=2, help="单个窗口下载失败后的重试次数，默认 2")
    parser.add_argument("--retry-sleep", type=float, default=1.0, help="单个窗口重试间隔秒数，默认 1")
    resume_default = str(os.getenv("QMT_MINUTE_RESUME", "1")).strip().lower() not in {"0", "false", "no", "off"}
    parser.set_defaults(resume=resume_default)
    parser.add_argument("--resume", dest="resume", action="store_true", help="根据 manifest 跳过已完成股票，默认开启")
    parser.add_argument("--no-resume", dest="resume", action="store_false", help="忽略 manifest，重新处理全部股票")
    parser.add_argument(
        "--max-empty-symbols",
        type=int,
        default=int(os.getenv("QMT_MINUTE_MAX_EMPTY_SYMBOLS", "0") or 0),
        help="允许整只股票全程无分钟线数据的最大数量，超过则任务失败，默认 0",
    )
    parser.add_argument(
        "--window-timeout-seconds",
        type=float,
        default=float(os.getenv("QMT_MINUTE_WINDOW_TIMEOUT_SECONDS", "120")),
        help="单只股票处理过程中允许的最大无进度秒数，超时后终止该股票子进程并跳过剩余窗口，默认 120",
    )
    parser.add_argument(
        "--max-failed-windows-per-symbol",
        type=int,
        default=int(os.getenv("QMT_MINUTE_MAX_FAILED_WINDOWS_PER_SYMBOL", "4") or 4),
        help="单只股票允许失败窗口数上限，达到后提前跳过剩余窗口，默认 4",
    )
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
    requested_symbols = list(symbols)

    if not symbols:
        print("[qmt-minute-sync] 未解析到任何股票列表", file=sys.stderr)
        return 2

    windows = list(_iter_time_windows(args.start_date, args.end_date, args.window_days))
    run_id = uuid4().hex
    run_config = _build_run_config(args, requested_symbols)
    resumed_completed_symbols: set[str] = set()
    if args.resume and not args.force:
        resumed_completed_symbols = _load_completed_symbols_from_manifest(manifest_path, run_config)
        if resumed_completed_symbols:
            symbols = [symbol for symbol in symbols if symbol not in resumed_completed_symbols]
            print(
                f"[qmt-minute-sync] resume matched completed_symbols={len(resumed_completed_symbols)} "
                f"remaining={len(symbols)}"
            )
    print(f"[qmt-minute-sync] universe={len(symbols)} period={args.period} start={args.start_date} end={args.end_date}")
    print(f"[qmt-minute-sync] windows={len(windows)} sample_symbols={symbols[:5]}")

    if args.dry_run:
        print("[qmt-minute-sync] dry-run 模式，不执行下载")
        return 0

    if args.skip_export and not args.import_db:
        print("[qmt-minute-sync] --skip-export 需要与 --import-db 一起使用", file=sys.stderr)
        return 2

    engine = None
    database_url = ""
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
        "run_id": run_id,
        "run_config": run_config,
        "symbols_requested": len(requested_symbols),
        "symbols_total": len(symbols),
        "symbols_skipped_resume": len(resumed_completed_symbols),
        "windows_total": len(windows),
        "started_at": _iso_now(),
        "period": args.period,
        "output_root": str(output_root),
        "format": args.format,
        "skip_export": bool(args.skip_export),
        "resume": bool(args.resume),
    }
    _append_manifest(manifest_path, {"type": "run_started", **summary})

    if not symbols:
        finished = {
            "type": "run_finished",
            "run_id": run_id,
            "run_config": run_config,
            "finished_at": _iso_now(),
            "symbols_requested": len(requested_symbols),
            "symbols_total": 0,
            "symbols_skipped_resume": len(resumed_completed_symbols),
            "windows_total": len(windows),
            "rows_total": 0,
            "imported_rows_total": 0,
            "failures": 0,
            "symbol_failures": 0,
            "nonempty_symbols": 0,
            "empty_symbols": 0,
            "partial_symbols": 0,
            "zero_row_symbols_sample": [],
            "partial_symbols_sample": [],
            "skip_export": bool(args.skip_export),
        }
        _append_manifest(manifest_path, finished)
        print(json.dumps(finished, ensure_ascii=False, indent=2))
        return 0

    total_rows = 0
    total_imported_rows = 0
    failures = 0
    symbol_failures = 0
    zero_row_symbols: list[str] = []
    partial_symbols: list[str] = []

    for index, symbol in enumerate(symbols, start=1):
        print(f"[qmt-minute-sync] ({index}/{len(symbols)}) symbol={symbol}")
        symbol_rows = 0
        symbol_imported_rows = 0
        symbol_empty_windows = 0
        symbol_failed_windows = 0
        first_success_start: str | None = None
        last_success_end: str | None = None
        symbol_results = _process_symbol_in_subprocess(
            symbol=symbol,
            period=args.period,
            windows=windows,
            output_root=output_root,
            file_format=args.format,
            force=args.force,
            import_db=args.import_db,
            database_url=database_url,
            skip_export=args.skip_export,
            import_existing_only=args.import_existing_only,
            retry_times=args.retry_times,
            retry_sleep=args.retry_sleep,
            no_progress_timeout_seconds=args.window_timeout_seconds,
            max_failed_windows_per_symbol=args.max_failed_windows_per_symbol,
        )
        for result in symbol_results:
            _append_manifest(manifest_path, {"type": "window", "run_id": run_id, **asdict(result)})
            if result.error:
                failures += 1
                symbol_failed_windows += 1
                print(
                    f"[qmt-minute-sync] error symbol={symbol} window={result.start_time}->{result.end_time}: {result.error}",
                    file=sys.stderr,
                )
            else:
                total_rows += result.rows
                total_imported_rows += result.imported_rows
                symbol_rows += result.rows
                symbol_imported_rows += result.imported_rows
                if result.rows <= 0 and result.imported_rows <= 0:
                    symbol_empty_windows += 1
                else:
                    if first_success_start is None:
                        first_success_start = result.start_time
                    last_success_end = result.end_time
        symbol_status = "ok"
        if symbol_rows <= 0 and symbol_imported_rows <= 0:
            symbol_status = "empty"
            symbol_failures += 1
            zero_row_symbols.append(symbol)
            print(f"[qmt-minute-sync] empty symbol={symbol} across {len(windows)} windows", file=sys.stderr)
        elif symbol_failed_windows > 0 or symbol_empty_windows > 0:
            symbol_status = "partial" if symbol_failed_windows > 0 else "ok"
        if symbol_status == "partial":
            partial_symbols.append(symbol)
        symbol_summary = SymbolSyncSummary(
            symbol=symbol,
            rows=symbol_rows,
            imported_rows=symbol_imported_rows,
            windows=len(windows),
            empty_windows=symbol_empty_windows,
            failed_windows=symbol_failed_windows,
            status=symbol_status,
            first_success_start=first_success_start,
            last_success_end=last_success_end,
        )
        _append_manifest(manifest_path, {"type": "symbol", "run_id": run_id, **asdict(symbol_summary)})
        if args.batch_sleep > 0:
            time.sleep(args.batch_sleep)

    finished = {
        "type": "run_finished",
        "run_id": run_id,
        "run_config": run_config,
        "finished_at": _iso_now(),
        "symbols_requested": len(requested_symbols),
        "symbols_total": len(symbols),
        "symbols_skipped_resume": len(resumed_completed_symbols),
        "windows_total": len(windows),
        "rows_total": total_rows,
        "imported_rows_total": total_imported_rows,
        "failures": failures,
        "symbol_failures": symbol_failures,
        "nonempty_symbols": len(symbols) - len(zero_row_symbols),
        "empty_symbols": len(zero_row_symbols),
        "partial_symbols": len(partial_symbols),
        "zero_row_symbols_sample": zero_row_symbols[:50],
        "partial_symbols_sample": partial_symbols[:50],
        "skip_export": bool(args.skip_export),
        "max_empty_symbols": int(args.max_empty_symbols),
        "empty_symbol_limit_exceeded": len(zero_row_symbols) > int(args.max_empty_symbols),
    }
    _append_manifest(manifest_path, finished)
    print(json.dumps(finished, ensure_ascii=False, indent=2))
    if failures > 0:
        return 1
    if len(zero_row_symbols) > int(args.max_empty_symbols):
        print(
            f"[qmt-minute-sync] empty symbol count exceeded limit: empty_symbols={len(zero_row_symbols)} "
            f"limit={int(args.max_empty_symbols)} sample={zero_row_symbols[:10]}",
            file=sys.stderr,
        )
        return 2
    return 0


def _import_xtdata():
    try:
        from xtquant import xtdata
    except Exception as exc:
        raise SystemExit(f"[qmt-minute-sync] xtdata 不可用，请确认已安装 xtquant 且在 QMT Windows 环境执行: {exc}") from exc
    if hasattr(xtdata, "enable_hello"):
        try:
            xtdata.enable_hello = False
        except Exception:
            pass
    return xtdata


def _build_run_config(args: argparse.Namespace, symbols: list[str]) -> dict[str, Any]:
    digest = hashlib.sha1("\n".join(symbols).encode("utf-8")).hexdigest() if symbols else ""
    return {
        "period": args.period,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "sector": args.sector,
        "window_days": int(args.window_days),
        "file_format": args.format,
        "import_db": bool(args.import_db),
        "skip_export": bool(args.skip_export),
        "symbols_total": len(symbols),
        "symbols_sha1": digest,
    }


def _load_completed_symbols_from_manifest(path: Path, run_config: dict[str, Any]) -> set[str]:
    if not path.exists():
        return set()
    matching_run_ids: set[str] = set()
    latest_status_by_symbol: dict[str, bool] = {}
    with path.open("r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            record_type = str(payload.get("type") or "")
            if record_type == "run_started" and payload.get("run_config") == run_config:
                run_id = str(payload.get("run_id") or "").strip()
                if run_id:
                    matching_run_ids.add(run_id)
                continue
            if record_type != "symbol":
                continue
            run_id = str(payload.get("run_id") or "").strip()
            if run_id not in matching_run_ids:
                continue
            symbol = str(payload.get("symbol") or "").strip()
            if not symbol:
                continue
            status = str(payload.get("status") or "").strip().lower()
            failed_windows = int(payload.get("failed_windows") or 0)
            latest_status_by_symbol[symbol] = failed_windows == 0 and status in {"ok", "empty"}
    return {symbol for symbol, completed in latest_status_by_symbol.items() if completed}


def _resolve_symbols(xtdata: Any, args: argparse.Namespace) -> list[str]:
    if args.symbols:
        return sorted({
            normalized
            for item in args.symbols
            if (normalized := _normalize_symbol(item)) and normalized not in EXCLUDED_STOCK_SYMBOLS
        })
    if args.symbols_file:
        path = Path(args.symbols_file).expanduser()
        if not path.exists():
            raise SystemExit(f"[qmt-minute-sync] symbols 文件不存在: {path}")
        items = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return sorted({
            normalized
            for item in items
            if (normalized := _normalize_symbol(item)) and normalized not in EXCLUDED_STOCK_SYMBOLS
        })

    sector_key = str(args.sector or DEFAULT_SECTOR).strip()
    candidates = UNIVERSE_ALIASES.get(sector_key, [sector_key])
    union: set[str] = set()
    errors: list[str] = []
    for candidate in candidates:
        try:
            items = xtdata.get_stock_list_in_sector(candidate) or []
            normalized = {_normalize_symbol(item) for item in items if _normalize_symbol(item)}
            if normalized:
                filtered = {item for item in normalized if item not in EXCLUDED_STOCK_SYMBOLS}
                union.update(filtered)
                print(f"[qmt-minute-sync] sector={candidate} count={len(filtered)} excluded={len(normalized) - len(filtered)}")
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


def _process_symbol_in_subprocess(
    *,
    symbol: str,
    period: str,
    windows: list[tuple[str, str]],
    output_root: Path,
    file_format: str,
    force: bool,
    import_db: bool,
    database_url: str,
    skip_export: bool,
    import_existing_only: bool,
    retry_times: int,
    retry_sleep: float,
    no_progress_timeout_seconds: float,
    max_failed_windows_per_symbol: int,
) -> list[WindowExportResult]:
    ctx = mp.get_context("spawn")
    event_queue: mp.Queue = ctx.Queue()
    worker_payload = {
        "symbol": symbol,
        "period": period,
        "windows": windows,
        "output_root": str(output_root),
        "file_format": file_format,
        "force": force,
        "import_db": import_db,
        "database_url": database_url,
        "skip_export": skip_export,
        "import_existing_only": import_existing_only,
        "retry_times": retry_times,
        "retry_sleep": retry_sleep,
        "max_failed_windows_per_symbol": max_failed_windows_per_symbol,
    }
    process = ctx.Process(target=_symbol_worker_entry, args=(worker_payload, event_queue))
    process.start()

    results: dict[int, WindowExportResult] = {}
    current_window_index: int | None = None
    last_progress_at = time.monotonic()
    aborted_reason: str | None = None

    while True:
        if not process.is_alive() and event_queue.empty():
            break
        try:
            event = event_queue.get(timeout=max(no_progress_timeout_seconds, 1.0))
            last_progress_at = time.monotonic()
        except queue.Empty:
            timeout_seconds = max(no_progress_timeout_seconds, 1.0)
            aborted_reason = (
                f"symbol worker timeout after {timeout_seconds:.0f}s with no progress"
                f" symbol={symbol} current_window_index={current_window_index if current_window_index is not None else 'unknown'}"
            )
            print(f"[qmt-minute-sync] {aborted_reason}", file=sys.stderr)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=2)
            break

        event_type = str(event.get("type") or "").strip()
        if event_type == "window_started":
            current_window_index = int(event["window_index"])
            continue
        if event_type == "window_result":
            current_window_index = None
            window_index = int(event["window_index"])
            results[window_index] = WindowExportResult(**event["result"])
            continue
        if event_type == "symbol_aborted":
            aborted_reason = str(event.get("reason") or f"symbol aborted: {symbol}")
            break
        if event_type == "worker_error":
            aborted_reason = str(event.get("error") or f"symbol worker error: {symbol}")
            break
        if event_type == "symbol_done":
            break

    process.join(timeout=5)
    if process.is_alive():
        process.terminate()
        process.join(timeout=2)
    if process.is_alive():
        process.kill()
        process.join(timeout=2)

    if aborted_reason is None and process.exitcode not in (0, None):
        aborted_reason = f"symbol worker exitcode={process.exitcode} symbol={symbol}"

    if aborted_reason:
        next_index = current_window_index
        if next_index is None:
            next_index = _first_missing_window_index(results, len(windows))
        if next_index is None:
            next_index = len(windows)
        for window_index in range(next_index, len(windows)):
            if window_index in results:
                continue
            start_time, end_time = windows[window_index]
            results[window_index] = WindowExportResult(
                symbol=symbol,
                start_time=start_time,
                end_time=end_time,
                rows=0,
                output_path=str(_build_output_path(output_root, symbol, start_time, end_time, file_format)),
                imported_rows=0,
                error=aborted_reason,
            )

    ordered_results: list[WindowExportResult] = []
    for window_index, (start_time, end_time) in enumerate(windows):
        result = results.get(window_index)
        if result is None:
            result = WindowExportResult(
                symbol=symbol,
                start_time=start_time,
                end_time=end_time,
                rows=0,
                output_path=str(_build_output_path(output_root, symbol, start_time, end_time, file_format)),
                imported_rows=0,
                error=f"missing worker result symbol={symbol} window={start_time}->{end_time}",
            )
        ordered_results.append(result)
    return ordered_results


def _first_missing_window_index(results: dict[int, WindowExportResult], total_windows: int) -> int | None:
    for window_index in range(total_windows):
        if window_index not in results:
            return window_index
    return None


def _symbol_worker_entry(worker_payload: dict[str, Any], event_queue) -> None:
    try:
        load_project_env()
        xtdata = _import_xtdata()
        engine = None
        if bool(worker_payload.get("import_db")):
            from sqlalchemy import create_engine

            database_url = str(worker_payload.get("database_url") or "").strip()
            if not database_url:
                raise RuntimeError("import_db=True but database_url is empty")
            engine = create_engine(database_url)

        symbol = str(worker_payload["symbol"])
        period = str(worker_payload["period"])
        windows = [(str(start_time), str(end_time)) for start_time, end_time in (worker_payload.get("windows") or [])]
        output_root = Path(str(worker_payload["output_root"])).expanduser().resolve()
        file_format = str(worker_payload["file_format"])
        force = bool(worker_payload.get("force"))
        skip_export = bool(worker_payload.get("skip_export"))
        import_existing_only = bool(worker_payload.get("import_existing_only"))
        retry_times = int(worker_payload.get("retry_times") or 0)
        retry_sleep = float(worker_payload.get("retry_sleep") or 0.0)
        max_failed_windows_per_symbol = int(worker_payload.get("max_failed_windows_per_symbol") or 0)

        failed_windows = 0
        for window_index, (start_time, end_time) in enumerate(windows):
            event_queue.put({
                "type": "window_started",
                "window_index": window_index,
                "symbol": symbol,
                "start_time": start_time,
                "end_time": end_time,
            })
            result = _process_symbol_window(
                xtdata=xtdata,
                symbol=symbol,
                period=period,
                start_time=start_time,
                end_time=end_time,
                output_root=output_root,
                file_format=file_format,
                force=force,
                engine=engine,
                skip_export=skip_export,
                import_existing_only=import_existing_only,
                retry_times=retry_times,
                retry_sleep=retry_sleep,
            )
            event_queue.put({
                "type": "window_result",
                "window_index": window_index,
                "result": asdict(result),
            })
            if result.error:
                failed_windows += 1
                if max_failed_windows_per_symbol > 0 and failed_windows >= max_failed_windows_per_symbol:
                    event_queue.put({
                        "type": "symbol_aborted",
                        "reason": (
                            f"symbol exceeded failed window limit={max_failed_windows_per_symbol} "
                            f"symbol={symbol} after window={start_time}->{end_time}"
                        ),
                    })
                    return
        event_queue.put({"type": "symbol_done"})
    except Exception as exc:
        event_queue.put({
            "type": "worker_error",
            "error": f"{exc}\n{traceback.format_exc(limit=5)}",
        })


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
    skip_export: bool,
    import_existing_only: bool,
    retry_times: int,
    retry_sleep: float,
) -> WindowExportResult:
    output_path = _build_output_path(output_root, symbol, start_time, end_time, file_format)
    if not skip_export and output_path.exists() and not force:
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
            raw = _fetch_window_frame(xtdata, symbol, period, start_time, end_time)
            frame = _normalize_history_frame(raw, symbol)
            if frame.empty:
                return WindowExportResult(symbol=symbol, start_time=start_time, end_time=end_time, rows=0, output_path=None, imported_rows=0)
            final_output_path: str | None = None
            if not skip_export:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                _write_partition(frame, output_path, file_format)
                final_output_path = str(output_path)
            imported_rows = _import_frame_to_db(frame, engine) if engine is not None else 0
            return WindowExportResult(
                symbol=symbol,
                start_time=start_time,
                end_time=end_time,
                rows=len(frame),
                output_path=final_output_path,
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


def _fetch_window_frame(xtdata: Any, symbol: str, period: str, start_time: str, end_time: str):
    _download_history_window(xtdata, symbol, period, start_time, end_time)
    return _read_history_window(xtdata, symbol, period, start_time, end_time)


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
        from sqlalchemy import inspect, text
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
        inspector = inspect(conn)
        if inspector.has_table("stock_minute_kline"):
            columns = {column["name"] for column in inspector.get_columns("stock_minute_kline")}
            if "created_at" not in columns:
                conn.execute(text("ALTER TABLE stock_minute_kline ADD COLUMN created_at TIMESTAMP DEFAULT NOW()"))
            if "updated_at" not in columns:
                conn.execute(text("ALTER TABLE stock_minute_kline ADD COLUMN updated_at TIMESTAMP DEFAULT NOW()"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_minute_time ON stock_minute_kline(trade_time)"))


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

    minute_columns = _get_minute_table_columns(engine)
    has_created_at = "created_at" in minute_columns
    has_updated_at = "updated_at" in minute_columns

    records = []
    now = datetime.now()
    for row in frame.itertuples(index=False):
        record = [
            row.symbol,
            row.trade_time.to_pydatetime() if isinstance(row.trade_time, pd.Timestamp) else row.trade_time,
            _safe_float(row.open),
            _safe_float(row.high),
            _safe_float(row.low),
            _safe_float(row.close),
            int(row.volume or 0),
            _safe_float(row.amount),
        ]
        if has_created_at:
            record.append(now)
        if has_updated_at:
            record.append(now)
        records.append(tuple(record))
    if not records:
        return 0

    insert_columns = [
        "symbol",
        "trade_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    ]
    if has_created_at:
        insert_columns.append("created_at")
    if has_updated_at:
        insert_columns.append("updated_at")

    update_columns = [
        "open = EXCLUDED.open",
        "high = EXCLUDED.high",
        "low = EXCLUDED.low",
        "close = EXCLUDED.close",
        "volume = EXCLUDED.volume",
        "amount = EXCLUDED.amount",
    ]
    if has_updated_at:
        update_columns.append("updated_at = EXCLUDED.updated_at")

    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cursor:
            psycopg2.extras.execute_values(
                cursor,
                f"""
                INSERT INTO stock_minute_kline (
                    {", ".join(insert_columns)}
                ) VALUES %s
                ON CONFLICT (symbol, trade_time) DO UPDATE SET
                    {", ".join(update_columns)}
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


def _get_minute_table_columns(engine) -> set[str]:
    try:
        from sqlalchemy import inspect
    except Exception as exc:
        raise RuntimeError(f"缺少 sqlalchemy.inspect，无法读取 minute 表结构: {exc}") from exc
    inspector = inspect(engine)
    if not inspector.has_table("stock_minute_kline"):
        return set()
    return {column["name"] for column in inspector.get_columns("stock_minute_kline")}


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
