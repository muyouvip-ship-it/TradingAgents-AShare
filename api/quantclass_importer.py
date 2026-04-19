"""
量化课堂数据导入到数据库
"""
import pandas as pd
from sqlalchemy import text
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def import_stock_daily_from_quantclass(db_session, csv_file_path: str) -> dict:
    """
    从量化课堂CSV文件导入股票日线数据到数据库（Pro版本，包含所有字段）
    
    Args:
        db_session: 数据库会话
        csv_file_path: CSV文件路径
    
    Returns:
        {
            'success': bool,
            'records_imported': int,
            'stocks_count': int,
            'errors': list
        }
    """
    try:
        # 读取CSV文件（量化课堂使用GBK编码，第一行是注释）
        logger.info(f"开始读取CSV文件: {csv_file_path}")
        df = pd.read_csv(csv_file_path, encoding='gbk', skiprows=1)
        
        logger.info(f"读取到 {len(df)} 行数据，{df['股票代码'].nunique()} 只股票")
        
        # 数据清洗
        records_imported = 0
        errors = []
        
        for idx, row in df.iterrows():
            try:
                # 处理股票代码（去掉市场前缀）
                symbol = row['股票代码']
                if symbol.startswith('bj'):
                    # 北交所股票，保留原代码
                    pass
                elif symbol.startswith(('sh', 'sz')):
                    # 沪深股票，去掉前缀
                    symbol = symbol[2:]
                
                # 处理日期
                trade_date = pd.to_datetime(row['交易日期']).date()
                
                # 插入数据库（包含Pro版本所有字段）
                insert_query = text("""
                    INSERT INTO stock_daily_kline 
                    (symbol, trade_date, open, high, low, close, volume, amount,
                     pre_close, float_market_cap, total_market_cap,
                     net_profit_ttm, cash_flow_ttm, net_assets, total_assets, total_liabilities,
                     net_profit_quarter, medium_buy, medium_sell, large_buy, large_sell,
                     retail_buy, retail_sell, institution_buy, institution_sell,
                     is_hs300, is_sz50, is_zz500, is_zz1000, is_zz2000, is_cyb,
                     sw_industry_l1, sw_industry_l2, sw_industry_l3,
                     close_0935, close_0945, close_0955)
                    VALUES (
                        :symbol, :trade_date, :open, :high, :low, :close, :volume, :amount,
                        :pre_close, :float_market_cap, :total_market_cap,
                        :net_profit_ttm, :cash_flow_ttm, :net_assets, :total_assets, :total_liabilities,
                        :net_profit_quarter, :medium_buy, :medium_sell, :large_buy, :large_sell,
                        :retail_buy, :retail_sell, :institution_buy, :institution_sell,
                        :is_hs300, :is_sz50, :is_zz500, :is_zz1000, :is_zz2000, :is_cyb,
                        :sw_industry_l1, :sw_industry_l2, :sw_industry_l3,
                        :close_0935, :close_0945, :close_0955
                    )
                    ON CONFLICT (symbol, trade_date) DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        amount = EXCLUDED.amount,
                        pre_close = EXCLUDED.pre_close,
                        float_market_cap = EXCLUDED.float_market_cap,
                        total_market_cap = EXCLUDED.total_market_cap,
                        net_profit_ttm = EXCLUDED.net_profit_ttm,
                        cash_flow_ttm = EXCLUDED.cash_flow_ttm,
                        net_assets = EXCLUDED.net_assets,
                        total_assets = EXCLUDED.total_assets,
                        total_liabilities = EXCLUDED.total_liabilities,
                        net_profit_quarter = EXCLUDED.net_profit_quarter,
                        medium_buy = EXCLUDED.medium_buy,
                        medium_sell = EXCLUDED.medium_sell,
                        large_buy = EXCLUDED.large_buy,
                        large_sell = EXCLUDED.large_sell,
                        retail_buy = EXCLUDED.retail_buy,
                        retail_sell = EXCLUDED.retail_sell,
                        institution_buy = EXCLUDED.institution_buy,
                        institution_sell = EXCLUDED.institution_sell,
                        is_hs300 = EXCLUDED.is_hs300,
                        is_sz50 = EXCLUDED.is_sz50,
                        is_zz500 = EXCLUDED.is_zz500,
                        is_zz1000 = EXCLUDED.is_zz1000,
                        is_zz2000 = EXCLUDED.is_zz2000,
                        is_cyb = EXCLUDED.is_cyb,
                        sw_industry_l1 = EXCLUDED.sw_industry_l1,
                        sw_industry_l2 = EXCLUDED.sw_industry_l2,
                        sw_industry_l3 = EXCLUDED.sw_industry_l3,
                        close_0935 = EXCLUDED.close_0935,
                        close_0945 = EXCLUDED.close_0945,
                        close_0955 = EXCLUDED.close_0955,
                        updated_at = NOW()
                """)
                
                # 准备数据
                data = {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "open": float(row['开盘价']) if pd.notna(row.get('开盘价')) else None,
                    "high": float(row['最高价']) if pd.notna(row.get('最高价')) else None,
                    "low": float(row['最低价']) if pd.notna(row.get('最低价')) else None,
                    "close": float(row['收盘价']) if pd.notna(row.get('收盘价')) else None,
                    "volume": int(row['成交量']) if pd.notna(row.get('成交量')) else None,
                    "amount": float(row['成交额']) if pd.notna(row.get('成交额')) else None,
                    # Pro版本额外字段
                    "pre_close": float(row['前收盘价']) if pd.notna(row.get('前收盘价')) else None,
                    "float_market_cap": float(row['流通市值']) if pd.notna(row.get('流通市值')) else None,
                    "total_market_cap": float(row['总市值']) if pd.notna(row.get('总市值')) else None,
                    "net_profit_ttm": float(row['净利润TTM']) if pd.notna(row.get('净利润TTM')) else None,
                    "cash_flow_ttm": float(row['现金流TTM']) if pd.notna(row.get('现金流TTM')) else None,
                    "net_assets": float(row['净资产']) if pd.notna(row.get('净资产')) else None,
                    "total_assets": float(row['总资产']) if pd.notna(row.get('总资产')) else None,
                    "total_liabilities": float(row['总负债']) if pd.notna(row.get('总负债')) else None,
                    "net_profit_quarter": float(row['净利润(当季)']) if pd.notna(row.get('净利润(当季)')) else None,
                    "medium_buy": float(row['中户资金买入额']) if pd.notna(row.get('中户资金买入额')) else None,
                    "medium_sell": float(row['中户资金卖出额']) if pd.notna(row.get('中户资金卖出额')) else None,
                    "large_buy": float(row['大户资金买入额']) if pd.notna(row.get('大户资金买入额')) else None,
                    "large_sell": float(row['大户资金卖出额']) if pd.notna(row.get('大户资金卖出额')) else None,
                    "retail_buy": float(row['散户资金买入额']) if pd.notna(row.get('散户资金买入额')) else None,
                    "retail_sell": float(row['散户资金卖出额']) if pd.notna(row.get('散户资金卖出额')) else None,
                    "institution_buy": float(row['机构资金买入额']) if pd.notna(row.get('机构资金买入额')) else None,
                    "institution_sell": float(row['机构资金卖出额']) if pd.notna(row.get('机构资金卖出额')) else None,
                    "is_hs300": str(row['沪深300成分股']).strip() if pd.notna(row.get('沪深300成分股')) else None,
                    "is_sz50": str(row['上证50成分股']).strip() if pd.notna(row.get('上证50成分股')) else None,
                    "is_zz500": str(row['中证500成分股']).strip() if pd.notna(row.get('中证500成分股')) else None,
                    "is_zz1000": str(row['中证1000成分股']).strip() if pd.notna(row.get('中证1000成分股')) else None,
                    "is_zz2000": str(row['中证2000成分股']).strip() if pd.notna(row.get('中证2000成分股')) else None,
                    "is_cyb": str(row['创业板指成分股']).strip() if pd.notna(row.get('创业板指成分股')) else None,
                    "sw_industry_l1": str(row['新版申万一级行业名称']).strip() if pd.notna(row.get('新版申万一级行业名称')) else None,
                    "sw_industry_l2": str(row['新版申万二级行业名称']).strip() if pd.notna(row.get('新版申万二级行业名称')) else None,
                    "sw_industry_l3": str(row['新版申万三级行业名称']).strip() if pd.notna(row.get('新版申万三级行业名称')) else None,
                    "close_0935": float(row['09:35收盘价']) if pd.notna(row.get('09:35收盘价')) else None,
                    "close_0945": float(row['09:45收盘价']) if pd.notna(row.get('09:45收盘价')) else None,
                    "close_0955": float(row['09:55收盘价']) if pd.notna(row.get('09:55收盘价')) else None,
                }
                
                db_session.execute(insert_query, data)
                
                records_imported += 1
                
                # 每100条提交一次
                if records_imported % 100 == 0:
                    db_session.commit()
                    logger.info(f"已导入 {records_imported} 条记录")
                    
            except Exception as e:
                errors.append(f"行 {idx}: {str(e)}")
                continue
        
        # 最终提交
        db_session.commit()
        
        logger.info(f"导入完成: {records_imported} 条记录")
        
        return {
            'success': True,
            'records_imported': records_imported,
            'stocks_count': df['股票代码'].nunique(),
            'errors': errors[:10]  # 只返回前10个错误
        }
        
    except Exception as e:
        logger.error(f"导入失败: {e}")
        return {
            'success': False,
            'error': str(e),
            'records_imported': 0
        }


