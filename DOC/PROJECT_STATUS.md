# FactorGuard 当前状态与正确性修复规范

> 状态：全市场近一年比赛快照与核心真实链路完成，视觉验收待执行 | 更新日期：2026-08-20 | 当前事实源：代码、自动化验证与本文件

## 1. 文档职责

- `README.md`：项目入口、真实能力边界、安装和运行说明。
- `FactorGuard_PRD_V1.1.md`：产品目标、指标口径和验收规则。
- `FACTORGUARD_TECHNICAL_DESIGN.md`：当前技术架构与组件契约。
- 本文件：当前实现状态、已知缺陷、本轮修复范围和验收证据。

发生冲突时，指标和产品行为以 PRD 为准；实现状态以代码、测试和本文件为准。

## 2. 已验证基线

### 已具备

- Streamlit 多页面应用可以启动。
- 因子元数据和预计算摘要可从 DuckDB 读取；DuckDB 不可用时可回退读取因子仓库 JSON。
- 无本地行情时，内置因子的传统评估页面可以展示预计算摘要。
- 传统评估、压力测试、重复检测、适用性和报告页面均已接入统一审计状态。
- `audit_runs` 会持久化运行参数、结论、证据哈希和报告哈希；自定义因子会先写入元数据以满足外键约束。
- 内置因子实时计算按因子仓库的 base/transform 契约执行；自定义公式由受限 AST 解释器执行，不使用 `eval`。

### 当前限制

- 本地行情源位于 `E:\Quantclass\stock-trading-data-pro`；正式比赛快照位于 `data/snapshot/`，范围为 2024-09-27 至 2025-09-26。
- 真实 CSV 不含 PE/PB；`净利润TTM`、`现金流TTM` 和 `净利润(当季)` 已按原义映射，不再误标为估值或同比字段。
- 快照构建已改为逐 CSV、逐 Parquet row group 流式写入，并通过 `.building` 临时文件完成原子替换；页面不会隐式触发构建。
- `data/factor_cache/` 当前仅为预留路径；本轮计算缓存位于 Streamlit 会话中，不是可跨进程复用的磁盘缓存。
- 预计算摘要只代表历史验证产物，不能冒充当前环境实时完成的压力测试、重复检测或适用性分析。
- 当前 AppTest 已断言跨页来源状态、未测试语义、证据不足结论、持久化状态和三种报告导出。
- 当前环境未完成真实浏览器点击和视觉验收；该项仍需在可用浏览器环境中人工复核。

## 3. 本轮修复目标

| ID | 要求 |
| --- | --- |
| REQ-001 | `h` 日前瞻收益必须为 `open(t+1+h) / open(t+1) - 1`。 |
| REQ-002 | 覆盖率必须相对因子与收益对齐前的应有样本计算，不能在删除缺失值后恒为 100%。 |
| REQ-003 | 缺少测试所需字段或没有执行测试时，状态必须为 `untested`，不能记为 `pass`。 |
| REQ-004 | 压力测试方向翻转不能通过；基线绝对 RankIC 过小时不得输出有意义的保留率。 |
| REQ-005 | 因子、前瞻周期或时间配置变化时，不得复用其他上下文的对齐数据和审计结果。 |
| REQ-006 | 各页面产生的传统评估、压力测试、重复检测和适用性结果必须写入统一审计状态，并携带来源。 |
| REQ-007 | 缺少统计支持或关键测试时，总体结论必须为“证据不足”，不得自动变成“条件有效”。 |
| REQ-008 | `evidence_hash` 必须覆盖 FactorSpec、数据快照、配置、传统评估、压力测试、重复检测、适用性和引擎版本。 |
| REQ-009 | 内置、文本、公式、上传和大师代理入口必须生成完整 FactorSpec；内置实时计算必须遵循其 base/transform 定义，暂不能计算时必须明确阻止流程。 |
| REQ-010 | FactorGuard 核心模块必须有 pytest 单元测试和带断言的页面集成测试。 |
| REQ-011 | 完整报告运行必须写入 DuckDB，包含运行参数、结论、`evidence_hash` 和 `report_hash`；失败时会话仍可用且必须保留错误原因。 |
| REQ-012 | 页面读取不到正式 Parquet 快照时必须快速降级，不得在页面渲染或 AppTest 中隐式扫描全部原始 CSV；快照只能由显式构建操作生成。 |
| REQ-013 | 真实数据对齐结果必须保留压力测试所需的 `total_mv`，缺失时才允许将微盘剔除和市值中性化标为 `untested`。 |
| REQ-014 | 重复检测的相似度返回契约统一使用 `score`；一站式鉴证不得因字段名不一致漏报高相似因子。 |
| REQ-015 | 一站式鉴证保存的总体结论必须来自统一证据引擎；未来函数失败、关键测试缺失或演示来源不得被 RankIC/ICIR 单独提升为有效结论。 |
| REQ-016 | FactorSpec 的预期方向必须参与统计证据；显著但方向相反的 RankIC 不得判为统计通过。 |
| REQ-017 | 大师财务代理可以计算时仍必须受时点证据约束；缺少公告日期时结论不得提升为支持。 |
| REQ-018 | 正式提交包必须包含运行所需 Parquet、DuckDB、因子索引和代码，并排除原始上游仓库、嵌套版本库、缓存、CSV 副本和构建中间文件。 |
| REQ-019 | 比赛界面不得宣称不存在的样本范围、LLM 或 Python 沙箱能力；因子入口不得因渲染全部 806 张详情卡而阻塞首屏。 |

