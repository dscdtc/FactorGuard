# FactorGuard 原版与当前版对比及 GitHub 发布建议

> 对比基线：`F:\FactorGuard 20260819`  
> 当前工作区：`F:\FactorGuard`  
> 对比日期：2026-08-21  
> 对比方式：目录结构、核心文件 SHA-256、源码契约、正式快照清单和自动化测试证据  
> 原版目录仅作只读基线，本次未修改。

## 1. 结论摘要

当前版不是原版的简单界面修改，而是从“可运行原型”推进到“具备正式数据、确定性凭证、AI 安全边界、自动化测试和双发布产物的可交付版本”。

核心范围内的文件差异为：

| 状态 | 数量 |
| --- | ---: |
| 新增 | 21 |
| 修改 | 27 |
| 删除 | 2 |
| 未变化 | 21 |

目录级变化：

| 模块 | 2026-08-19 原版 | 当前版 | 变化 |
| --- | ---: | ---: | --- |
| `engine/` | 19 | 21 | 新增证据约束 AI 分析和会话上下文 |
| `models/` | 5 | 6 | 新增 AI 输出 Pydantic 契约 |
| `pages/` | 9 | 8 | 独立工作台合并到首页 |
| `scripts/` | 0 | 3 | 新增快照、比赛包和 GitHub Release 构建脚本 |
| `tests/` | 0 | 7 | 新增核心、AI、页面和发布契约测试 |
| 正式 Parquet | 0 | 3 | 新增冻结比赛快照 |

全仓库文件数量包含三个大型因子仓库，仅用于规模参考：原版 6,486 个文件，当前版 6,511 个文件。核心差异应以上表和文件哈希结果为准，不能用总文件数替代行为对比。

## 2. 产品与页面变化

### 2.1 首页与工作台

原版同时存在简单入口 `app.py` 和 `pages/01_工作台.py`，导航和职责重复。当前版将数据快照、新建鉴证、最近运行和四个 Demo 入口合并到 `app.py`，使用显式 `st.navigation` 把首项命名为“首页”，并删除重复工作台页面。

### 2.2 报告页

原版报告页没有独立、真实的模型辅助链路。当前版报告页包含 8 个 Tab，其中“AI 辅助解读”与正式报告明确分离；HTML、Markdown、JSON 正式下载按钮固定为 3 个。

### 2.3 能力声明

原版 README 使用过时的本地数据路径和 PE/PB 字段描述。当前版按实际数据校准为：

- 原始 CSV：`E:\Quantclass\stock-trading-data-pro`；
- 正式快照：2024-09-27 至 2025-09-26；
- 1,314,224 行、5,473 只股票；
- 原始 CSV 不包含 PE/PB 和财务公告时点；
- 预计算、演示、未测试和实时计算状态不能混用。

## 3. 数据与可复现性变化

原版没有 `data/` 正式快照，也没有可重复执行的构建脚本。当前版新增：

- `daily_ohlcv.parquet`：56,828,422 字节；
- `daily_basic.parquet`：38,992,249 字节；
- `stock_basic.parquet`：86,329 字节；
- `manifest.json`：记录范围、行数、股票数和各文件 SHA-256；
- `scripts/build_snapshots.py`：显式、流式构建快照；
- `.building` 临时文件和原子替换，避免半成品冒充正式快照。

页面不会因快照缺失而隐式扫描全部原始 CSV。GitHub 源码包也不捆绑大型数据；正式 Parquet 使用独立 Release 附件分发。

## 4. 确定性审计变化

当前版对原核心链路进行了行为修复和收口：

- 前瞻收益统一为 `open(t+1+h) / open(t+1) - 1`；
- 覆盖率基于对齐前应有样本计算；
- 缺字段或未执行的测试保持 `untested`，不能转成 `pass`；
- 压力测试方向翻转不能通过；
- 因子、前瞻周期、时间范围和快照变化会使缓存失效；
- 传统评估、压力测试、重复性和适用性统一进入证据引擎；
- 关键证据不足时总体结论为 `insufficient`；
- `evidence_hash` 覆盖 FactorSpec、快照、配置、传统评估、压力测试、重复性、适用性和引擎版本；
- `audit_runs` 持久化正式结论、运行参数、`evidence_hash` 和 `report_hash`。

## 5. AI 与正式报告边界变化

原版 `compute_report_hash(evidence_hash, ai_explanation)` 会让 AI 文本改变正式报告哈希。当前版已调整为三个独立边界：

| 哈希 | 覆盖内容 | AI 是否参与 |
| --- | --- | --- |
| `evidence_hash` | 确定性输入、配置、计算证据和引擎版本 | 否 |
| `report_hash` | `evidence_hash` 与确定性正式报告载荷 | 否 |
| `ai_analysis_hash` | `evidence_hash`、供应商、模型、提示词版本和经校验的 AI 载荷 | 是，独立计算 |

当前 AI sidecar 支持 OpenAI、DeepSeek、通义千问 / DashScope、智谱、Moonshot / Kimi、硅基流动和自定义 OpenAI-compatible 服务，并满足：

- API Key 仅从环境变量读取；
- 不进入页面输入、session state、请求正文、报告、日志或哈希；
- 模型不能改变正式结论；
- 引用必须属于当前真实 `evidence_id`；
- 文本数字必须来自正式证据；
- 超时、网络错误、结构错误、引用错误或数字错误统一降级为 `rule_fallback`；
- AI 文本不进入正式 HTML、Markdown、JSON 下载内容，也不写入 `audit_runs` 正式字段。

PRD 和技术设计中原先“AI 进入 `report_hash`”的旧口径已经同步修正。

## 6. 测试与交付变化

原版 `tests/` 为空。当前版测试覆盖：

