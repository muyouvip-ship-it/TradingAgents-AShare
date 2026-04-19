-- 回测数据配置和管理表

-- 1. 回测数据下载任务表
CREATE TABLE IF NOT EXISTS backtest_data_tasks (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    task_type VARCHAR(50) NOT NULL,  -- 数据类型: daily_kline, minute_kline, index_data, chip_data, financial_data, research_reports
    data_source VARCHAR(100),        -- 数据源: akshare, tushare, baostock, etc.
    date_range_start DATE NOT NULL,   -- 开始日期
    date_range_end DATE NOT NULL,     -- 结束日期
    symbols TEXT[],                   -- 股票代码数组
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- 状态: pending, running, completed, failed
    progress INTEGER DEFAULT 0,       -- 进度百分比 0-100
    total_records INTEGER DEFAULT 0,  -- 总记录数
    downloaded_records INTEGER DEFAULT 0, -- 已下载记录数
    error_message TEXT,               -- 错误信息
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    
    CONSTRAINT fk_backtest_task_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX idx_backtest_tasks_user_id ON backtest_data_tasks(user_id);
CREATE INDEX idx_backtest_tasks_status ON backtest_data_tasks(status);
CREATE INDEX idx_backtest_tasks_created_at ON backtest_data_tasks(created_at DESC);

-- 2. 数据下载配置表
CREATE TABLE IF NOT EXISTS backtest_data_configs (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    config_name VARCHAR(100) NOT NULL,  -- 配置名称
    enabled_data_types TEXT[] NOT NULL DEFAULT '{}',  -- 启用的数据类型
    default_date_range_days INTEGER DEFAULT 365,      -- 默认下载天数
    default_symbols TEXT[] DEFAULT '{}',              -- 默认股票代码
    data_source_preference VARCHAR(100) DEFAULT 'akshare', -- 数据源偏好
    auto_download BOOLEAN DEFAULT FALSE,              -- 是否自动下载
    update_frequency VARCHAR(20),                     -- 更新频率: daily, weekly, monthly
    last_updated_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    CONSTRAINT fk_backtest_config_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT unique_user_config_name UNIQUE (user_id, config_name)
);

CREATE INDEX idx_backtest_configs_user_id ON backtest_data_configs(user_id);

-- 3. 数据统计表（展示已有数据）
CREATE TABLE IF NOT EXISTS backtest_data_stats (
    id SERIAL PRIMARY KEY,
    data_type VARCHAR(50) NOT NULL,   -- 数据类型
    symbol VARCHAR(20),               -- 股票代码，为空表示所有股票
    date_range_start DATE,            -- 数据开始日期
    date_range_end DATE,              -- 数据结束日期
    total_records BIGINT DEFAULT 0,   -- 总记录数
    last_updated_date DATE,           -- 最后更新日期
    data_quality_score INTEGER DEFAULT 100, -- 数据质量评分 0-100
    missing_dates DATE[],             -- 缺失的日期
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    CONSTRAINT unique_data_stats UNIQUE (data_type, symbol)
);

CREATE INDEX idx_data_stats_data_type ON backtest_data_stats(data_type);
CREATE INDEX idx_data_stats_symbol ON backtest_data_stats(symbol);
CREATE INDEX idx_data_stats_date_range ON backtest_data_stats(date_range_start, date_range_end);

-- 4. 数据源配置表
CREATE TABLE IF NOT EXISTS data_source_configs (
    id SERIAL PRIMARY KEY,
    source_name VARCHAR(100) NOT NULL UNIQUE,  -- 数据源名称
    source_type VARCHAR(50) NOT NULL,          -- 类型: stock, index, financial, etc.
    api_key TEXT,                              -- API密钥
    api_secret TEXT,                           -- API密钥
    base_url TEXT,                             -- API基础URL
    rate_limit_per_minute INTEGER DEFAULT 60,  -- 每分钟请求限制
    is_active BOOLEAN DEFAULT TRUE,            -- 是否启用
    priority INTEGER DEFAULT 1,                -- 优先级（1-10，越高越优先）
    description TEXT,                          -- 描述
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 插入默认数据源配置
INSERT INTO data_source_configs (source_name, source_type, description, priority) VALUES
('akshare', 'stock', 'AKShare开源数据源，免费无限制', 10),
('tushare', 'stock', 'Tushare数据源，需要API Token', 5),
('baostock', 'stock', 'Baostock数据源，免费', 8),
('eastmoney', 'financial', '东方财富数据源，免费', 7),
('sina', 'stock', '新浪财经数据源，免费', 6),
('tencent', 'stock', '腾讯财经数据源，免费', 9);

-- 创建数据质量监控表（简化版）
CREATE TABLE IF NOT EXISTS backtest_data_quality (
    id SERIAL PRIMARY KEY,
    data_type VARCHAR(50) NOT NULL,
    check_date DATE NOT NULL,
    symbol VARCHAR(20),
    check_items JSONB NOT NULL DEFAULT '{}',  -- 检查项结果
    quality_score INTEGER DEFAULT 100,        -- 质量评分 0-100
    issues TEXT[],                            -- 问题列表
    created_at TIMESTAMP DEFAULT NOW(),
    
    CONSTRAINT unique_data_quality_check UNIQUE (data_type, check_date, symbol)
);

CREATE INDEX idx_data_quality_date ON backtest_data_quality(check_date DESC);
CREATE INDEX idx_data_quality_type ON backtest_data_quality(data_type);