## 4. 状态与证据契约

审计子结果统一使用以下来源状态：

- `computed`：当前环境从当前因子和数据实时计算。
- `precomputed`：读取已存在的历史验证摘要。
- `demo`：明确构造的路演数据，不作为真实鉴证证据。
- `untested`：缺少数据、字段或用户尚未执行。
- `failed`：已尝试但计算失败，并保留原因。

`untested` 和 `failed` 不得被转换为通过。报告必须展示来源和缺失项。

## 5. 缓存契约

所有对齐数据和计算缓存至少绑定：

- `factor_id`；
- `forward_period`；
- 时间范围及自定义边界；
- 数据快照哈希或等价数据标识；
- 影响结果的预处理、中性化和随机种子。

当前会话缓存使用因子规格哈希、上传数据哈希、前瞻周期、时间范围、自定义边界、分组参数、Bootstrap 参数和快照身份生成缓存键。快照身份由 Parquet 文件名、大小和修改时间组成；它用于缓存失效，不声称是内容级加密哈希。

切换因子时清理上一因子的活动结果；历史命名缓存可以保留，但只有上下文完全相同时才允许读取。

## 6. 结论规则

按 PRD V1.1 执行：

1. 时间正确性失败：`invalid`。
2. 数据不足、统计不支持或关键测试缺失：`insufficient`。
3. 基线有统计支持但核心压力测试失败：`fragile`。
4. 仅在明确环境中获得支持：`conditional`。
5. 所有关键维度通过且无显著条件限制：`supported`。

演示级代理结果不能将结论提升为 `supported`。

## 7. 验收标准

