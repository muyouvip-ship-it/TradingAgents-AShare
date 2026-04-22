"""
回测数据配置和管理API
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import date, datetime
from typing import List, Optional
import asyncio
import logging

from api.database import get_db, get_db_ctx, UserDB
from api.deps import require_api_user as get_current_user
from api.data_downloader import DataDownloader
from api.quantclass_downloader import QuantClassDownloader
from api.quantclass_importer import import_stock_daily_from_quantclass
from api.data_quality_manager import DataQualityManager
from api.data_source_monitor import get_data_source_monitor
from .backtest_data_models import (
    BacktestDataTaskCreate, BacktestDataTask,
    BacktestDataConfigCreate, BacktestDataConfig,
    BacktestDataStats, BatchDataDownloadRequest,
    BacktestDataTaskListResponse, BacktestDataConfigListResponse,
    BacktestDataStatsListResponse
)

router = APIRouter(prefix="/v1/backtest-data", tags=["backtest-data"])

# 数据源兼容性映射
DATA_SOURCE_COMPATIBILITY = {
    'daily_kline': ['quantclass', 'akshare', 'baostock', 'tushare', 'eastmoney'],
    'minute_kline': ['akshare'],  # 量化课堂不支持1分钟K线
    'index_data': ['quantclass', 'akshare', 'baostock', 'tushare', 'eastmoney'],
    'chip_data': ['quantclass'],  # 只有量化课堂支持
    'financial_data': ['quantclass'],  # 只有量化课堂支持
    'research_reports': ['eastmoney']  # 只有东方财富支持
}

# ========== 数据下载任务API ==========

@router.post("/tasks", response_model=BacktestDataTask)
async def create_backtest_data_task(
    task: BacktestDataTaskCreate,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建回测数据下载任务"""
    try:
        # 插入任务记录
        query = text("""
            INSERT INTO backtest_data_tasks 
            (user_id, task_type, data_source, date_range_start, date_range_end, symbols, status)
            VALUES (:user_id, :task_type, :data_source, :date_range_start, :date_range_end, :symbols, 'pending')
            RETURNING id
        """)
        
        result = db.execute(query, {
            "user_id": current_user.id,
            "task_type": task.task_type,
            "data_source": task.data_source or "akshare",
            "date_range_start": task.date_range_start,
            "date_range_end": task.date_range_end,
            "symbols": task.symbols or []
        })
        task_id = result.fetchone()[0]
        db.commit()
        
        # 获取创建的任务
        task_query = text("""
            SELECT * FROM backtest_data_tasks WHERE id = :task_id
        """)
        task_result = db.execute(task_query, {"task_id": task_id})
        row = task_result.fetchone()
        
        return BacktestDataTask(
            id=row.id,
            user_id=row.user_id,
            task_type=row.task_type,
            data_source=row.data_source,
            date_range_start=row.date_range_start,
            date_range_end=row.date_range_end,
            symbols=row.symbols or [],
            status=row.status,
            progress=row.progress or 0,
            total_records=row.total_records or 0,
            downloaded_records=row.downloaded_records or 0,
            error_message=row.error_message,
            created_at=row.created_at,
            updated_at=row.updated_at,
            completed_at=row.completed_at
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建任务失败: {str(e)}")


@router.get("/tasks", response_model=BacktestDataTaskListResponse)
async def list_backtest_data_tasks(
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100
):
    """获取回测数据下载任务列表"""
    try:
        # 获取任务总数
        count_query = text("""
            SELECT COUNT(*) FROM backtest_data_tasks WHERE user_id = :user_id
        """)
        count_result = db.execute(count_query, {"user_id": current_user.id})
        total = count_result.fetchone()[0]
        
        # 获取任务列表
        tasks_query = text("""
            SELECT * FROM backtest_data_tasks 
            WHERE user_id = :user_id 
            ORDER BY created_at DESC 
            LIMIT :limit OFFSET :skip
        """)
        tasks_result = db.execute(tasks_query, {
            "user_id": current_user.id,
            "limit": limit,
            "skip": skip
        })
        
        tasks = []
        for row in tasks_result:
            tasks.append(BacktestDataTask(
                id=row.id,
                user_id=row.user_id,
                task_type=row.task_type,
                data_source=row.data_source,
                date_range_start=row.date_range_start,
                date_range_end=row.date_range_end,
                symbols=row.symbols or [],
                status=row.status,
                progress=row.progress or 0,
                total_records=row.total_records or 0,
                downloaded_records=row.downloaded_records or 0,
                error_message=row.error_message,
                created_at=row.created_at,
                updated_at=row.updated_at,
                completed_at=row.completed_at
            ))
        
        return BacktestDataTaskListResponse(tasks=tasks, total=total)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取任务列表失败: {str(e)}")


@router.get("/tasks/{task_id}", response_model=BacktestDataTask)
async def get_backtest_data_task(
    task_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取单个回测数据下载任务"""
    try:
        query = text("""
            SELECT * FROM backtest_data_tasks 
            WHERE id = :task_id AND user_id = :user_id
        """)
        result = db.execute(query, {"task_id": task_id, "user_id": current_user.id})
        row = result.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="任务不存在")
        
        return BacktestDataTask(
            id=row.id,
            user_id=row.user_id,
            task_type=row.task_type,
            data_source=row.data_source,
            date_range_start=row.date_range_start,
            date_range_end=row.date_range_end,
            symbols=row.symbols or [],
            status=row.status,
            progress=row.progress or 0,
            total_records=row.total_records or 0,
            downloaded_records=row.downloaded_records or 0,
            error_message=row.error_message,
            created_at=row.created_at,
            updated_at=row.updated_at,
            completed_at=row.completed_at
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取任务失败: {str(e)}")


# ========== 数据配置API ==========

@router.post("/configs", response_model=BacktestDataConfig)
async def create_backtest_data_config(
    config: BacktestDataConfigCreate,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建回测数据配置"""
    try:
        # 检查配置名称是否已存在
        check_query = text("""
            SELECT COUNT(*) FROM backtest_data_configs 
            WHERE user_id = :user_id AND config_name = :config_name
        """)
        check_result = db.execute(check_query, {
            "user_id": current_user.id,
            "config_name": config.config_name
        })
        if check_result.fetchone()[0] > 0:
            raise HTTPException(status_code=400, detail="配置名称已存在")
        
        # 插入配置
        query = text("""
            INSERT INTO backtest_data_configs 
            (user_id, config_name, enabled_data_types, default_date_range_days, 
             default_symbols, data_source_preference, auto_download, update_frequency)
            VALUES (:user_id, :config_name, :enabled_data_types, :default_date_range_days,
                    :default_symbols, :data_source_preference, :auto_download, :update_frequency)
            RETURNING id
        """)
        
        result = db.execute(query, {
            "user_id": current_user.id,
            "config_name": config.config_name,
            "enabled_data_types": config.enabled_data_types,
            "default_date_range_days": config.default_date_range_days,
            "default_symbols": config.default_symbols or [],
            "data_source_preference": config.data_source_preference,
            "auto_download": config.auto_download,
            "update_frequency": config.update_frequency
        })
        config_id = result.fetchone()[0]
        db.commit()
        
        # 获取创建的配置
        config_query = text("""
            SELECT * FROM backtest_data_configs WHERE id = :config_id
        """)
        config_result = db.execute(config_query, {"config_id": config_id})
        row = config_result.fetchone()
        
        return BacktestDataConfig(
            id=row.id,
            user_id=row.user_id,
            config_name=row.config_name,
            enabled_data_types=row.enabled_data_types or [],
            default_date_range_days=row.default_date_range_days,
            default_symbols=row.default_symbols or [],
            data_source_preference=row.data_source_preference,
            auto_download=row.auto_download,
            update_frequency=row.update_frequency,
            last_updated_at=row.last_updated_at,
            created_at=row.created_at,
            updated_at=row.updated_at
        )
    except Exception as e:
        db.rollback()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"创建配置失败: {str(e)}")


@router.get("/configs", response_model=BacktestDataConfigListResponse)
async def list_backtest_data_configs(
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取回测数据配置列表"""
    try:
        # 获取配置列表
        query = text("""
            SELECT * FROM backtest_data_configs 
            WHERE user_id = :user_id 
            ORDER BY created_at DESC
        """)
        result = db.execute(query, {"user_id": current_user.id})
        
        configs = []
        for row in result:
            configs.append(BacktestDataConfig(
                id=row.id,
                user_id=row.user_id,
                config_name=row.config_name,
                enabled_data_types=row.enabled_data_types or [],
                default_date_range_days=row.default_date_range_days,
                default_symbols=row.default_symbols or [],
                data_source_preference=row.data_source_preference,
                auto_download=row.auto_download,
                update_frequency=row.update_frequency,
                last_updated_at=row.last_updated_at,
                created_at=row.created_at,
                updated_at=row.updated_at
            ))
        
        return BacktestDataConfigListResponse(configs=configs, total=len(configs))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取配置列表失败: {str(e)}")


# ========== 数据统计API ==========

@router.get("/stats", response_model=BacktestDataStatsListResponse)
async def get_backtest_data_stats(
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取回测数据统计"""
    try:
        # 获取数据统计
        query = text("""
            SELECT * FROM backtest_data_stats 
            ORDER BY data_type, symbol NULLS FIRST
        """)
        result = db.execute(query)
        
        stats = []
        for row in result:
            stats.append(BacktestDataStats(
                data_type=row.data_type,
                symbol=row.symbol,
                date_range_start=row.date_range_start,
                date_range_end=row.date_range_end,
                total_records=row.total_records or 0,
                last_updated_date=row.last_updated_date,
                data_quality_score=row.data_quality_score or 100,
                missing_dates=row.missing_dates or [],
                created_at=row.created_at,
                updated_at=row.updated_at
            ))
        
        return BacktestDataStatsListResponse(stats=stats, total=len(stats))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取数据统计失败: {str(e)}")


# ========== 批量下载API ==========

@router.post("/batch-download")
async def batch_download_data(
    request: BatchDataDownloadRequest,
    background_tasks: BackgroundTasks,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """批量下载数据 - 自动取消同类型的旧任务"""
    try:
        task_ids = []
        
        # 为每种数据类型创建下载任务
        for data_type in request.data_types:
            # 取消同类型的pending/running任务
            cancel_query = text("""
                UPDATE backtest_data_tasks 
                SET status = 'cancelled', error_message = '被新任务取代', updated_at = NOW()
                WHERE user_id = :user_id 
                  AND task_type = :task_type 
                  AND status IN ('pending', 'running')
            """)
            db.execute(cancel_query, {
                "user_id": current_user.id,
                "task_type": data_type
            })
            
            # 创建新任务
            query = text("""
                INSERT INTO backtest_data_tasks 
                (user_id, task_type, data_source, date_range_start, date_range_end, symbols, status)
                VALUES (:user_id, :task_type, :data_source, :date_range_start, :date_range_end, :symbols, 'pending')
                RETURNING id
            """)
            
            result = db.execute(query, {
                "user_id": current_user.id,
                "task_type": data_type,
                "data_source": request.data_source,
                "date_range_start": request.date_range_start,
                "date_range_end": request.date_range_end,
                "symbols": request.symbols or []
            })
            task_id = result.fetchone()[0]
            task_ids.append(task_id)
        
        db.commit()
        
        # 在后台启动下载任务
        background_tasks.add_task(_process_batch_download, task_ids, current_user.id)
        
        return {
            "message": "批量下载任务已创建",
            "task_ids": task_ids,
            "total_tasks": len(task_ids)
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建批量下载任务失败: {str(e)}")


# ========== 数据源配置API ==========

@router.get("/data-sources")
async def list_data_sources(
    db: Session = Depends(get_db)
):
    """获取数据源配置列表"""
    try:
        query = text("""
            SELECT * FROM data_source_configs 
            WHERE is_active = TRUE 
            ORDER BY priority DESC, source_name
        """)
        result = db.execute(query)
        
        sources = []
        for row in result:
            sources.append({
                "id": row.id,
                "source_name": row.source_name,
                "source_type": row.source_type,
                "description": row.description,
                "rate_limit_per_minute": row.rate_limit_per_minute,
                "priority": row.priority,
                "requires_api_key": bool(row.api_key)
            })
        
        return {"sources": sources, "total": len(sources)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取数据源列表失败: {str(e)}")


# ========== 辅助函数 ==========

async def _process_batch_download(task_ids: List[int], user_id: str):
    """处理批量下载任务 - 使用AKShare真实数据"""
    from api.database import get_db_ctx
    import logging
    
    logger = logging.getLogger(__name__)
    
    for task_id in task_ids:
        try:
            # 获取任务信息
            with get_db_ctx() as db:
                task_query = text("SELECT * FROM backtest_data_tasks WHERE id = :task_id")
                task_result = db.execute(task_query, {"task_id": task_id})
                task = task_result.fetchone()
                
                if not task:
                    logger.error(f"任务 {task_id} 不存在")
                    continue
                
                # ✅ 验证数据源兼容性
                compatible_sources = DATA_SOURCE_COMPATIBILITY.get(task.task_type, [])
                if task.data_source not in compatible_sources:
                    logger.warning(f"数据类型 {task.task_type} 不支持数据源 {task.data_source}")
                    # 自动切换到兼容的数据源
                    if compatible_sources:
                        old_source = task.data_source
                        new_source = compatible_sources[0]
                        logger.info(f"已自动切换数据源: {old_source} -> {new_source}")
                        # 更新数据库
                        db.execute(text("UPDATE backtest_data_tasks SET data_source = :source WHERE id = :task_id"), 
                                   {"source": new_source, "task_id": task_id})
                        db.commit()
                        # 重新查询任务以获取更新后的数据源
                        task_result = db.execute(task_query, {"task_id": task_id})
                        task = task_result.fetchone()
                
                # 更新任务状态为运行中
                db.execute(text("UPDATE backtest_data_tasks SET status = 'running', updated_at = NOW() WHERE id = :task_id"), {"task_id": task_id})
                db.commit()
                
                logger.info(f"开始处理任务 {task_id}: {task.task_type} (数据源: {task.data_source})")
            
            # 创建下载器
            with get_db_ctx() as db:
                downloader = DataDownloader(db)
                
                total_records = 0
                success_count = 0
                error_count = 0
                
                # 根据数据类型下载
                if task.task_type == 'daily_kline':
                    # 检查数据源
                    if task.data_source == 'quantclass':
                        # 使用量化课堂数据源
                        logger.info("使用量化课堂数据源下载股票日K线")
                        
                        try:
                            # 量化课堂配置
                            quantclass_api_key = '2HUTNZYOSRA8X5Z7TY2VZGKNTX5UN28B'
                            quantclass_hid = '1ad9e296ad8d3816b9bce5cba86b1ff6'
                            
                            # 创建下载器
                            qc_downloader = QuantClassDownloader(quantclass_api_key, quantclass_hid)
                            
                            # 下载数据
                            download_result = qc_downloader.download_product('stock-trading-data-pro')
                            
                            if download_result['success']:
                                # 导入数据库
                                import_result = import_stock_daily_from_quantclass(db, download_result['data_path'])
                                
                                if import_result['success']:
                                    total_records = import_result['records_imported']
                                    success_count = import_result['stocks_count']
                                    logger.info(f"量化课堂导入成功: {total_records}条记录, {success_count}只股票")
                                else:
                                    error_count = 1
                                    logger.error(f"量化课堂导入失败: {import_result.get('error')}")
                            else:
                                error_count = 1
                                logger.error(f"量化课堂下载失败: {download_result.get('error')}")
                        except Exception as e:
                            error_count = 1
                            logger.error(f"量化课堂处理异常: {e}")
                        
                        # ✅ 量化课堂下载完成，跳过AKShare下载流程
                        pass
                    
                    else:
                        # 使用AKShare数据源
                        logger.info("使用AKShare数据源下载股票日K线")
                        
                        # 获取股票列表
                        symbols = downloader.get_all_stock_symbols()
                        if task.symbols:
                            # 如果指定了股票代码，只下载指定的
                            symbols = [s for s in symbols if s in task.symbols]
                        
                        total_stocks = len(symbols)
                        logger.info(f"准备下载 {total_stocks} 只股票的日K线数据 (使用AKShare)")
                    
                        # 并行下载（每次处理30只股票，优化性能）
                        batch_size = 10  # ✅ 优化：从30降到10，避免卡顿
                        for i in range(0, len(symbols), batch_size):
                            batch = symbols[i:i+batch_size]
                        
                        # 并行下载这一批股票
                        download_tasks = [
                            downloader.download_daily_kline(
                                symbol, task.date_range_start, task.date_range_end
                            )
                            for symbol in batch
                        ]
                        results = await asyncio.gather(*download_tasks, return_exceptions=True)
                        
                        # 统计结果
                        for symbol, result in zip(batch, results):
                            if isinstance(result, Exception):
                                logger.error(f"股票 {symbol} 下载异常: {result}")
                                error_count += 1
                            elif result['success']:
                                total_records += result['records']
                                success_count += 1
                            else:
                                logger.error(f"股票 {symbol} 下载失败: {result.get('error', '未知错误')}")
                                error_count += 1
                        
                        # 更新进度
                        progress = int((i + batch_size) / len(symbols) * 100)
                        with get_db_ctx() as db_update:
                            db_update.execute(text("""
                                UPDATE backtest_data_tasks 
                                SET progress = :progress, 
                                    downloaded_records = :records,
                                    updated_at = NOW()
                                WHERE id = :task_id
                            """), {
                                "task_id": task_id,
                                "progress": min(progress, 100),
                                "records": total_records
                            })
                            db_update.commit()
                        
                        # 批次间延迟，优化后减少延迟
                        await asyncio.sleep(2)  # ✅ 优化：从0.1秒增加到2秒，避免卡顿
                elif task.task_type == 'index_data':
                    # 检查数据源
                    if task.data_source == 'quantclass':
                        # 使用量化课堂数据源
                        logger.info("使用量化课堂数据源下载指数数据")
                        
                        try:
                            # 量化课堂配置
                            quantclass_api_key = '2HUTNZYOSRA8X5Z7TY2VZGKNTX5UN28B'
                            quantclass_hid = '1ad9e296ad8d3816b9bce5cba86b1ff6'
                            
                            # 创建下载器
                            qc_downloader = QuantClassDownloader(quantclass_api_key, quantclass_hid)
                            
                            # 下载指数数据
                            download_result = qc_downloader.download_product('stock-main-index-data')
                            
                            if download_result['success']:
                                # 导入数据库
                                from api.generic_importer import import_generic_data
                                import_result = import_generic_data(db, download_result['data_path'], 'index_daily')
                                
                                if import_result['success']:
                                    total_records = import_result['records_imported']
                                    success_count = 1
                                    logger.info(f"量化课堂指数数据导入成功: {total_records}条记录")
                                else:
                                    error_count = 1
                                    logger.error(f"量化课堂指数数据导入失败: {import_result.get('error')}")
                            else:
                                error_count = 1
                                logger.error(f"量化课堂指数数据下载失败: {download_result.get('error')}")
                        except Exception as e:
                            error_count = 1
                            logger.error(f"量化课堂指数数据下载异常: {e}")
                    
                    else:
                        # 使用AKShare数据源
                        logger.info("使用AKShare数据源下载指数数据")
                        
                        # 下载主要指数数据
                        symbols = downloader.get_main_index_symbols()
                        if task.symbols:
                            symbols = [s for s in symbols if s in task.symbols]
                        
                        logger.info(f"准备下载 {len(symbols)} 个指数数据")
                        
                        for symbol in symbols:
                            result = await downloader.download_index_data(
                                symbol, task.date_range_start, task.date_range_end
                            )
                            
                            if result['success']:
                                total_records += result['records']
                                success_count += 1
                            else:
                                error_count += 1
                            
                            await asyncio.sleep(1.5)
                
                elif task.task_type == 'minute_kline':
                    # ✅ 1分钟K线数据 - 已验证数据源兼容性，只使用AKShare
                    symbols = downloader.get_all_stock_symbols()
                    if task.symbols:
                        symbols = [s for s in symbols if s in task.symbols]

                    total_stocks = len(symbols)
                    logger.info(f"准备下载 {total_stocks} 只股票的1分钟K线数据 (使用AKShare)")

                    # ✅ 优化：限制并发数量，避免卡顿
                    batch_size = 10  # 从20降到10
                    for i in range(0, len(symbols), batch_size):
                        batch = symbols[i:i+batch_size]

                        # 并行下载这一批股票
                        download_tasks = [
                            downloader.download_minute_kline(
                                symbol, task.date_range_start, task.date_range_end
                            )
                            for symbol in batch
                        ]
                        results = await asyncio.gather(*download_tasks, return_exceptions=True)

                        # 统计结果
                        for symbol, result in zip(batch, results):
                            if isinstance(result, Exception):
                                logger.error(f"股票 {symbol} 1分钟K线下载异常: {result}")
                                error_count += 1
                            elif result['success']:
                                total_records += result['records']
                                success_count += 1
                            else:
                                logger.error(f"股票 {symbol} 1分钟K线下载失败: {result.get('error', '未知错误')}")
                                error_count += 1

                        # 更新进度
                        progress = int((i + batch_size) / len(symbols) * 100)
                        with get_db_ctx() as db_update:
                            db_update.execute(text("""
                                UPDATE backtest_data_tasks
                                SET progress = :progress,
                                    downloaded_records = :records,
                                    updated_at = NOW()
                                WHERE id = :task_id
                            """), {
                                "task_id": task_id,
                                "progress": min(progress, 100),
                                "records": total_records
                            })
                            db_update.commit()

                        # ✅ 优化：增加延迟，避免卡顿
                        await asyncio.sleep(2)  # 从0.5秒增加到2秒
                
                elif task.task_type == 'chip_data':
                    # 筹码数据
                    if task.data_source == 'quantclass':
                        logger.info("使用量化课堂数据源下载筹码数据")
                        
                        try:
                            quantclass_api_key = '2HUTNZYOSRA8X5Z7TY2VZGKNTX5UN28B'
                            quantclass_hid = '1ad9e296ad8d3816b9bce5cba86b1ff6'
                            
                            qc_downloader = QuantClassDownloader(quantclass_api_key, quantclass_hid)
                            download_result = qc_downloader.download_product('stock-chip-distribution')
                            
                            if download_result['success']:
                                from api.generic_importer import import_generic_data
                                import_result = import_generic_data(db, download_result['data_path'], 'chip_data')
                                
                                if import_result['success']:
                                    total_records = import_result['records_imported']
                                    success_count = 1
                                    logger.info(f"筹码数据导入成功: {total_records}条记录")
                                else:
                                    error_count = 1
                                    logger.error(f"筹码数据导入失败: {import_result.get('error')}")
                            else:
                                error_count = 1
                                logger.error(f"筹码数据下载失败: {download_result.get('error')}")
                        except Exception as e:
                            error_count = 1
                            logger.error(f"筹码数据下载异常: {e}")
                    else:
                        logger.warning("AKShare不支持筹码数据下载")
                        error_count = 1
                
                elif task.task_type == 'financial_data':
                    # 财务数据
                    if task.data_source == 'quantclass':
                        logger.info("使用量化课堂数据源下载财务数据")
                        
                        try:
                            quantclass_api_key = '2HUTNZYOSRA8X5Z7TY2VZGKNTX5UN28B'
                            quantclass_hid = '1ad9e296ad8d3816b9bce5cba86b1ff6'
                            
                            qc_downloader = QuantClassDownloader(quantclass_api_key, quantclass_hid)
                            download_result = qc_downloader.download_product('stock-fin-pre-data-sina')
                            
                            if download_result['success']:
                                from api.generic_importer import import_generic_data
                                import_result = import_generic_data(db, download_result['data_path'], 'financial_data')
                                
                                if import_result['success']:
                                    total_records = import_result['records_imported']
                                    success_count = 1
                                    logger.info(f"财务数据导入成功: {total_records}条记录")
                                else:
                                    error_count = 1
                                    logger.error(f"财务数据导入失败: {import_result.get('error')}")
                            else:
                                error_count = 1
                                logger.error(f"财务数据下载失败: {download_result.get('error')}")
                        except Exception as e:
                            error_count = 1
                            logger.error(f"财务数据下载异常: {e}")
                    else:
                        logger.warning("AKShare财务数据下载功能待实现")
                        error_count = 1
                
                elif task.task_type == 'research_reports':
                    # 研报数据
                    logger.warning("研报数据下载功能待实现")
                    error_count = 1
                
                else:
                    logger.warning(f"未知的数据类型: {task.task_type}")
                    error_count = 1
                
                # 更新任务状态为已完成
                with get_db_ctx() as db:
                    db.execute(text("""
                        UPDATE backtest_data_tasks 
                        SET status = 'completed', 
                            progress = 100, 
                            total_records = :total_records,
                            downloaded_records = :total_records,
                            completed_at = NOW(),
                            updated_at = NOW()
                        WHERE id = :task_id
                    """), {
                        "task_id": task_id,
                        "total_records": total_records
                    })
                    
                    # 更新数据统计（先删除旧记录，再插入新记录，避免PostgreSQL NULL值问题）
                    db.execute(text("""
                        DELETE FROM backtest_data_stats 
                        WHERE data_type = :data_type AND (symbol = :symbol OR (symbol IS NULL AND :symbol IS NULL))
                    """), {
                        "data_type": task.task_type,
                        "symbol": None
                    })
                    
                    db.execute(text("""
                        INSERT INTO backtest_data_stats 
                        (data_type, symbol, total_records, date_range_start, date_range_end, data_quality_score, last_updated_date)
                        VALUES (:data_type, NULL, :total_records, :date_range_start, :date_range_end, 95, CURRENT_DATE)
                    """), {
                        "data_type": task.task_type,
                        "total_records": total_records,
                        "date_range_start": task.date_range_start,
                        "date_range_end": task.date_range_end
                    })
                    db.commit()
                    
                    # 数据质量检查（质量优先原则）
                    try:
                        quality_manager = DataQualityManager()
                        
                        # 确定表名
                        table_name = 'stock_daily_kline'
                        if task.task_type == 'index_data':
                            table_name = 'index_daily_data'
                        elif task.task_type == 'minute_kline':
                            table_name = 'stock_minute_kline'
                        
                        # 执行质量检查
                        quality_result = quality_manager.validate_database_integrity(
                            db, table_name, task.task_type
                        )
                        
                        if quality_result['valid']:
                            logger.info(f"✅ 数据质量检查通过: {quality_result['stats']}")
                        else:
                            logger.warning(f"⚠️ 数据质量问题: {quality_result['issues']}")
                    except Exception as e:
                        logger.error(f"数据质量检查异常: {e}")
                    
                    # 记录数据源使用统计
                    try:
                        monitor = get_data_source_monitor()
                        monitor.record_download(
                            source=task.data_source or 'quantclass',
                            data_type=task.task_type,
                            records=total_records,
                            success=(error_count == 0)
                        )
                        logger.info(f"✅ 使用统计已记录: {task.data_source} - {task.task_type}")
                    except Exception as e:
                        logger.error(f"使用统计记录异常: {e}")
                    
                    logger.info(f"任务 {task_id} 完成: 成功 {success_count}, 失败 {error_count}, 总记录 {total_records}")
                
        except Exception as e:
            logger.error(f"任务 {task_id} 执行失败: {e}")
            # 更新任务状态为失败
            with get_db_ctx() as db:
                db.execute(text("""
                    UPDATE backtest_data_tasks 
                    SET status = 'failed', 
                        error_message = :error,
                        updated_at = NOW()
                    WHERE id = :task_id
                """), {"task_id": task_id, "error": str(e)})
                db.commit()




# ========== 数据下载状态检查 ==========

@router.get("/download-status")
async def get_download_status(
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取数据下载状态概览"""
    try:
        # 统计各种状态的任务数量
        status_query = text("""
            SELECT status, COUNT(*) as count 
            FROM backtest_data_tasks 
            WHERE user_id = :user_id 
            GROUP BY status
        """)
        status_result = db.execute(status_query, {"user_id": current_user.id})
        
        status_counts = {}
        for row in status_result:
            status_counts[row.status] = row.count
        
        # 获取最近的任务
        recent_query = text("""
            SELECT * FROM backtest_data_tasks 
            WHERE user_id = :user_id 
            ORDER BY created_at DESC 
            LIMIT 5
        """)
        recent_result = db.execute(recent_query, {"user_id": current_user.id})
        
        recent_tasks = []
        for row in recent_result:
            recent_tasks.append({
                "id": row.id,
                "task_type": row.task_type,
                "status": row.status,
                "progress": row.progress or 0,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "completed_at": row.completed_at.isoformat() if row.completed_at else None
            })
        
        return {
            "status_counts": status_counts,
            "recent_tasks": recent_tasks,
            "total_tasks": sum(status_counts.values())
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取下载状态失败: {str(e)}")


# ========== 数据质量检查API ==========

@router.get("/quality-check/{table_name}")
async def check_data_quality(
    table_name: str,
    data_type: str = "daily_kline",
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    检查数据质量
    
    Args:
        table_name: 表名（如 stock_daily_kline）
        data_type: 数据类型（daily_kline, index_data等）
    """
    try:
        quality_manager = DataQualityManager()
        
        # 执行数据库完整性检查
        db_result = quality_manager.validate_database_integrity(db, table_name, data_type)
        
        return {
            "success": True,
            "table_name": table_name,
            "data_type": data_type,
            "valid": db_result['valid'],
            "issues": db_result['issues'],
            "stats": db_result['stats']
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"数据质量检查失败: {str(e)}")


@router.get("/quality-report")
async def generate_quality_report(
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    生成完整的数据质量报告
    
    包括：
    - 股票日K线数据质量
    - 指数数据质量
    - 数据库完整性
    """
    try:
        quality_manager = DataQualityManager()
        
        report = {
            "generated_at": datetime.now().isoformat(),
            "tables": {}
        }
        
        # 检查股票日K线
        daily_kline_result = quality_manager.validate_database_integrity(
            db, "stock_daily_kline", "daily_kline"
        )
        report["tables"]["stock_daily_kline"] = {
            "valid": daily_kline_result['valid'],
            "issues": daily_kline_result['issues'],
            "stats": daily_kline_result['stats']
        }
        
        # 检查指数数据（如果表存在）
        try:
            index_result = quality_manager.validate_database_integrity(
                db, "index_daily_data", "index_data"
            )
            report["tables"]["index_daily_data"] = {
                "valid": index_result['valid'],
                "issues": index_result['issues'],
                "stats": index_result['stats']
            }
        except:
            report["tables"]["index_daily_data"] = {
                "valid": False,
                "issues": ["表不存在"],
                "stats": {}
            }
        
        return {
            "success": True,
            "report": report
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成质量报告失败: {str(e)}")


# ========== 数据源使用统计API ==========

@router.get("/source-usage")
async def get_data_source_usage(
    current_user: UserDB = Depends(get_current_user)
):
    """
    获取数据源使用统计
    
    包括：
    - 量化课堂使用次数和剩余次数
    - AKShare使用统计
    - 每日下载记录
    """
    try:
        monitor = get_data_source_monitor()
        
        return {
            "success": True,
            "sources": monitor.get_all_sources_status(),
            "daily_report": monitor.get_daily_report()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取使用统计失败: {str(e)}")


@router.get("/source-status/{source}")
async def get_source_status(
    source: str,
    current_user: UserDB = Depends(get_current_user)
):
    """
    获取指定数据源状态
    
    Args:
        source: 数据源名称（quantclass, akshare）
    """
    try:
        monitor = get_data_source_monitor()
        status = monitor.get_usage_status(source)
        
        if 'error' in status:
            raise HTTPException(status_code=400, detail=status['error'])
        
        return {
            "success": True,
            "status": status
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取数据源状态失败: {str(e)}")
