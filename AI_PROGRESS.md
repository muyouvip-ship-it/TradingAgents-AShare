# AI Progress

本文件记录最近交接进度。每次任务收尾时更新，保持最新内容在最上方。

## 2026-05-15 最终代码收口与远端推送

### 本次做了什么

- 收口当前 `main` 工作区累计改动，准备提交并推送到远端。
- 本次提交覆盖近期资讯之眼主线机会榜、设置页日 K 覆盖日历、量化小课堂补数、策略回测引擎/仓储、报告/分析页接口与前端类型等改动。
- 继续按根目录交接约定更新本进度文件，方便后续对话从当前提交继续。

### 改动文件

- 后端：`api/backtest_data_api.py`、`api/routes/news_eye.py`、`api/routes/strategy_platform.py`、`api/services/news_theme_service.py`、`api/services/strategy_platform_engine.py` 等。
- 前端：`frontend/src/pages/NewsEye.tsx`、`frontend/src/pages/Settings.tsx`、`frontend/src/pages/Analysis.tsx`、`frontend/src/pages/Reports.tsx`、`frontend/src/services/api.ts`、`frontend/src/types/index.ts`。
- 测试：`tests/test_backtest_data_api_calendar.py`、`tests/test_news_theme_service.py`、`tests/test_strategy_platform_repository.py`、`tests/test_strategy_platform_true_engine.py`、`tests/test_realtime_monitor.py`。
- 数据/文档：`data/quantclass/2026-04-20.csv`、`data/quantclass/2026-04-21.csv`、`data/quantclass/2026-04-24.csv`、`data/quantclass/2026-05-07.csv` 至 `2026-05-14.csv`、`项目数据来源与调用机制梳理.md`。

### 验证结果

- `git diff --check`
- `python -m py_compile api/backtest_data_api.py api/routes/news_eye.py api/schemas/news_eye.py api/services/news_theme_service.py api/services/news_eye_service.py api/services/strategy_platform_engine.py api/services/strategy_platform_repository.py`
- `set -a; source .env; set +a; pytest tests/test_backtest_data_api_calendar.py tests/test_news_theme_service.py tests/test_news_eye_service.py -q`：`18 passed`
- `pytest tests/test_strategy_platform_repository.py tests/test_strategy_platform_true_engine.py tests/test_realtime_monitor.py -q`：`50 passed`
- `cd frontend && npm run build`

### 当前风险或未完成事项

- 本次是累计改动收口，没有额外跑全量测试套件。
- 量化小课堂 CSV 为正式补数产物，后续如果继续自动下载，需要留意数据目录大小和是否需要归档策略。

### 下一步建议

- 后续继续从 `main` 最新提交开始开发。
- 若要支持普通微信群推送，建议另起 Windows 专用微信号 + `wxauto` relay，避免在主力 Mac 微信上做 GUI 自动化。

## 2026-05-14 日 K 缺口检查与量化小课堂补数

### 本次做了什么

- 按 A 股交易日历核对正式 PostgreSQL 日 K 数据，检查 `stock_daily_kline`、`raw_stock_daily_kline_quantclass`、`norm_stock_daily_kline`、`pub_stock_daily_kline`。
- 发现可用日 K 覆盖中近期缺失 3 个交易日：`2026-04-20`、`2026-04-21`、`2026-04-24`。
- 使用量化小课堂 `stock-trading-data-pro` 按指定日期下载并导入这 3 天数据。
- 导入后刷新 `data/artifacts/market_cache/daily_kline/daily_kline_2026.parquet`。
- 重新核对设置页日历接口，2026 年有数据天数从 `81` 天变为 `84` 天。
- 继续核查旧主表 `stock_daily_kline`，发现旧表缺 `2026-04-20`、`2026-04-21`、`2026-04-24` 和 `2026-05-06` 至 `2026-05-14` 共 10 个增量交易日；已从 `pub_stock_daily_kline` 镜像回旧表。

### 改动/生成文件

- `data/quantclass/2026-04-20.csv`
- `data/quantclass/2026-04-21.csv`
- `data/quantclass/2026-04-24.csv`
- `data/artifacts/market_cache/daily_kline/daily_kline_2026.parquet`
- PostgreSQL `stock_daily_kline` 旧主表新增/更新 `54928` 行，日期覆盖到 `2026-05-14`。

### 验证结果