| ID | 验收条件 | 验证 |
| --- | --- | --- |
| AC-001 | 人工价格序列的 1 日和 5 日前瞻收益符合 PRD 公式。 | pytest |
| AC-002 | 含缺失因子值的人工数据返回非 100% 的正确覆盖率。 | pytest |
| AC-003 | 缺少 `total_mv` 时两项市值测试为 `untested`。 | pytest |
| AC-004 | 压力后方向翻转时测试不得为 `pass`。 | pytest |
| AC-005 | 切换因子后不能读取上一因子的 `aligned_data`。 | pytest |
| AC-006 | 关键测试缺失或统计失败时审计结论为 `insufficient`。 | pytest |
| AC-007 | 任一压力、重复性或适用性结果变化都会改变 `evidence_hash`。 | pytest |
| AC-008 | AppTest 串联后报告消费同一因子的审计状态并生成三种导出。 | AppTest |
| AC-009 | `compileall` 和 FactorGuard 核心 pytest 全部通过。 | 自动 |
| AC-010 | 内置因子按仓库 base/transform 契约计算，且未注册自定义 FactorSpec 可直接进入对齐流程。 | pytest |
| AC-011 | 自定义因子的完整运行可写入临时 DuckDB 并读回两个哈希；不同上传数据产生不同数据身份。 | pytest |
| AC-012 | 快照构建可按闭区间限制日期，真实沪深北 CSV 能生成字段正确的三份 Parquet。 | pytest + 真实数据烟雾测试 |
| AC-013 | 正式快照缺失但原始 CSV 存在时，数据读取立即返回明确错误且不会调用 `build_snapshots`；离线 AppTest 仍走预计算降级。 | pytest + AppTest |
| AC-014 | 对齐后的真实数据包含 `total_mv`，微盘剔除和市值中性化不再因字段丢失变成 `untested`。 | pytest |
| AC-015 | R001/R034 的公式相似度 `score > 0.8` 能被一站式重复扫描识别。 | pytest |
| AC-016 | 时间正确性失败时保存结论为 `invalid`；关键证据缺失时为 `insufficient`，不受漂亮 RankIC/ICIR 覆盖。 | pytest |
| AC-017 | RankIC 与 `expected_direction` 相反时统计支持为失败，总体不高于 `insufficient`。 | pytest + 真实 R001 |
| AC-018 | 资本效率代理可在真实快照计算，但因公告时点缺失保持时间正确性 `untested` 和总体 `insufficient`。 | pytest + 真实数据 |
| AC-019 | 精简 ZIP 包含三份正式 Parquet、清单、DuckDB、三个因子索引和演示稿，且不含 `DataSource`、`.git`、CSV、`.building`、缓存或日志。 | 归档检查 + 解压运行 |
| AC-020 | 入口页显示 2024-09-27 至 2025-09-26，移除 Python 脚本占位和 LLM 误导；因子页仅渲染首批 12 张详情卡且 806 个条目仍可搜索选择。 | AppTest |

## 8. 执行任务

| 任务 | 关联 | 状态 |
| --- | --- | --- |
| T-001 校准文档职责与当前事实 | REQ-001..011 | 完成 |
| T-002 修复指标与压力测试口径 | REQ-001..004 | 完成 |
| T-003 建立因子选择与页面状态契约 | REQ-005..006、009 | 完成 |
| T-004 修复结论、凭证和运行记录 | REQ-007..008、011 | 完成 |
| T-005 增加核心测试并执行回归 | REQ-010 | 完成 |
| T-006 修复真实字段映射和有界内存快照构建 | 数据正确性 | 完成 |
| T-007 构建全市场近一年比赛快照并运行真实因子回归 | 真实数据验收 | 完成 |
| T-008 拆分显式快照构建与页面只读加载 | REQ-012 | 完成 |
| T-009 修复压力测试、重复检测和总体结论契约 | REQ-013..016 | 完成 |
| T-010 接入一个可计算但时点受限的大师代理 | REQ-017 | 完成 |
| T-011 修复跨电脑路径、展示口径和因子入口性能 | REQ-019 | 完成 |
| T-012 生成精简比赛包、校验清单与演示脚本 | REQ-018 | 完成 |

## 9. 验证证据

2026-08-20 最终自动化与真实数据验收：

