"""
策略执行器

负责策略的定时执行、信号生成和通知推送。
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import asyncio

from tradingagents.strategies.manager import get_strategy_manager
from tradingagents.strategies.base.signal import Signal
from tradingagents.dataflows.interface import route_to_vendor

logger = logging.getLogger(__name__)


class StrategyExecutor:
    """策略执行器"""
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.strategy_manager = get_strategy_manager()
        self.active_jobs: Dict[str, List[str]] = {}  # strategy_id -> job_ids
        self.signal_history: Dict[str, List[Signal]] = {}  # strategy_id -> signals
        
    async def start(self):
        """启动调度器"""
        self.scheduler.start()
        logger.info("Strategy executor started")
    
    async def stop(self):
        """停止调度器"""
        self.scheduler.shutdown()
        logger.info("Strategy executor stopped")
    
    def schedule_strategy(
        self,
        strategy_id: str,
        schedule_type: str = "daily",
        schedule_time: str = "09:30",
        symbols: List[str] = None,
        **kwargs
    ) -> str:
        """
        调度策略执行
        
        Args:
            strategy_id: 策略ID
            schedule_type: 调度类型（daily, hourly, custom）
            schedule_time: 执行时间（HH:MM格式）
            symbols: 股票代码列表
            **kwargs: 其他参数
        
        Returns:
            job_id: 任务ID
        """
        # 验证策略是否存在
        strategy = self.strategy_manager.get_strategy(strategy_id)
        if not strategy:
            raise ValueError(f"Strategy not found: {strategy_id}")
        
        # 创建调度任务
        if schedule_type == "daily":
            hour, minute = map(int, schedule_time.split(':'))
            trigger = CronTrigger(hour=hour, minute=minute, day_of_week='mon-fri')
        elif schedule_type == "hourly":
            trigger = CronTrigger(minute=0, day_of_week='mon-fri')
        else:
            # custom cron expression
            trigger = CronTrigger.from_crontab(schedule_time)
        
        job = self.scheduler.add_job(
            self._execute_strategy,
            trigger=trigger,
            args=[strategy_id, symbols, kwargs],
            id=f"{strategy_id}_{datetime.now().timestamp()}",
            name=f"Strategy: {strategy.name}",
            misfire_grace_time=300,
        )
        
        # 记录任务
        if strategy_id not in self.active_jobs:
            self.active_jobs[strategy_id] = []
        self.active_jobs[strategy_id].append(job.id)
        
        logger.info(f"Scheduled strategy {strategy_id} with job_id={job.id}")
        return job.id
    
    def unschedule_strategy(self, job_id: str):
        """取消策略调度"""
        self.scheduler.remove_job(job_id)
        
        # 从记录中移除
        for strategy_id, job_ids in self.active_jobs.items():
            if job_id in job_ids:
                job_ids.remove(job_id)
                break
        
        logger.info(f"Unscheduled job: {job_id}")
    
    async def _execute_strategy(
        self,
        strategy_id: str,
        symbols: List[str],
        kwargs: Dict[str, Any]
    ):
        """执行策略"""
        try:
            logger.info(f"Executing strategy: {strategy_id}")
            
            strategy = self.strategy_manager.get_strategy(strategy_id)
            if not strategy:
                logger.error(f"Strategy not found: {strategy_id}")
                return
            
            all_signals = []
            
            # 对每个股票执行策略
            for symbol in (symbols or []):
                # 获取股票数据
                data = await self._get_stock_data(symbol, days=365)
                
                if data is None or data.empty:
                    logger.warning(f"No data for symbol: {symbol}")
                    continue
                
                # 生成信号
                signals = strategy.generate_signals(data)
                all_signals.extend(signals)
            
            # 保存信号历史
            if strategy_id not in self.signal_history:
                self.signal_history[strategy_id] = []
            self.signal_history[strategy_id].extend(all_signals)
            
            # 发送通知
            if all_signals:
                await self._send_notifications(strategy_id, all_signals)
            
            logger.info(f"Strategy {strategy_id} generated {len(all_signals)} signals")
            
        except Exception as e:
            logger.error(f"Error executing strategy {strategy_id}: {e}", exc_info=True)
    
    async def _get_stock_data(self, symbol: str, days: int = 365) -> Optional[Any]:
        """获取股票数据"""
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            # 使用dataflows获取数据
            data = route_to_vendor(
                method="get_stock_daily",
                symbol=symbol,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            )
            
            return data
        except Exception as e:
            logger.error(f"Error fetching data for {symbol}: {e}")
            return None
    
    async def _send_notifications(self, strategy_id: str, signals: List[Signal]):
        """发送信号通知"""
        try:
            # 这里可以集成飞书、邮件、微信等通知渠道
            # 暂时只记录日志
            for signal in signals[-5:]:  # 只发送最近5个信号
                logger.info(
                    f"Signal: {signal.signal_type.value} {signal.symbol} "
                    f"@ {signal.price:.2f} (confidence: {signal.confidence:.2f})"
                )
        except Exception as e:
            logger.error(f"Error sending notifications: {e}")
    
    def get_active_jobs(self) -> Dict[str, List[str]]:
        """获取活跃的任务"""
        return self.active_jobs
    
    def get_signal_history(self, strategy_id: str) -> List[Signal]:
        """获取信号历史"""
        return self.signal_history.get(strategy_id, [])


# 全局执行器实例
_executor: Optional[StrategyExecutor] = None


def get_executor() -> StrategyExecutor:
    """获取全局执行器实例"""
    global _executor
    if _executor is None:
        _executor = StrategyExecutor()
    return _executor