# 测试脚本
if __name__ == '__main__':
    import sys
    sys.path.insert(0, '/Users/wolf/Documents/DaiMa/TradingAgents-AShare-main')
    
    from api.database import get_db_ctx
    from api.quantclass_downloader import QuantClassDownloader
    
    # 配置
    API_KEY = '2HUTNZYOSRA8X5Z7TY2VZGKNTX5UN28B'
    HID = '1ad9e296ad8d3816b9bce5cba86b1ff6'
    
    # 创建下载器
    downloader = QuantClassDownloader(API_KEY, HID)
    
    # 下载股票日线数据
    print("开始下载量化课堂数据...")
    result = downloader.download_product('stock-trading-data', save_path='/tmp/quantclass_import')
    
    if not result['success']:
        print(f"下载失败: {result.get('error')}")
        sys.exit(1)
    
    csv_file = result['data_path']
    print(f"下载成功: {csv_file}")
    
    # 导入数据库
    print("\n开始导入数据库...")
    with get_db_ctx() as db:
        import_result = import_stock_daily_from_quantclass(db, csv_file)
    
    if import_result['success']:
        print(f"\n✅ 导入成功!")
        print(f"导入记录: {import_result['records_imported']}")
        print(f"股票数量: {import_result['stocks_count']}")
        if import_result.get('errors'):
            print(f"错误数量: {len(import_result['errors'])}")
    else:
        print(f"\n❌ 导入失败: {import_result.get('error')}")