- `py -m pytest -q tests\test_core_correctness.py`：24 passed。
- `py tests\apptest_full_flow.py`：通过；03 → 04 → 05 → 06 → 08 串联无异常，报告结论为证据不足并提供 3 个下载按钮。
- `py -m pytest -q`：最终数字见本节最后一次回归记录。
- `py -m compileall -q app.py config.py engine models pages ui utils tests`：通过。
- DuckDB 实际读回：`audit_runs` 已包含 `factor_id`、结论、`evidence_hash` 和 `report_hash`。
- Streamlit 健康检查：`http://127.0.0.1:8501/_stcore/health` 返回 `200 / ok`，首页返回 `200`。
- 真实数据烟雾测试：读取 `sh600000`、`sz000001`、`bj430017`，限定 `2025-09-24` 至 `2025-09-26`；生成 OHLCV 9 行、basic 9 行、stock_basic 3 行，0 个读取失败。
- DuckDB 校验：三份快照日期和股票数一致；`net_profit_ttm`、`cash_flow_ttm`、`net_profit_quarter` 均为 9/9 非空，未生成错误的 `pe_ttm` 字段。
- 比赛快照显式构建：扫描 6,114 个 CSV，生成 1,314,224 行、5,473 只股票、0 个读取失败；三份 Parquet 合计约 96 MB，清单与 SHA-256 见 `data/snapshot/manifest.json`。
- R001 真实链路：快照载入约 3.3 秒，完整计算约 34 秒；覆盖率 96.14%，四项压力测试 3 通过、1 警告、0 未测试。RankIC Mean 为 -0.03264，与 `higher` 预期方向相反，因此不能判为统计通过。
- 大师资本效率代理真实链路：因子值覆盖 99.05%，完整计算约 27 秒；因方向不符、统计不显著、基线不足和公告时点缺失，结论为 `insufficient`，未冒充已验证的巴菲特策略。
- `py tests\apptest_real_audit.py`：真实一站式鉴证通过，处理 1,314,224 行 / 5,473 只股票；四项压力测试判词依次为 warn/pass/pass/pass，统一证据结论与最近运行记录均为 `insufficient`。
- `py -m pytest -q`：50 passed；`compileall` 通过。
- 可移植性与展示修复回归：`py -m pytest -q` 为 52 passed；入口页 AppTest 覆盖首页和因子输入。修复前因 806 张卡片逐项查询导致 60 秒超时。
- `scripts/build_submission.py` 已生成 `dist/FactorGuard_submission.zip`；归档仅 94 项，包含正式快照、DuckDB、3 个因子索引和演示稿，归档检查未发现禁止项。
- 从提交 ZIP 解压到独立目录后，入口页 AppTest 通过，包内核心 pytest 为 26 passed；证明提交包不依赖开发目录中的原始 CSV、上游 `DataSource` 或测试缓存。

AppTest 的 `missing ScriptRunContext` 是 Streamlit bare mode 测试提示；无行情时的单行加载失败信息属于预期降级证据。

## 10. 文档与产物清理建议

- 已删除不再反映当前实现的历史 MVP 任务清单；当前规划和验收状态统一由本文件及 `DOC/changes/` 下的变更规格维护。
- 根目录 `tmp_dom.txt`、`tmp_home.png` 是浏览器检查临时产物；当前策略阻止自动删除，提交包会排除。
- `tests/artifacts/` 下截图和文本是可再生成的测试证据；保留用于路演复核，或在发布包中排除。
- 中止构建留下的 `data/snapshot_week_20250922_20250926/*.building` 和 `tests/artifacts/real_smoke_source_3d/*.csv` 均为冗余副本；当前执行环境的删除策略阻止自动清理，`scripts/build_submission.py` 会排除这些文件。

## 11. 非目标

- 本轮不新增市场和数据源。
- 本轮不执行用户上传的任意 Python 代码。
- 本轮不进行整体视觉改版。
- 本轮不把预计算摘要扩展成伪造的完整实时 Tear Sheet。

## 12. 比赛提交前剩余事项

- 必须：在可用浏览器环境逐个点击首页、四个 Demo、报告导出，检查桌面与移动布局并重做答辩截图；本轮浏览器控制实例为空，不能以 AppTest 代替视觉结论。
- 已完成：3 至 5 分钟演示脚本见 `DOC/COMPETITION_DEMO_SCRIPT.md`。
- 已完成：`scripts/build_submission.py` 可生成精简提交包并附带 SHA-256；排除上游仓库、pytest 缓存、旧截图、复制 CSV 和 `.building` 文件。
- 报名方向：选择“金融行业 AI 应用开发（投研应用）”。FactorGuard 是完整投研应用，不是单独的金融投研 Skill。正式鉴证为确定性链路；可选模型仅提供证据约束的辅助解读，无配置时规则降级。

## 13. AI 辅助解读变更（2026-08-20）

