# FactorGuard / 因子验真台

> **独立于回测平台的因子质量检查与验真层**
>
> 回测告诉您因子过去表现如何，FactorGuard 告诉您这个结论是否经得起质疑。

> **当前版本说明：** 当前工作区和比赛提交包包含 2024-09-27 至 2025-09-26 的 A 股比赛快照，可执行真实评估与压力测试；GitHub 源码包为避免大文件进入 Git 历史，不捆绑 Parquet 和 DuckDB，正式快照通过 Release 附件分发或由用户显式重建。内置因子也可离线展示历史预计算摘要。预计算、演示和未测试结果会分别标记，不等同于完整实时鉴证。当前修复状态见 [PROJECT_STATUS](DOC/PROJECT_STATUS.md)。

🔬 [在线运行](#快速开始) | 📄 [PRD 文档](DOC/FactorGuard_PRD_V1.1.md) | 🏗️ [技术设计](DOC/FACTORGUARD_TECHNICAL_DESIGN.md)

---

## 1. 项目简介

FactorGuard 是一款面向个人量化研究者的**因子验真工具**。它不以生成更多因子为核心，而是把因子研究结论转化为**可检查、可反驳、可复现的证据对象**。

针对现有因子平台的常见盲区，FactorGuard 回答以下问题：

- 因子是否使用了**未来数据**？
- 财务或行情字段在测试时点是否**真实可用**？
- 好结果是否主要来自**小微盘、行业或低流动性暴露**？
- 结论是否只由**少数年份、股票或极端样本**贡献？
- 因子是否只是已有因子的**改名或单调变换**？
- 更改股票池、数据延迟或预处理后是否**立即失效**？
- 报告中的结论能否被他人**重新运行和验证**？

**边界声明：** 本产品是研究质量基础设施，不输出交易信号，不提供策略组合、择时、荐股和自动交易。

---

## 2. 核心功能

| 页面 | 功能 |
|---|---|
| 🏠 **首页** | 数据快照、新建鉴证、最近运行记录、四个 Demo 入口 |
| 📥 **因子输入** | 因子导入：内置因子库 / 文本描述 / 受限公式 / 上传因子值 |
| 🔍 **传统评估** | 完整 Tear Sheet：IC / RankIC / ICIR / 分组收益 / 换手率 / IC 衰减 / 滚动统计 |
| 💪 **压力测试** | 对抗式检验：执行延迟 / 微盘暴露 / 中性化 / 极端样本 / Bootstrap 置信区间 |
| 🔗 **重复性检测** | 三重检测：公式结构 / 横截面暴露 / 收益序列相似度 |
| 📊 **适用性地图** | 多维度适用性热力图（市值 × 波动率 × 时间段 × 股票池） |
| 👨‍🏫 **大师方法拆解** | 拆解公开投资方法论为结构化原则与可鉴证的代理因子 |
| 🧾 **报告与凭证** | 正式报告、确定性哈希复现凭证，以及独立的可校验 AI 辅助解读 Tab |
| 🧪 **鉴证运行** | 端到端鉴证流程编排与运行记录 |

大师方法页包含一个可真实计算的资本效率代理（净利润TTM/净资产）。由于本地数据没有财务公告日期，系统会明确将时间正确性标为未测试，最终不把代理结果包装成已经验证的“大师策略”。

**内置因子库：** 随附 3 个因子 Skill 仓库（方向性 Alpha / 风险模式 Alpha / 量价统计 Alpha），共 800 个标准化因子；另有 5 个异常 Demo 和 1 个大师代理，总计 806 个可选条目。内置标准因子附带历史真实数据验证指标。

---

## 3. 技术架构

| 层级 | 技术 | 说明 |
|---|---|---|
| 前端框架 | Streamlit ≥ 1.28 | 多页面应用，会话状态管理 |
| 图表库 | Plotly ≥ 5.18 | 交互式研究报告级图表 |
| 数据处理 | Pandas / NumPy / SciPy | 因子计算与时序统计 |
| 数据存储 | **Parquet 列式快照 + DuckDB** | 列式存储 + 向量化查询，较 SQLite 提速 10–100 倍 |
| 因子解析 | Lark ≥ 1.1 | 受限公式语言解析器，生成 AST（避免 `eval` 风险） |
| 数据模型 | Pydantic ≥ 2.5 | FactorSpec / Evidence / MasterMethod 等结构化模型 |
| 数据源 | 冻结 Parquet 快照 + 本地 CSV | 页面使用冻结快照；原始 CSV 仅用于显式重建 |

```
本地数据 (E:\Quantclass\stock-trading-data-pro)
        │
        ▼
┌─────────────────────┐     ┌──────────────────────────┐
│  data_loader.py     │────▶│  data/snapshot/*.parquet │  冻结数据快照
│  (快照生成)         │     │  daily_ohlcv / daily_basic│
└─────────────────────┘     └──────────┬───────────────┘
                                       │
┌─────────────────────┐     ┌──────────▼───────────────┐
│  Factors/ 因子库     │────▶│  factor_computer.py      │  因子值计算
│  (SKILL.md + index) │     │  session context cache   │  会话缓存
└─────────────────────┘     └──────────┬───────────────┘
                                       │
            ┌──────────────────────────┼──────────────────────────┐
            ▼                          ▼                          ▼
   traditional_eval.py         stress_test.py              suitability.py
   (传统评估 Tear Sheet)       (压力测试 + Bootstrap)      (适用性地图)
            │                          │                          │
            └──────────────┬───────────┴──────────────────────────┘
                           ▼
                evidence_engine.py  →  证据模型 + 结论生成
                           ▼
                hash_utils.py      →  确定性复现凭证
                           ▼
                run_recorder.py    →  鉴证运行记录 (factor_master.duckdb)
```

---

## 4. 项目结构

```
FactorGuard/
├── app.py                  # Streamlit 首页（数据快照 + 新建鉴证 + 最近运行 + Demo）
├── config.py               # 全局配置（路径、参数、颜色映射）
├── requirements.txt        # Python 依赖清单
├── setup.bat               # Windows 一键环境初始化脚本
│
├── pages/                  # Streamlit 多页面模块
│   ├── 02_因子输入.py
│   ├── 03_传统评估.py
│   ├── 04_压力测试.py
│   ├── 05_重复性检测.py
│   ├── 06_适用性地图.py
│   ├── 07_大师方法拆解.py
│   ├── 08_报告与凭证.py
│   └── 09_鉴证运行.py
│
├── engine/                 # 核心计算引擎
│   ├── data_loader.py      # 本地数据加载与 Parquet 快照生成
│   ├── duckdb_query.py     # DuckDB 查询层
│   ├── factor_loader.py    # 因子库加载（SKILL.md + factor_index.json）
│   ├── formula_parser.py   # Lark 受限公式解析器 → AST
│   ├── factor_computer.py  # 因子值计算
│   ├── data_aligner.py     # 数据对齐：因子值 × 收益标签 × 股票池
│   ├── traditional_eval.py # IC / RankIC / 分组 / 换手 / 衰减
│   ├── bootstrap.py        # Bootstrap 置信区间（按日期分块）
│   ├── stress_test.py      # 压力测试引擎
│   ├── suitability.py      # 适用性地图引擎
│   ├── duplicate_detect.py # 三重重复检测
│   ├── evidence_engine.py  # 证据模型与结论生成
│   ├── hash_utils.py       # 确定性哈希（evidence_hash / report_hash）
│   └── run_recorder.py     # 鉴证运行记录
│
├── models/                 # Pydantic 数据模型
├── ui/                     # UI 工具（图表、指标卡片、配色）
├── utils/                  # 通用工具（交易日历、预处理、IO）
│
├── data/                   # 数据存储（运行时生成）
│   ├── snapshot/           # 冻结数据快照（Parquet）
│   ├── factor_cache/       # 预留的磁盘因子缓存（当前未启用）
│   └── factor_master.duckdb# DuckDB 元数据库
│
├── Factors/                # 内置因子库（只读引用，3 个 Skill 仓库）
└── DOC/                    # PRD 与技术设计文档
```

---

## 5. 快速开始

### 5.1 环境要求

- **Python ≥ 3.11**
- **Windows 10/11**（项目在 Windows 环境开发验证；Linux/macOS 亦可运行，仅需调整激活脚本）
- 本地数据集（仅重建快照时需要）：默认 `E:\Quantclass\stock-trading-data-pro`，也可通过环境变量 `FACTORGUARD_DATA_LOCAL` 指定。页面只读取随项目提供的 `data/snapshot/`，换电脑运行不需要复制原始 CSV。

### 5.2 方式一：Windows 一键初始化

```bash
# 在项目根目录执行
setup.bat
```

脚本将自动完成：创建虚拟环境 → 激活 → 升级 pip → 安装全部依赖。

### 5.3 方式二：手动安装

```bash
# 1. 创建并激活虚拟环境
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux / macOS

# 2. 安装依赖
pip install -r requirements.txt
```

需要重建比赛快照时显式执行：

```bash
py scripts/build_snapshots.py --date-start 2024-09-27 --date-end 2025-09-26
```

原始数据不在默认位置时：

```powershell
$env:FACTORGUARD_DATA_LOCAL = "D:\your-data\stock-trading-data-pro"
py scripts/build_snapshots.py --date-start 2024-09-27 --date-end 2025-09-26
```

构建过程逐 CSV 流式写入 Parquet；页面不会自动触发该任务。完整源目录首次构建约需十余分钟，完成后读取快照为秒级。

<details>
<summary>依赖清单（点击展开）</summary>

| 依赖 | 用途 |
|---|---|
| streamlit ≥ 1.28 | Web 前端框架 |
| plotly ≥ 5.18 | 交互式图表 |
| pandas ≥ 2.1 / numpy ≥ 1.26 | 数据处理与数值计算 |
| scipy ≥ 1.11 | 统计检验 |
| lark ≥ 1.1 | 受限公式解析器 |
| pydantic ≥ 2.5 | 数据模型 |
| pyarrow ≥ 14.0 | Parquet 读写 |
| duckdb ≥ 1.0 | 列式查询引擎 |
| openpyxl ≥ 3.1 | Excel 导出 |

</details>

### 5.4 启动应用

```bash
# 确保虚拟环境已激活
venv\Scripts\activate

# 启动 Streamlit 服务
streamlit run app.py
```

启动后浏览器自动打开 **http://localhost:8501**，即可通过左侧导航栏进入各功能页面。

> 💡 **使用提示：**
> - 首次使用时先在「因子输入」页选择因子；有正式行情快照时实时计算，没有快照时仅展示内置因子的历史预计算摘要；
> - 已计算结果按因子规格、上传数据、前瞻周期、时间范围、Bootstrap 参数和数据快照身份缓存在会话中；上下文一致时重复访问会直接使用缓存；
> - Streamlit 支持代码热重载，修改代码后页面自动刷新。

### 5.5 指定端口启动（可选）

```bash
streamlit run app.py --server.port 8503
```

同一局域网设备访问时，可显式监听全部接口：

```bash
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

### 5.6 AI 辅助解读模型配置（可选）

完成正式鉴证后，在“报告与凭证 → AI 辅助解读”中选择供应商和模型 ID。当前内置 OpenAI、DeepSeek、通义千问 / DashScope、智谱、Moonshot / Kimi、硅基流动及自定义 OpenAI-compatible 七种选项。

API Key 不在页面填写，只从启动 Streamlit 的同一终端环境读取：

```powershell
$env:FACTORGUARD_LLM_PROVIDER = "deepseek"
$env:FACTORGUARD_LLM_API_KEY = "<your-api-key>"
py -m streamlit run app.py --server.port 8501
```

页面可编辑模型 ID。需要固定默认值、使用企业代理或自定义兼容服务时，可额外设置：

```powershell
$env:FACTORGUARD_LLM_MODEL = "deepseek-chat"
$env:FACTORGUARD_LLM_BASE_URL = "https://api.deepseek.com"
$env:FACTORGUARD_LLM_TIMEOUT = "20"
```

自定义供应商必须提供兼容 Chat Completions 的 Base URL 和模型 ID。旧版仅设置 `FACTORGUARD_LLM_BASE_URL`、`FACTORGUARD_LLM_MODEL`、`FACTORGUARD_LLM_API_KEY` 的方式仍然有效。环境变量修改后需重启 Streamlit；未配置密钥或调用失败时自动显示 `rule_fallback`。

密钥不会进入页面控件、Streamlit session state、模型请求正文、正式报告或哈希。正式报告与 AI 辅助解读使用彼此独立的哈希边界。

### 5.7 GitHub 源码包的数据准备

`FactorGuard_github_source.zip` 不包含 Parquet 和 DuckDB。需要运行真实全市场鉴证时，从 GitHub Release 下载 `FactorGuard_snapshot_20240927_20250926.zip`，解压后保证目录结构如下：

```text
FactorGuard/
└── data/
    └── snapshot/
        ├── daily_ohlcv.parquet
        ├── daily_basic.parquet
        ├── stock_basic.parquet
        └── manifest.json
```

也可以使用自己的原始 CSV 显式重建快照。没有 Parquet 时，应用仍可读取因子仓库中的历史预计算摘要，但不会把它冒充本次实时鉴证。

---

## 6. 数据说明

| 数据 | 位置 | 说明 |
|---|---|---|
| 快照清单 | `data/snapshot/manifest.json` | 构建参数、日期范围、行数、股票数和 SHA-256 |
| 行情快照 | `data/snapshot/daily_ohlcv.parquet` | 近一年 A 股全市场日线，1,314,224 行 / 5,473 只 |
| 基础指标快照 | `data/snapshot/daily_basic.parquet` | 市值 / 换手率 / 利润与现金流 / 资产负债 |
| 因子值缓存 | `data/factor_cache/` | 预留路径，当前版本尚未启用磁盘级因子缓存 |
| 元数据库 | `data/factor_master.duckdb` | 因子元数据、鉴证记录、预计算指标 |

原始数据目录可用 `FACTORGUARD_DATA_LOCAL` 覆盖，快照目录可用 `FACTORGUARD_SNAPSHOT_DIR` 覆盖；其余默认参数见 [config.py](config.py)。

GitHub 源码仓库只跟踪快照说明和清单，不跟踪 `.parquet`、`.duckdb`、原始 CSV 或 API Key。比赛可运行包与 GitHub 源码包是两个独立发布产物。

### 6.1 生成比赛提交包

```powershell
py scripts/build_submission.py
```

输出位于 `dist/FactorGuard_submission.zip`，并附带 SHA-256 文件。提交包自动排除上游 `DataSource` 仓库、嵌套 `.git`、测试缓存、旧截图、复制 CSV 和 `.building` 中间文件。

---

## 7. 相关文档

- [产品需求文档 PRD V1.1](DOC/FactorGuard_PRD_V1.1.md)
- [技术设计文档](DOC/FACTORGUARD_TECHNICAL_DESIGN.md)
- [当前状态与正确性修复规范](DOC/PROJECT_STATUS.md)
- [原版与当前版对比及 GitHub 发布建议](DOC/PROJECT_COMPARISON_20260819_TO_CURRENT.md)
- [比赛演示脚本](DOC/COMPETITION_DEMO_SCRIPT.md)
