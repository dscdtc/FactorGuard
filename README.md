# FactorGuard / 因子验真台

> **独立于回测平台的因子质量检查与验真层**
>
> 回测告诉您因子过去表现如何，FactorGuard 告诉您这个结论是否经得起质疑。

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
| 🏠 **工作台** | 新建鉴证、最近运行记录、Demo 入口 |
| 📥 **因子输入** | 因子导入：内置因子库 / 文本描述 / 受限公式 / 上传因子值 |
| 🔍 **传统评估** | 完整 Tear Sheet：IC / RankIC / ICIR / 分组收益 / 换手率 / IC 衰减 / 滚动统计 |
| 💪 **压力测试** | 对抗式检验：执行延迟 / 微盘暴露 / 中性化 / 极端样本 / Bootstrap 置信区间 |
| 🔗 **重复性检测** | 三重检测：公式结构 / 横截面暴露 / 收益序列相似度 |
| 📊 **适用性地图** | 多维度适用性热力图（市值 × 波动率 × 时间段 × 股票池） |
| 👨‍🏫 **大师方法拆解** | 拆解公开投资方法论为结构化原则与可鉴证的代理因子 |
| 🧾 **报告与凭证** | 总览报告、证据维度汇总、确定性哈希复现凭证 |
| 🧪 **鉴证运行** | 端到端鉴证流程编排与运行记录 |

**内置因子库：** 随附 3 个因子 Skill 仓库（方向性 Alpha / 风险模式 Alpha / 量价统计 Alpha），共 200+ 个标准化因子，均附带真实数据验证指标。

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
| 数据源 | 本地数据集 + akshare / baostock | 本地日线数据为主，免费开源数据源补充 |

```
本地数据 (H:\data\stock-trading-data-pro)
        │
        ▼
┌─────────────────────┐     ┌──────────────────────────┐
│  data_loader.py     │────▶│  data/snapshot/*.parquet │  冻结数据快照
│  (快照生成)         │     │  daily_ohlcv / daily_basic│
└─────────────────────┘     └──────────┬───────────────┘
                                       │
┌─────────────────────┐     ┌──────────▼───────────────┐
│  Factors/ 因子库     │────▶│  factor_computer.py      │  因子值计算
│  (SKILL.md + index) │     │  factor_cache/*.parquet  │  预计算缓存
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
├── app.py                  # Streamlit 主入口（多页面路由 + 全局状态）
├── config.py               # 全局配置（路径、参数、颜色映射）
├── requirements.txt        # Python 依赖清单
├── setup.bat               # Windows 一键环境初始化脚本
│
├── pages/                  # Streamlit 多页面模块
│   ├── 01_工作台.py
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
│   ├── factor_cache/       # 预计算因子值缓存
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
- 本地数据集（可选）：`H:\data\stock-trading-data-pro` — A 股全量股票日线行情（含 OHLCV、市值、PE/PB、行业分类）。缺失时项目使用 `data/snapshot/` 内已生成的 Parquet 快照。

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
| akshare ≥ 1.14 / baostock ≥ 0.8.8 | 补充数据源 |
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
> - 首次进入各页面时，请在「因子输入」页选择因子并预计算，后续页面即可直接使用缓存结果；
> - 已计算的评估结果会按 `因子 × 参数` 缓存在会话中，重复访问页面直接显示「📦 使用缓存数据」，无需重新计算；
> - Streamlit 支持代码热重载，修改代码后页面自动刷新。

### 5.5 指定端口启动（可选）

```bash
streamlit run app.py --server.port 8503
```

---

## 6. 数据说明

| 数据 | 位置 | 说明 |
|---|---|---|
| 行情快照 | `data/snapshot/daily_ohlcv.parquet` | A 股全量日线行情（合并生成） |
| 基础指标快照 | `data/snapshot/daily_basic.parquet` | 市值 / PE / PB / 流通市值 |
| 因子值缓存 | `data/factor_cache/{factor_id}.parquet` | 预计算因子值 |
| 元数据库 | `data/factor_master.duckdb` | 因子元数据、鉴证记录、预计算指标 |

### 修改数据文件目录

所有数据路径集中定义在 [config.py](config.py)，按需修改后**重启 Streamlit** 即可生效：

```python
# config.py

# 原始本地数据集（每只股票独立 CSV 的根目录）
DATA_LOCAL = Path("H:/data/stock-trading-data-pro")

# 冻结数据快照（Parquet，由 data_loader.py 从 DATA_LOCAL 合并生成）
DATA_SNAPSHOT = ROOT_DIR / "data" / "snapshot"

# 预计算因子值缓存目录
FACTOR_CACHE = ROOT_DIR / "data" / "factor_cache"

# DuckDB 元数据库（因子元数据、鉴证记录、预计算指标）
DB_PATH = ROOT_DIR / "data" / "factor_master.duckdb"
```

**常见场景：**

| 需求 | 修改方式 |
|---|---|
| 本地行情 CSV 存放在其他位置 | 修改 `DATA_LOCAL` 为实际路径，如 `Path("D:/my_stock_data")` |
| 快照 / 缓存 / 数据库放到项目外 | 修改 `DATA_SNAPSHOT`、`FACTOR_CACHE`、`DB_PATH` 为绝对路径 |
| 数据迁移到其他机器 | 先备份 `data/` 目录，再按新机器路径更新上述配置 |

> ⚠️ **注意：**
> - `DATA_LOCAL` 指向的原始 CSV 仅在首次生成快照时读取；若已有 `data/snapshot/*.parquet`，修改 `DATA_LOCAL` 后需删除旧快照才会重新生成；
> - `DB_PATH` 变更后，历史鉴证记录与预计算指标不会自动迁移，需一并复制 `.duckdb` 文件；
> - 路径建议使用正斜杠 `/` 或 `Path()` 对象，避免 Windows 反斜杠转义问题。

其他默认参数（预测周期、Bootstrap 配置等）同样在 [config.py](config.py) 中调整。

---

## 7. 相关文档

- [产品需求文档 PRD V1.1](DOC/FactorGuard_PRD_V1.1.md)
- [技术设计文档](DOC/FACTORGUARD_TECHNICAL_DESIGN.md)
- [MVP 任务清单](DOC/FactorGuard_MVP_TaskList.md)