- `2026-04-20` 导入 `5493` 行 / `5493` 只股票。
- `2026-04-21` 导入 `5498` 行 / `5498` 只股票。
- `2026-04-24` 导入 `5496` 行 / `5496` 只股票。
- 补数后 `raw_stock_daily_kline_quantclass`、`norm_stock_daily_kline`、`pub_stock_daily_kline` 三层均能查到上述 3 天数据。
- 近期交易日 `2026-04-14` 至 `2026-05-14` 复核结果：`MISSING_RECENT=[]`、`PARTIAL_RECENT=[]`。
- 认证请求 `GET /v1/backtest-data/daily-kline/coverage-calendar?year=2026` 返回约 `1.473s`，三天均 `has_data=true`，且 `is_trading_day=true`。
- 旧主表补齐后复核：`stock_daily_kline` 总行数 `17667600`，覆盖 `8681` 个交易日，日期范围 `1990-12-19` 至 `2026-05-14`；`2026-04-14` 至 `2026-05-14` 复核 `OLD_MISSING_RECENT=[]`、`OLD_PARTIAL_RECENT=[]`。

### 当前风险或未完成事项

- 当前代码默认 `MARKET_DATA_WRITE_LEGACY_TABLES=0`，后续增量仍会优先写 raw/norm/pub 发布链路；如果希望以后旧主表也同步写入，需要显式打开兼容镜像或改默认策略。
- 本次只补了实际缺失交易日和旧表近期缺口，没有重刷整个历史库。

### 下一步建议

- 后续若设置页要更直观，可在“已下载数据”中区分旧主表、发布层、统一视图的覆盖状态，避免看到旧主表滞后时误判缺数据。
- 可以把“交易日历对比 + 指定日期量化小课堂补数”沉淀成一个后台运维按钮或脚本。

## 2026-05-14 设置页日 K 覆盖日历超时修复

### 本次做了什么

- 修复设置页“回测数据 / 已下载数据 / 股票日 K 线数据视图”请求 `coverage-calendar?year=2026` 超过 15 秒的问题。
- 根因是接口读取 `preferred_daily_kline_table()` 后落到 `market_stock_daily_kline` 统一视图，视图会做跨表 `UNION` 和去重，`MIN/MAX(trade_date)` 与按日统计在正式 PostgreSQL 上容易超时。
- 日历接口改为优先读取轻量物理表 `stock_daily_kline`、`pub_stock_daily_kline`，只在没有物理表可用时兜底到首选表。
- 接口响应新增 `source_tables`，方便页面/调试知道当前覆盖日历来自哪些表。
- 新增针对性单测，防止后续把日历统计重新改回慢视图。
- 股票日 K 线数据视图补充休息日展示：后端每日对象新增 `is_rest_day/is_trading_day`，前端日期格右上角显示红色“休”角标。

### 改动文件

- `api/backtest_data_api.py`
- `frontend/src/pages/Settings.tsx`
- `tests/test_backtest_data_api_calendar.py`

### 验证结果

- `python -m py_compile api/backtest_data_api.py`
- `pytest tests/test_backtest_data_api_calendar.py -q`
- `cd frontend && npm run build`
- 正式后端 `127.0.0.1:8500`、前端代理 `127.0.0.1:5174` 均在运行。
- 认证后请求 `http://127.0.0.1:5174/v1/backtest-data/daily-kline/coverage-calendar?year=2026` 连续 3 次返回 `200 OK`，耗时约 `4.141s / 1.441s / 2.202s`。
- 返回结果显示 `year=2026`、`total_days_with_data=81`、`source_tables=['stock_daily_kline', 'pub_stock_daily_kline']`。
- 休息日字段验证：认证后请求同一接口返回 `is_rest_day/is_trading_day`，2026 年休息日计数为 `123`，例如 `2026-01-01` 返回 `is_rest_day=true`。

### 当前风险或未完成事项

- 未跑全量回归；此前尝试跑较重的 `tests/test_market_data_pipeline_service.py` 会卡在正式库初始化/查询路径，不适合作为这个小修复的快速验证。
- 如果未来 `stock_daily_kline` 或 `pub_stock_daily_kline` 数据量继续增大，建议为 `(trade_date, symbol)` 补充/确认索引，进一步压低冷启动查询耗时。

### 下一步建议

- 前端可在日历视图中展示 `source_tables` 或数据源提示，便于以后定位数据口径。
- 后续可给设置页统计接口增加更细的慢查询日志，超过阈值时输出表名、年份和耗时。

## 2026-05-10 资讯掘金主线机会榜

### 本次做了什么