- 正式报告由 `engine/evidence_engine.py` 生成，`report_hash` 只覆盖确定性的正式报告载荷；AI 文本不进入 HTML、Markdown、JSON 正式下载内容。
- `engine/ai_analysis.py` 只接收因子标识、正式结论、五维证据摘要和 `EvidenceRecord` 摘要，并把结果写入 Streamlit `session_state` 的 `audit_results["ai_analysis"]`。`save_run`/`audit_runs` 不保存 AI 文本或 AI 哈希。
- 模型输出必须通过 Pydantic 结构校验、正式结论一致性校验、真实 `evidence_id` 校验和证据数字校验；失败、超时、网络错误和非 JSON 响应均标记 `rule_fallback`。
- 规则降级对同一输入确定性相同；模型、提示词版本或经校验的 AI 载荷变化只改变 `ai_analysis_hash`，不改变 `evidence_hash` 或 `report_hash`。
- 验证证据：`tests/test_ai_analysis.py` 与核心回归共 43 项通过；全量 pytest 共 69 项通过；`compileall` 和 `tests/apptest_full_flow.py` 通过。
- 提交包 `dist/FactorGuard_submission.zip` 已通过精确禁入项检查和独立解压目录包内回归。最终 SHA-256 记录在旁侧 `dist/FactorGuard_submission.zip.sha256`，避免把 ZIP 自身哈希写入包内文档造成自引用。

正式报告由确定性审计引擎生成；大模型只提供可引用、可校验、可降级的投研辅助解读，不参与正式裁决。

## 14. 首页与 AI 入口整理（2026-08-21）

- `app.py` 已合并原工作台的数据快照、新建鉴证、最近运行和四个 Demo 入口，删除重复的 `pages/01_工作台.py`。
- 报告页新增独立“AI 辅助解读”Tab；无正式证据时仍显示该 Tab，并明确要求先完成鉴证。
- 完整流程 AppTest 会实际点击 AI 按钮，断言无模型环境下返回 `rule_fallback`、降级原因和 `ai_analysis_hash`；正式下载按钮仍为 3 个。
- 入口页 AppTest、完整流程 AppTest、`compileall` 均通过；全量 pytest 为 69 passed。

## 15. AI 多供应商配置（2026-08-21）

- 报告页 AI Tab 现支持 OpenAI、DeepSeek、通义千问 / DashScope、智谱、Moonshot / Kimi、硅基流动和自定义 OpenAI-compatible 七种选项；模型 ID 可编辑，自定义模式可填写 Base URL。
- 配置优先级为页面显式值、环境变量、供应商预设；旧版 `FACTORGUARD_LLM_BASE_URL` / `FACTORGUARD_LLM_MODEL` / `FACTORGUARD_LLM_API_KEY` 环境配置继续兼容。
- `FACTORGUARD_LLM_API_KEY` 仍是唯一密钥来源。页面没有密钥输入控件，只显示是否配置；密钥不进入 session state、请求正文、正式导出、日志或哈希，异常原因也会脱敏。
- 未知供应商、自定义配置不完整、缺少密钥、调用失败或响应校验失败均安全返回 `rule_fallback`。供应商、模型或经校验的 AI 文本变化会改变 `ai_analysis_hash`，不改变正式 `report_hash`。
- 最终发布候选验证：AI、核心与发布聚焦回归为 61 passed，全量 pytest 为 87 passed，`compileall` 通过；报告页仍只有 3 个正式下载按钮。
- `scripts/build_github_release.py` 与 `scripts/build_submission.py` 已重新生成发布包；GitHub 源码包、快照包和比赛包的精确扫描均未发现 `DataSource`、嵌套 `.git`、`__pycache__`、`.pytest_cache`、CSV、`.building` 或日志。
- GitHub 源码包独立解压后为 60 passed、1 skipped，且包内 `compileall` 通过；源码包叠加正式快照后为 59 passed。各 ZIP 的最终 SHA-256 记录在同目录旁侧 `.sha256` 文件中。

正式报告由确定性审计引擎生成；大模型只提供可引用、可校验、可降级的投研辅助解读，不参与正式裁决。

## 16. GitHub 版本发布（2026-08-21）

- 远程第一版保留原始历史，并以 `v0.1.0` 标记。
- 当前确定性审计与 AI 辅助解读版本发布为 `v1.0.0`；源码进入 `main`，正式快照仅作为 Release 附件分发，不进入 Git 历史。
- GitHub 仓库当前保持 Private。主项目尚未选择根级 `LICENSE`，转为 Public 前必须由项目所有者明确许可方案。