- 前瞻收益、覆盖率、压力方向和未测试语义；
- 缓存上下文与证据哈希边界；
- 运行记录持久化；
- AI Pydantic 结构、结论、引用和数字校验；
- 无配置、超时、网络错误和非法响应规则降级；
- API Key、DataFrame 和本地路径不进入模型请求；
- AI 不改变正式报告哈希与正式下载；
- 首页、完整跨页流程和真实 R001 AppTest；
- GitHub 源码包禁入项和正式快照 SHA-256。

当前版还提供两个独立发布流程：

- `scripts/build_submission.py`：生成包含正式数据的比赛可运行包；
- `scripts/build_github_release.py`：生成 GitHub 源码包与独立快照 Release 包。

最终发布候选验证结果为：聚焦回归 61 passed，全量回归 87 passed；GitHub 源码包独立解压后 60 passed、1 skipped，叠加正式快照后 59 passed，所有编译检查通过。

## 7. 保留与删除判断

### 7.1 当前版继续保留

- `README.md`：GitHub 仓库首页和运行入口；
- `DOC/FactorGuard_PRD_V1.1.md`：产品范围和指标口径；
- `DOC/FACTORGUARD_TECHNICAL_DESIGN.md`：当前架构与契约；
- `DOC/PROJECT_STATUS.md`：实现状态和验收证据；
- `DOC/changes/ai_auxiliary_analysis/`：AI 安全边界变更依据；
- `DOC/COMPETITION_DEMO_SCRIPT.md`：比赛演示操作说明；
- 本文档：原版到当前版的变更说明和发布策略；
- 三个因子仓库中的索引、说明、许可和预计算摘要；
- 原版目录与指定备份目录：仅在本地保留，作为回滚与审计基线。

### 7.2 已删除且不应恢复到当前主线

- `pages/01_工作台.py`：与当前首页重复；
- `DOC/FactorGuard_MVP_TaskList.md`：基于过时的 5 人团队排期，已被当前状态和变更规格取代。

## 8. GitHub 最终上传建议

### 8.1 仓库内容

使用 `dist/FactorGuard_github_source.zip` 解压后的 `FactorGuard` 目录创建 GitHub 仓库。仓库应包含：

- `app.py`、`config.py`、`requirements.txt`、`setup.bat`；
- `engine/`、`models/`、`pages/`、`scripts/`、`tests/`、`ui/`、`utils/`；
- `Factors/` 中筛选后的索引、说明、许可和验证摘要；
- `README.md`、`DOC/`、根目录 `.gitignore`；
- `data/snapshot/README.md` 和 `manifest.json`。

不要把源码 ZIP 本身提交到仓库。GitHub 自动生成的源码归档已经足够，构建 ZIP 只用于本地初始化干净仓库。

### 8.2 GitHub Release 附件

上传 `FactorGuard_snapshot_20240927_20250926.zip` 作为正式快照附件，并同时上传对应 `.sha256`。比赛交付需要完整开箱运行时，可另行上传 `FactorGuard_submission.zip`，但必须明确标注它是比赛包，不是源码仓库。

### 8.3 公开上传前必须决定

当前 FactorGuard 根目录没有项目级 `LICENSE`。公开仓库前应由项目所有者明确选择 MIT、Apache-2.0、专有许可或其他方案。三个因子仓库各自已有许可文件，但不能自动替代 FactorGuard 主项目许可。

### 8.4 版本标签

- `v0.1.0`：指向 GitHub 已有第一版的最后一次提交，作为原型基线。
- `v1.0.0`：指向当前发布提交，包含确定性正式审计、隔离的 AI 辅助解读、正式数据快照契约和自动化测试。
- `v1.0.0` Release 只上传正式快照 ZIP 及其 `.sha256`；GitHub 自动生成源码归档，比赛 ZIP 继续作为本地比赛交付物保留。

## 9. 绝对不要上传

- 任何真实 API Key、`.env`、`.streamlit/secrets.toml`、私钥或访问令牌；
- `E:\Quantclass\stock-trading-data-pro` 原始 CSV；
- `DataSource/` 上游工作区；
- 当前工作区或 `Factors/` 内的任何 `.git` 目录；
- `__pycache__`、`.pytest_cache`、`tests/artifacts`、日志、截图和临时文件；
- `data/factor_master.duckdb` 及其 WAL；
- `data/snapshot_week_*` 和任何 `.building` 文件；
- 本地备份目录、独立解压验证目录和聊天截图。

根目录 `.gitignore` 已覆盖上述常见风险，但 `.gitignore` 不能移除已经提交进 Git 历史的密钥或大文件。首次提交前仍应从干净源码包创建仓库并检查暂存列表。

## 10. 本地保留建议

| 内容 | 建议 | 理由 |
| --- | --- | --- |
| `F:\FactorGuard` | 保留 | 当前开发工作区和事实源 |
| `F:\FactorGuard 20260819` | 只读保留 | 原始版本对比基线 |
| `F:\FactorGuard_backups\FactorGuard_20260820_203100\FactorGuard` | 保留 | 已知稳定回滚点 |
| `E:\Quantclass\stock-trading-data-pro` | 本地保留，不上传 | 原始正式数据源 |
| `FactorGuard_submission.zip` | 保留 | 比赛开箱运行包 |
| `FactorGuard_github_source.zip` | 保留到仓库初始化完成 | 干净源码发布基线 |
| `FactorGuard_snapshot_20240927_20250926.zip` | 长期保留 | GitHub Release 正式数据附件 |
| 各 ZIP 的 `.sha256` | 与 ZIP 一起保留 | 下载和归档完整性校验 |

## 11. 最终原则

正式报告由确定性审计引擎生成；大模型只提供可引用、可校验、可降级的投研辅助解读，不参与正式裁决。