- 在“资讯之眼”增加主线机会榜能力：标准主题映射、来源分层、政策催化、非线性共振评分、共识率/分歧提示、拥挤风险、证据消息和历史回溯。
- 新增后端 `news_theme_service`，从 `market_news_items` 和索引表生成主题快照，并提供后续 1/3/5 日板块表现回溯。
- 新闻刷新后会尝试同步刷新 `premarket`、`24h`、`72h`、`7d` 四个窗口的主线快照；失败只记录日志，不阻断资讯入库。
- 前端 `/news-eye` 顶部新增“主线机会榜”，支持时间窗口切换、点击主题筛选资讯流、证据展开和历史表现查看。
- 发现旧 `8500` 后端进程未加载新增接口导致页面无主线数据，已重启 `ta-backend` screen，并重算主线快照。

### 改动文件

- `api/services/news_theme_service.py`
- `api/routes/news_eye.py`
- `api/schemas/news_eye.py`
- `api/services/news_eye_service.py`
- `api/services/__init__.py`
- `frontend/src/pages/NewsEye.tsx`
- `frontend/src/services/api.ts`
- `frontend/src/types/index.ts`
- `tests/test_news_theme_service.py`

### 验证结果

- `pytest tests/test_news_theme_service.py tests/test_news_eye_service.py -q`
- `python -m py_compile api/services/news_theme_service.py api/routes/news_eye.py api/schemas/news_eye.py api/services/news_eye_service.py`
- `cd frontend && npm run build`
- `git diff --check`
- 临时启动后端 `127.0.0.1:8501`，确认新路由 `/v1/news-eye/themes` 已加载；未登录访问按预期返回 401。
- 正式后端 `127.0.0.1:8500` 已重启并加载新接口；后台日志显示登录态请求 `/v1/news-eye/themes` 返回 `200 OK`。

### 当前风险或未完成事项

- 第一版标准主题库为内置别名表，后续还需要接入同花顺/通达信概念库或本地股票池概念表。
- 历史表现第一版按 `sw_industry_l1` 聚合，概念主题如“算力”如果没有对应行业字段，可能没有表现数据。
- LLM 榜单摘要暂未自动调用模型，当前摘要和风险提示先由规则生成。

### 下一步建议

- 补充更完整的概念映射源，并把主题到成分股/板块指数的映射做成可维护配置。
- 增加评分参数的后台配置或实验记录，用历史回溯持续调新鲜度、来源层级和分歧因子权重。

## 2026-05-08 Git 收口与远端推送

### 本次做了什么

- 准备提交当前工作区全部改动。
- 将 `default-sqlite` 当前版本合并到 `main`。
- 推送到项目当前目标远端：`all-seeing-eye` 与 `quanzhizhiyan`。

### 改动文件

- 本次提交包含近期 QMT、实时监控、行情数据、设置页、股票市场、资讯之眼、文档交接文件等累计改动。
- 具体文件以本次 Git commit diff 为准。

### 验证结果

- 已在提交前完成相关验证：
  - `npm run build`
  - `pytest tests/test_virtual_warehouse.py tests/test_qmt_sync_scheduler_service.py tests/test_realtime_monitor.py -q`
  - `python -m py_compile api/services/qmt_virtual_account_service.py api/services/data_source_governance.py`

### 下一步建议

- 推送后如果继续开发，先从 `main` 拉取最新版本。
- 后续每次功能收口继续更新本文件顶部记录。

## 2026-05-08 交接文档初始化

### 本次做了什么

- 扩展根目录 `README.md`，补充项目定位、核心模块、运行方式、数据与后台任务、验证方式和安全边界。
- 新增 `AI_PROGRESS.md`，作为每次 AI 收尾时必须更新的进度文件。
- 新增 `AI_RULES.md`，作为长期有效的协作规则文件。

### 改动文件

- `README.md`
- `AI_PROGRESS.md`
- `AI_RULES.md`

### 验证结果

- 文档类改动，未运行代码测试。
- 已确认根目录存在现有 `产品文档.md`、`项目性能与功能拓展分析.md`、多源治理和 QMT 相关文档，可作为后续深读材料。

### 当前状态摘要

- 项目使用 PostgreSQL，不再按 SQLite 口径维护。
- QMT 账户配置应走设置页/数据库，不应写死在 `.env`。
- QMT 实盘仓和虚拟仓页面已区分“实时直连 / 后台在线 / 快照可用 / 未连接”，避免页面切走后误显示失联。
- 资讯之眼和股票市场接口近期已修复为按当前用户读取数据源与 QMT bridge 配置。
- 后端当前常用端口 `8500`，前端常用端口 `5174`。

### 下一步建议

- 后续任何代码任务结束时，追加或更新本文件顶部条目。
- 如果发生重要架构、数据口径、QMT 安全边界变化，同时更新 `README.md` 和 `AI_RULES.md`。
- 下一阶段继续收紧：产品口径统一、实盘安全边界、数据可信度展示、策略可解释性。
