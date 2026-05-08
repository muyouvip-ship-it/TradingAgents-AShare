# AI Progress

本文件记录最近交接进度。每次任务收尾时更新，保持最新内容在最上方。

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
