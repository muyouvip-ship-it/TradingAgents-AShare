"""
量化课堂数据产品映射
"""

# 数据产品映射：任务类型 -> 量化课堂产品代码
QUANTCLASS_PRODUCT_MAPPING = {
    # K线数据
    'daily_kline': 'stock-trading-data',           # 股票历史日线数据
    'daily_kline_pro': 'stock-trading-data-pro',   # 股票历史全息日线数据
    'hour_kline': 'stock-1h-trading-data',         # 股票1小时K线数据
    'minute_5_kline': 'stock-5m-close-price',      # 股票5分钟收盘价
    'minute_15_kline': 'stock-15m-close-price',    # 股票15分钟收盘价
    
    # 指数数据
    'index_daily': 'stock-main-index-data',        # 主要指数历史日线数据
    'index_hour': 'stock-1h-index-data',           # 指数1小时K线数据
    
    # 高级数据
    'chip_data': 'stock-chip-distribution',        # 筹码分布市场数据
    'money_flow': 'stock-money-flow',              # 资金流数据
    'financial_data': 'stock-fin-pre-data-sina',   # 财务预处理数据
    'analyst_ranking': 'stock-analyst-ranking',    # 分析师评级数据
    
    # 其他数据
    'dividend': 'stock-dividend-delivery',         # 个股分红数据
    'trading_date': 'stock-trading-date',          # 每日A股股票汇总
}

# 数据产品描述
QUANTCLASS_PRODUCT_DESCRIPTIONS = {
    'stock-trading-data': '股票历史日线数据',
    'stock-trading-data-pro': '股票历史全息日线数据（更完整）',
    'stock-1h-trading-data': '股票1小时K线数据',
    'stock-5m-close-price': '股票5分钟收盘价',
    'stock-15m-close-price': '股票15分钟收盘价',
    'stock-main-index-data': '主要指数历史日线数据',
    'stock-1h-index-data': '指数1小时K线数据',
    'stock-chip-distribution': '筹码分布市场数据',
    'stock-money-flow': '资金流数据',
    'stock-fin-pre-data-sina': '财务预处理数据',
    'stock-analyst-ranking': '分析师评级数据',
}

# 需要特殊处理的数据类型
QUANTCLASS_SPECIAL_HANDLING = {
    'minute_kline': {
        'use_akshare': True,  # 量化课堂没有1分钟数据，使用AKShare
        'reason': '量化课堂无1分钟K线数据，使用AKShare获取'
    }
}
