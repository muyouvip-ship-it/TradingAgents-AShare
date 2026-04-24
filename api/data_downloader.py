"""
真实数据下载模块 - 使用AKShare下载股票数据
"""

import akshare as ak
import pandas as pd
import inspect
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Awaitable, Callable, List, Optional, Dict, Any
from urllib.parse import urlparse
from sqlalchemy import bindparam, text
import asyncio
import logging
import requests

from api.core.env import load_project_env
from api.core.settings import settings

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
QmtProgressCallback = Callable[[int, str], Awaitable[None] | None]


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

    async def download_minute_kline_from_qmt(
        self,
        *,
        start_date: date,
        end_date: date,
        symbols: Optional[List[str]] = None,
        force: bool = False,
        progress_callback: Optional[QmtProgressCallback] = None,
    ) -> Dict[str, Any]:
        """通过 QMT xtdata 脚本下载 1 分钟 K 线并直接导入 PostgreSQL。"""
        load_project_env()
        script_path = ROOT / "scripts" / "qmt_minute_history_sync.py"
        if not script_path.exists():
            return {"success": False, "records": 0, "error": f"QMT 分钟线脚本不存在: {script_path}"}

        normalized_symbols = [str(item).strip() for item in (symbols or []) if str(item).strip()]
        bridge_config = self._resolve_qmt_history_bridge()
        if bridge_config:
            return await self._download_minute_kline_from_qmt_bridge(
                bridge_config=bridge_config,
                start_date=start_date,
                end_date=end_date,
                symbols=normalized_symbols,
                force=force,
                progress_callback=progress_callback,
            )
        if os.getenv("QMT_ALLOW_LOCAL_HISTORY_SYNC", "0").lower() not in {"1", "true", "yes", "on"}:
            return {
                "success": False,
                "records": 0,
                "error": "未找到 QMT_HISTORY_ACCOUNT_KEY 对应的模拟仓 bridge。为避免误用实盘仓，回测分钟线下载不会回退到其他 QMT 通道。",
            }

        database_url = os.getenv("QMT_MINUTE_DATABASE_URL", os.getenv("DATABASE_URL", "")).strip()
        if not database_url:
            return {"success": False, "records": 0, "error": "QMT_MINUTE_DATABASE_URL / DATABASE_URL 未配置，无法通过 QMT 导入分钟线"}

        before_count = self._count_minute_kline_rows(normalized_symbols, start_date, end_date)

        command = [
            sys.executable,
            str(script_path),
            "--period", "1m",
            "--start-date", start_date.isoformat(),
            "--end-date", end_date.isoformat(),
            "--format", "parquet",
            "--import-db",
            "--database-url", database_url,
            "--retry-times", "2",
            "--retry-sleep", "1",
        ]
        if normalized_symbols:
            command.extend(["--symbols", *normalized_symbols])
        else:
            command.extend(["--sector", "all_a"])
        if force:
            command.append("--force")

        logger.info("开始调用 QMT 分钟线同步脚本: %s", " ".join(command))
        await self._emit_progress(progress_callback, 10, "已启动 QMT 历史分钟线脚本，正在解析股票池")
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(ROOT),
            env=os.environ.copy(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        progress_state: dict[str, int] = {"universe": 0, "windows": 0}
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        async def consume_stdout():
            if process.stdout is None:
                return
            while True:
                raw = await process.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                stdout_lines.append(line)
                await self._handle_qmt_progress_line(line, progress_state, progress_callback)

        async def consume_stderr():
            if process.stderr is None:
                return
            while True:
                raw = await process.stderr.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                stderr_lines.append(line)
                await self._emit_progress(progress_callback, 15, f"QMT 脚本输出告警：{line[:160]}")

        await asyncio.gather(consume_stdout(), consume_stderr())
        returncode = await process.wait()
        stdout = "\n".join(stdout_lines).strip()
        stderr = "\n".join(stderr_lines).strip()
        if returncode != 0:
            message = stderr or stdout or f"QMT 分钟线脚本执行失败，exit_code={returncode}"
            logger.error("QMT 分钟线同步失败: %s", message)
            await self._emit_progress(progress_callback, 0, message)
            return {"success": False, "records": 0, "error": message}

        await self._emit_progress(progress_callback, 92, "QMT 脚本执行完成，正在统计导入结果")
        after_count = self._count_minute_kline_rows(normalized_symbols, start_date, end_date)
        inserted_rows = max(after_count - before_count, 0)
        logger.info("QMT 分钟线同步完成，新增/覆盖区间记录约 %s 条", inserted_rows)
        await self._emit_progress(progress_callback, 100, f"QMT 分钟线导入完成，区间记录约 {inserted_rows} 条")
        return {
            "success": True,
            "records": inserted_rows,
            "stdout": stdout[-4000:] if stdout else None,
        }

    async def _download_minute_kline_from_qmt_bridge(
        self,
        *,
        bridge_config: dict[str, str],
        start_date: date,
        end_date: date,
        symbols: list[str],
        force: bool,
        progress_callback: Optional[QmtProgressCallback],
    ) -> Dict[str, Any]:
        base_url = str(bridge_config.get("bridge_base_url") or "").rstrip("/")
        token = str(bridge_config.get("bridge_token") or "")
        account_key = str(bridge_config.get("account_key") or settings.qmt_history_account_key or "paper_sim").strip()
        account_id = str(bridge_config.get("account_id") or "").strip()
        role = str(bridge_config.get("role") or "paper").strip()
        if not base_url:
            return {"success": False, "records": 0, "error": "QMT bridge_base_url 为空"}

        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        database_url = str(os.getenv("QMT_MINUTE_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
        payload = {
            "period": "1m",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "sector": "all_a",
            "symbols": symbols,
            "file_format": "parquet",
            "import_db": True,
            "database_url": database_url,
            "force": force,
            "window_days": int(os.getenv("QMT_MINUTE_WINDOW_DAYS", "365") or 365),
            "retry_times": 2,
            "retry_sleep": 1,
        }
        request_id = f"qmt-history-{int(time.time())}"
        logger.info(
            "[qmt-audit] action=history_minute_sync.request request_id=%s account_key=%s account_id=%s role=%s bridge_url=%s symbols=%s start=%s end=%s",
            request_id,
            account_key,
            account_id,
            role,
            base_url,
            len(symbols),
            start_date,
            end_date,
        )
        if not database_url:
            return {"success": False, "records": 0, "error": "缺少 QMT_MINUTE_DATABASE_URL / DATABASE_URL，无法让 Windows bridge 导入分钟线"}
        if self._database_url_is_localhost_for_remote_bridge(database_url, base_url):
            return {
                "success": False,
                "records": 0,
                "error": "当前 DATABASE_URL 指向 localhost，Windows QMT bridge 无法用这个地址访问 Mac/PostgreSQL；请配置 QMT_MINUTE_DATABASE_URL 为 Windows 可访问的 PostgreSQL 地址。",
            }

        before_count = self._count_minute_kline_rows(symbols, start_date, end_date)
        await self._emit_progress(progress_callback, 8, f"正在连接 QMT bridge：{base_url}（通道：{account_key} / {role}）")
        try:
            response = await asyncio.to_thread(
                requests.post,
                f"{base_url}/history/minute/sync",
                json=payload,
                headers=headers,
                timeout=20,
            )
            response.raise_for_status()
            job = response.json()
        except Exception as exc:
            logger.info(
                "[qmt-audit] action=history_minute_sync.error request_id=%s account_key=%s role=%s bridge_url=%s error=%s",
                request_id,
                account_key,
                role,
                base_url,
                exc,
            )
            return {"success": False, "records": 0, "error": f"QMT bridge 历史分钟线任务创建失败：{exc}"}

        job_id = str(job.get("job_id") or "")
        if not job_id:
            return {"success": False, "records": 0, "error": f"QMT bridge 未返回 job_id：{job}"}

        timeout_seconds = int(os.getenv("QMT_HISTORY_JOB_TIMEOUT", "86400") or 86400)
        started = time.time()
        last_message = ""
        while True:
            try:
                status_response = await asyncio.to_thread(
                    requests.get,
                    f"{base_url}/history/minute/jobs/{job_id}",
                    headers=headers,
                    timeout=20,
                )
                status_response.raise_for_status()
                job = status_response.json()
            except Exception as exc:
                return {"success": False, "records": 0, "error": f"QMT bridge 历史分钟线状态查询失败：{exc}"}

            status = str(job.get("status") or "").lower()
            progress = int(job.get("progress") or 0)
            message = str(job.get("message") or "")
            if message and message != last_message:
                await self._emit_progress(progress_callback, progress, message)
                last_message = message
            if status == "completed":
                after_count = self._count_minute_kline_rows(symbols, start_date, end_date)
                inserted_rows = max(after_count - before_count, 0)
                bridge_rows = int(job.get("rows_total") or 0)
                logger.info(
                    "[qmt-audit] action=history_minute_sync.success request_id=%s account_key=%s role=%s bridge_url=%s bridge_job_id=%s records=%s",
                    request_id,
                    account_key,
                    role,
                    base_url,
                    job_id,
                    inserted_rows or bridge_rows,
                )
                return {
                    "success": True,
                    "records": inserted_rows or bridge_rows,
                    "bridge_job_id": job_id,
                    "bridge": base_url,
                    "account_key": account_key,
                    "role": role,
                }
            if status == "failed":
                logger.info(
                    "[qmt-audit] action=history_minute_sync.failed request_id=%s account_key=%s role=%s bridge_url=%s bridge_job_id=%s error=%s",
                    request_id,
                    account_key,
                    role,
                    base_url,
                    job_id,
                    job.get("error") or job.get("message"),
                )
                return {
                    "success": False,
                    "records": 0,
                    "error": str(job.get("error") or job.get("message") or "QMT bridge 历史分钟线任务失败"),
                    "bridge_job_id": job_id,
                    "bridge": base_url,
                    "account_key": account_key,
                    "role": role,
                }
            if time.time() - started > timeout_seconds:
                return {"success": False, "records": 0, "error": f"QMT bridge 历史分钟线任务超时：{job_id}", "bridge_job_id": job_id}
            await asyncio.sleep(2)

    @staticmethod
    def _resolve_qmt_history_bridge() -> dict[str, str] | None:
        history_account_key = str(os.getenv("QMT_HISTORY_ACCOUNT_KEY") or settings.qmt_history_account_key or "paper_sim").strip() or "paper_sim"
        explicit_base = str(os.getenv("QMT_HISTORY_BRIDGE_BASE_URL") or "").strip()
        explicit_token = str(os.getenv("QMT_HISTORY_BRIDGE_TOKEN") or os.getenv("QMT_BRIDGE_TOKEN") or "").strip()
        if explicit_base:
            if DataDownloader._bridge_url_looks_live(explicit_base):
                logger.warning("[qmt-audit] QMT_HISTORY_BRIDGE_BASE_URL 指向实盘端口，拒绝用于回测分钟线下载: %s", explicit_base)
                return None
            return {"bridge_base_url": explicit_base, "bridge_token": explicit_token, "account_key": history_account_key, "role": "paper"}
        for account in settings.qmt_accounts():
            if not bool(account.get("enabled", True)):
                continue
            if str(account.get("key") or "").strip() != history_account_key:
                continue
            if str(account.get("role") or "paper").strip().lower() != "paper":
                logger.warning("[qmt-audit] QMT_HISTORY_ACCOUNT_KEY=%s 不是模拟仓，拒绝用于回测分钟线下载", history_account_key)
                return None
            base_url = str(account.get("bridge_base_url") or "").strip()
            if DataDownloader._bridge_url_looks_live(base_url):
                logger.warning("[qmt-audit] QMT_HISTORY_ACCOUNT_KEY=%s 的 bridge 指向实盘端口，拒绝用于回测分钟线下载: %s", history_account_key, base_url)
                return None
            if base_url:
                return {
                    "bridge_base_url": base_url,
                    "bridge_token": str(account.get("bridge_token") or ""),
                    "account_key": str(account.get("key") or history_account_key),
                    "account_id": str(account.get("account_id") or ""),
                    "role": str(account.get("role") or "paper"),
                }
        if not settings.qmt_accounts_json and str(settings.qmt_default_account_key or "paper_sim").strip() == history_account_key:
            base_url = str(settings.qmt_bridge_base_url or "").strip()
            if base_url:
                return {
                    "bridge_base_url": base_url,
                    "bridge_token": str(settings.qmt_bridge_token or ""),
                    "account_key": history_account_key,
                    "account_id": str(settings.qmt_account_id or ""),
                    "role": "paper",
                }
        logger.warning("[qmt-audit] 未找到 QMT_HISTORY_ACCOUNT_KEY=%s 对应的模拟仓 bridge，回测分钟线不会回退到其他 QMT 账户", history_account_key)
        return None

    @staticmethod
    def _bridge_url_looks_live(bridge_base_url: str) -> bool:
        try:
            parsed = urlparse(str(bridge_base_url or ""))
            return parsed.port == 8711
        except Exception:
            return ":8711" in str(bridge_base_url or "")

    @staticmethod
    def _database_url_is_localhost_for_remote_bridge(database_url: str, bridge_base_url: str) -> bool:
        try:
            db_host = (urlparse(database_url).hostname or "").lower()
            bridge_host = (urlparse(bridge_base_url).hostname or "").lower()
        except Exception:
            return False
        local_hosts = {"localhost", "127.0.0.1", "::1"}
        return db_host in local_hosts and bridge_host not in local_hosts

    async def _handle_qmt_progress_line(
        self,
        line: str,
        progress_state: dict[str, int],
        progress_callback: Optional[QmtProgressCallback],
    ) -> None:
        universe_match = re.search(r"universe=(\d+)", line)
        windows_match = re.search(r"windows=(\d+)", line)
        symbol_match = re.search(r"\((\d+)/(\d+)\)\s+symbol=([A-Z0-9.]+)", line)

        if universe_match:
            progress_state["universe"] = int(universe_match.group(1))
            await self._emit_progress(progress_callback, 12, f"已解析股票池，共 {progress_state['universe']} 只股票")
            return
        if windows_match:
            progress_state["windows"] = int(windows_match.group(1))
            await self._emit_progress(progress_callback, 16, f"已拆分下载窗口，共 {progress_state['windows']} 个时间窗口")
            return
        if symbol_match:
            current = int(symbol_match.group(1))
            total = int(symbol_match.group(2))
            symbol = symbol_match.group(3)
            progress = 20 + int((current / max(total, 1)) * 68)
            await self._emit_progress(progress_callback, min(progress, 88), f"QMT 正在处理第 {current}/{total} 只股票：{symbol}")
            return
        if "retry symbol=" in line:
            await self._emit_progress(progress_callback, 30, line.replace("[qmt-minute-sync] ", ""))
            return
        if "dry-run 模式" in line:
            await self._emit_progress(progress_callback, 25, "QMT 脚本当前处于 dry-run 模式")
            return

    async def _emit_progress(
        self,
        callback: Optional[QmtProgressCallback],
        progress: int,
        message: str,
    ) -> None:
        if callback is None:
            return
        result = callback(progress, message)
        if inspect.isawaitable(result):
            await result

    def _count_minute_kline_rows(self, symbols: List[str], start_date: date, end_date: date) -> int:
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())
        variants = sorted({variant for symbol in symbols for variant in self._minute_symbol_variants(symbol)})
        try:
            if variants:
                query = text(
                    """
                    SELECT COUNT(*) AS count
                    FROM stock_minute_kline
                    WHERE trade_time >= :start_dt
                      AND trade_time < :end_dt
                      AND symbol IN :symbols
                    """
                ).bindparams(bindparam("symbols", expanding=True))
            else:
                query = text(
                    """
                    SELECT COUNT(*) AS count
                    FROM stock_minute_kline
                    WHERE trade_time >= :start_dt
                      AND trade_time < :end_dt
                    """
                )
            if variants:
                row = self.db.execute(query, {"start_dt": start_dt, "end_dt": end_dt, "symbols": variants}).fetchone()
            else:
                row = self.db.execute(query, {"start_dt": start_dt, "end_dt": end_dt}).fetchone()
            return int(row[0] or 0) if row else 0
        except Exception as exc:
            logger.warning("统计分钟线记录数失败: %s", exc)
            return 0

    @staticmethod
    def _minute_symbol_variants(symbol: str) -> List[str]:
        text_symbol = str(symbol or "").strip().upper()
        if not text_symbol:
            return []
        variants = {text_symbol}
        bare = text_symbol.split(".", 1)[0]
        variants.add(bare)
        if "." not in text_symbol and len(bare) == 6:
            if bare.startswith("6"):
                variants.add(f"{bare}.SH")
            elif bare.startswith(("0", "3")):
                variants.add(f"{bare}.SZ")
            elif bare.startswith(("4", "8")):
                variants.add(f"{bare}.BJ")
        return sorted(variants)
    
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
