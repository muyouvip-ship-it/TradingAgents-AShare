"""
数据查询API - 查询股票K线数据
数据库中已有完整数据，此API提供查询接口
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date, datetime
import logging

from api.database import get_db
from api.models.strategy_models import StockDailyKlineDB

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/data", tags=["Data Management"])


# ============ 请求模型 ============

class DataAvailabilityRequest(BaseModel):
    """数据可用性检查请求"""
    symbols: List[str] = Field(..., description="股票代码列表")
    start_date: date = Field(..., description="开始日期")
    end_date: date = Field(..., description="结束日期")


# ============ API 路由 ============

@router.post("/kline/check", summary="检查数据可用性")
async def check_data_availability(
    request: DataAvailabilityRequest,
    db: Session = Depends(get_db),
):
    """
    检查指定股票在指定日期范围内的数据可用性
    
    返回每只股票的数据条数和日期范围
    """
    try:
        from sqlalchemy import func
        
        results = []
        for symbol in request.symbols:
            # 查询数据量
            count = db.query(func.count(StockDailyKlineDB.id)).filter(
                StockDailyKlineDB.symbol == symbol,
                StockDailyKlineDB.trade_date >= request.start_date,
                StockDailyKlineDB.trade_date <= request.end_date
            ).scalar()
            
            # 查询日期范围
            min_date = db.query(func.min(StockDailyKlineDB.trade_date)).filter(
                StockDailyKlineDB.symbol == symbol,
                StockDailyKlineDB.trade_date >= request.start_date,
                StockDailyKlineDB.trade_date <= request.end_date
            ).scalar()
            
            max_date = db.query(func.max(StockDailyKlineDB.trade_date)).filter(
                StockDailyKlineDB.symbol == symbol,
                StockDailyKlineDB.trade_date >= request.start_date,
                StockDailyKlineDB.trade_date <= request.end_date
            ).scalar()
            
            results.append({
                "symbol": symbol,
                "available": count > 0,
                "count": count,
                "min_date": min_date.isoformat() if min_date else None,
                "max_date": max_date.isoformat() if max_date else None,
            })
        
        return {
            "success": True,
            "total": len(request.symbols),
            "results": results,
        }
        
    except Exception as e:
        logger.error(f"检查数据可用性失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/kline/stats", summary="查看数据统计")
async def get_kline_stats(
    db: Session = Depends(get_db),
):
    """
    查看数据库中的K线数据统计
    
    返回：
    - 总股票数
    - 总记录数
    - 日期范围
    """
    try:
        from sqlalchemy import func
        
        # 总记录数
        total_records = db.query(func.count(StockDailyKlineDB.id)).scalar()
        
        # 股票数
        total_stocks = db.query(func.count(func.distinct(StockDailyKlineDB.symbol))).scalar()
        
        # 日期范围
        min_date = db.query(func.min(StockDailyKlineDB.trade_date)).scalar()
        max_date = db.query(func.max(StockDailyKlineDB.trade_date)).scalar()
        
        return {
            "total_stocks": total_stocks,
            "total_records": total_records,
            "date_range": {
                "min": min_date.isoformat() if min_date else None,
                "max": max_date.isoformat() if max_date else None,
            },
        }
        
    except Exception as e:
        logger.error(f"获取统计失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/kline/{symbol}", summary="查询股票K线数据")
async def get_kline_data(
    symbol: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """
    查询指定股票的K线数据
    
    - **symbol**: 股票代码（6位数字）
    - **start_date**: 开始日期（可选）
    - **end_date**: 结束日期（可选）
    - **limit**: 返回记录数限制（默认100条）
    """
    try:
        query = db.query(StockDailyKlineDB).filter(StockDailyKlineDB.symbol == symbol)
        
        if start_date:
            query = query.filter(StockDailyKlineDB.trade_date >= start_date)
        
        if end_date:
            query = query.filter(StockDailyKlineDB.trade_date <= end_date)
        
        query = query.order_by(StockDailyKlineDB.trade_date.desc()).limit(limit)
        
        records = query.all()
        
        return {
            "symbol": symbol,
            "total": len(records),
            "data": [r.to_dict() for r in records]
        }
        
    except Exception as e:
        logger.error(f"查询数据失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
