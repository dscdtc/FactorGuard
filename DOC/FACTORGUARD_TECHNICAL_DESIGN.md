# FactorGuard 技术设计文档

> 基于 PRD V1.1 修订版 | 目标提交：2026年8月31日 | 版本：MVP 1.0
>
> **实现校准（2026-08-20）：** 当前代码使用 DuckDB + Parquet。运行历史、证据哈希和报告哈希已经持久化；工作副本包含全市场近一年比赛快照，`data/factor_cache/` 仍是预留路径。最终状态与验证证据见 [PROJECT_STATUS.md](PROJECT_STATUS.md)。

---

## 1. 技术选型

| 层级 | 技术 | 版本要求 | 说明 |
|---|---|---|---|
| 前端框架 | Streamlit | >= 1.28 | 单文件多页面应用，天然支持状态管理和组件化 |
| 图表库 | Plotly | >= 5.18 | 交互式图表，支持 SVG/Canvas 渲染 |
| 数据处理 | Pandas | >= 2.1 | 因子计算、CSV 读写、时序操作 |
| 数值计算 | NumPy | >= 1.26 | 矩阵运算、统计指标 |
| 数据库 | DuckDB | `duckdb` | 因子元数据、预计算指标与鉴证记录 |
| 因子解析 | Lark | >= 1.1 | 受限公式语言解析器，生成 AST |
| 环境管理 | venv | Python 3.11+ | 隔离开发环境 |
| 数据源（主） | 本地数据 `E:\Quantclass\stock-trading-data-pro` | — | 每只股票独立 CSV，含日线 OHLCV、市值、换手率、利润/现金流、资产负债和行业分类 |
| 数据源（辅） | 未接入 | — | akshare / baostock 仅作为后续补充方案，不是当前运行依赖 |

### 1.1 选型理由

**Streamlit：** 单文件即可构建完整页面，无需前后端分离，适合 MVP 快速迭代。原生支持会话状态、文件上传、侧边栏组件，与 Plotly 无缝集成。

**Plotly：** 支持缩放、悬停、导出等交互操作，比 Matplotlib 更适合研究报告级图表展示。内置 `plotly.subplots` 支持多图联排。

**DuckDB：** 统一管理因子元数据和预计算指标，并与 Parquet 快照配合。当前 `audit_runs` 表已建表，运行历史写入由 `run_recorder.py` 负责。

**Lark：** Python 原生解析器生成器，支持上下文无关文法，用于实现受限公式语言的 AST 解析，避免 `eval` 安全风险。

**本地数据源：** 本地 CSV 数据集覆盖 A 股全量股票日线行情（沪深京三地），包含 OHLCV、市值、换手率、利润/现金流、资产负债和行业分类，零网络依赖、零 API 调用限制。源文件不含 PE/PB，也缺少财务披露时点，因此这些字段不能冒充历史时点可用的估值或质量证据。免费三方数据源（akshare / baostock）只作为后续补充方案。

---

## 2. 项目目录结构

```
FactorGuard/
├── venv/                          # Python 虚拟环境（gitignore）
├── requirements.txt               # 依赖清单
├── setup.bat                      # Windows 一键环境初始化脚本
├── app.py                         # 首页：快照、新建鉴证、最近运行、Demo 入口
├── config.py                      # 全局配置（路径、参数、颜色映射）
│
├── pages/                         # Streamlit 多页面模块
│   ├── 02_ 📥_因子输入.py         # 因子输入：内置/规则文本/受限公式/因子值上传
│   ├── 03_ 🔍_传统评估.py         # Tear Sheet：IC/RankIC/分组/换手/衰减/滚动
│   ├── 04_ 💪_压力测试.py         # 对抗式压力测试视图
│   ├── 05_ 🔗_重复性检测.py       # 因子关系：公式/暴露/收益三层检测
│   ├── 06_ 📊_适用性地图.py       # 多维度适用性热力图
│   ├── 07_ 👨‍🏫_大师方法拆解.py     # 公开方法来源、原则、代理因子
│   ├── 08_ 🧾_报告与凭证.py       # 总览报告、证据维度、复现凭证
│   └── 09_ 🧪_鉴证运行.py         # 一站式鉴证流程与运行记录
│
├── engine/                        # 核心计算引擎
│   ├── __init__.py
│   ├── data_loader.py             # 本地 CSV 数据加载与快照生成
│   ├── factor_loader.py           # 从 SKILL.md 和 factor_index.json 加载因子
│   ├── formula_parser.py          # Lark 受限公式解析器 → AST
│   ├── factor_computer.py         # 因子值计算（调用 agent 的 factor.py）
│   ├── data_aligner.py            # 数据对齐：因子值 × 收益标签 × 股票池
│   ├── traditional_eval.py        # 传统评估：IC/RankIC/ICIR/分组收益/换手/衰减
│   ├── bootstrap.py               # Bootstrap 置信区间（按日期分块）
│   ├── stress_test.py             # 压力测试：延迟/微盘/中性化/极端样本
│   ├── suitability.py             # 适用性地图计算引擎
│   ├── duplicate_detect.py        # 三重重复检测
│   ├── evidence_engine.py         # 证据模型、结论生成
│   ├── hash_utils.py              # 确定性哈希（evidence_hash/report_hash）
│   ├── ai_explainer.py            # 确定性规则解析与证据解释
│   └── ai_analysis.py             # 证据约束模型适配、输出校验与规则降级
│
├── models/                        # 数据模型（Pydantic）
│   ├── __init__.py
│   ├── factor_spec.py             # FactorSpec V2 模型
│   ├── evidence.py                # 证据记录模型
│   ├── master_method.py           # MasterMethodSpec 模型
│   └── audit_result.py            # 鉴证结果模型
│
├── data/                          # 数据存储
│   ├── snapshot/                  # 冻结数据快照（Parquet，从本地CSV合并生成）
│   │   ├── daily_ohlcv.parquet    # 日线行情（合并所有 sh/sz/bj CSV）
│   │   ├── daily_basic.parquet    # 市值/换手率/利润现金流/资产负债
│   │   └── stock_basic.parquet    # 股票列表（代码、名称、上市日期、行业）
│   ├── factor_cache/              # 预留的磁盘因子缓存（当前未启用）
│   │   └── {factor_id}.parquet
│   └── factor_master.duckdb       # DuckDB 数据库
│
├── Factors/                       # 现有因子库（只读引用）
│   ├── skill-quant-factor-directional-alpha/
│   ├── skill-quant-factor-risk-pattern-alpha/
│   └── skill-quant-factor-volume-stat-alpha/
│
├── DataSource/                    # 外部数据源与方法论参考（只读）
│   └── ai-berkshire/              # AI Berkshire 投资研究框架
│       ├── codex-skills/          # 去劣筛选、财报研读、论文追踪等 Skill
│       ├── codex-prompts/         # 各 Skill 的入口 prompt
│       ├── reports/               # 四大视角（段永平/巴菲特/芒格/李录）的个股研究报告
│       └── data/                  # fundamentals.json + watchlist.json
│
├── ui/                            # UI 工具函数
│   ├── __init__.py
│   ├── chart_utils.py             # Plotly 图表工厂
│   ├── color_utils.py             # 颜色方案、饱和度映射
│   ├── metric_cards.py            # 指标卡片组件
│   └── table_utils.py             # 表格样式工具
│
├── utils/                         # 通用工具
│   ├── __init__.py
│   ├── calendar.py                # 交易日历
│   ├── preprocess.py              # 去极值、标准化、中性化
│   └── io_utils.py                # CSV/Parquet 读写工具
│
├── tests/                         # 测试
│   ├── test_formula_parser.py
│   ├── test_traditional_eval.py
│   ├── test_stress_test.py
│   ├── test_duplicate_detect.py
│   └── test_hash_utils.py
│
└── FACTORGUARD_TECHNICAL_DESIGN.md  # 本文档
```

---

## 3. 核心数据模型

### 3.1 FactorSpec V2（因子定义）

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import date

class FactorSpec(BaseModel):
    factor_id: str                          # 稳定唯一标识，如 "R004"
    name: str                               # 因子名称
    name_cn: str                            # 中文名称
    version: str = "1.0.0"                  # 因子版本
    description: str                        # 自然语言定义
    formula: Optional[str] = None           # 受限公式或描述
    formula_cn: Optional[str] = None        # 中文公式描述
    expected_direction: Literal["higher", "lower"]
    category: str                           # 分类：动量/反转/趋势/波动/成交量/质量
    base: str                               # 基础信号类型
    transform: str                          # 变换类型
    params: dict                            # 参数 {window, norm, lag, smooth, ...}
    inputs: list[str]                       # 所需数据字段 ["open","high","low","close","volume"]
    frequency: Literal["1d"] = "1d"         # MVP 固定日频
    availability: str = "after_close"       # 观察时点
    availability_lag: int = 1               # 额外延迟交易日数
    min_window: int = 20                    # 最小回看窗口
    universe_rule: str = "historical_all_a" # 股票池规则
    preprocess: str = "mad3_zscore"         # 预处理方法
    neutralization: Optional[str] = None    # 中性化方式
    source: str                             # 内置/用户/上传
    source_reference: Optional[str] = None  # 来源说明
    rationale_cn: Optional[str] = None      # 因子逻辑说明
```

### 3.2 证据记录（Evidence）

```python
class EvidenceRecord(BaseModel):
    evidence_id: str                        # 证据唯一标识
    dimension: str                          # 证据维度
    severity: Literal["pass", "warn", "fail", "untested"]
    claim: str                              # 声明
    evidence_ids: list[str] = []            # 引用的子证据
    metrics: dict = {}                      # 指标快照
    explanation: str = ""                   # 解释
```

### 3.3 鉴证结果（AuditResult）

```python
class AuditResult(BaseModel):
    factor_id: str
    run_id: str
    timestamp: str
    data_snapshot: str
    evidence_hash: str
    report_hash: str
    conclusion: Literal[
        "invalid", "insufficient", "fragile", "conditional", "supported"
    ]
    evidence_dimensions: dict               # 五维度评级
    risk_summary: list[str]
    next_test: Optional[str]
    evidence_records: list[EvidenceRecord]
```

### 3.4 大师方法（MasterMethodSpec）

**参考来源：** `DataSource/ai-berkshire/` 项目中的 `quality-screen`（去劣筛选）Skill 提供了大师方法拆解的完整范式——将投资大师的定性原则转化为可量化指标，并通过因子代理进行验证。

```python
class Principle(BaseModel):
    id: int
    name: str                               # 原则名称，如 "资本效率"
    description: str                        # 原则描述
    master_perspective: str                 # 对应大师视角：巴菲特/段永平/芒格/李录
    proxy_factors: list[str]                # 代理因子 ID 列表
    proxy_grade: Literal["A", "B", "C", "U"]# 代理质量等级
    proxy_limitations: str                  # 代理局限说明
    measurable: bool = True                 # 是否可量化

class MasterMethodSpec(BaseModel):
    method_id: str                          # 方法唯一标识
    name: str                               # 方法名称，如 "巴菲特质量框架"
    source_title: str                       # 来源标题
    source_reference: str                   # 来源引用
    source_excerpt: str                     # 原文摘录
    principles: list[Principle]             # 原则列表
    exemption_rules: list[dict] = []        # 豁免规则（参考 quality-screen 的 3 条豁免）
    data_requirements: list[str]            # 数据要求
    limitations: str                        # 局限性声明
    ai_berkshire_skill: Optional[str] = None  # 对应的 ai-berkshire Skill 名称
```

### 3.5 大师方法映射：ai-berkshire 质量框架 → 因子代理

ai-berkshire 的 `quality-screen` 定义了 **7 条去劣指标 + 3 条豁免规则**，为 FactorGuard 的大师方法模块提供了直接的量化方法论参考：

| # | ai-berkshire 指标 | 量化方向 | 因子代理候选 | 数据可用性 | 代理等级 |
|---|---|---|---|---|---|
| 1 | 10年平均ROE < 8% | 资本效率 | ROE 稳定性因子 | 本地数据含净利润/净资产 | B |
| 2 | 5年累计FCF为负 | 真金白银 | 经营现金流/净利润比 | 需 akshare 补充现金流量表 | C |
| 3 | 利息覆盖 < 2倍 | 偿债安全 | EBIT/利息支出 | 需 akshare 补充 | C |
| 4 | 长期毛利率 < 15% | 定价权 | 毛利率稳定性因子 | 本地数据可推算(收入-成本)/收入 | C |
| 5 | 经营现金流/净利润 < 0.7 | 利润质量 | 现金流质量因子 | 需 akshare 补充 | C |
| 6 | 长期净利率 < 5% | 抗风险 | 净利率因子 | 本地数据含净利润 | B |
| 7 | 5年总股本膨胀 > 20% | 股东利益 | 股本变化因子 | 本地数据可推算 | B |

**MVP Demo D 策略：** 选取代理等级为 B 的指标（ROE 稳定性、净利率、股本变化），结合本地数据可获取的字段构建 3-4 个可验证代理因子，其余 C 级代理标记为"不可鉴证"并展示局限说明。这与 ai-berkshire 的"数据不足时标注而非强行判定"原则一致。

---

## 4. 数据库设计（DuckDB）

### 4.1 表结构

```sql
-- 因子元数据缓存
CREATE TABLE factor_metadata (
    factor_id       TEXT PRIMARY KEY,
    name_cn         TEXT NOT NULL,
    category        TEXT NOT NULL,
    expected_direction TEXT NOT NULL,
    source          TEXT NOT NULL,          -- 'builtin' | 'user' | 'upload'
    spec_json       TEXT NOT NULL,          -- FactorSpec JSON
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- 鉴证运行记录
CREATE TABLE audit_runs (
    run_id          TEXT PRIMARY KEY,
    factor_id       TEXT NOT NULL,
    status          TEXT NOT NULL,          -- 'running' | 'completed' | 'failed'
    conclusion      TEXT,                   -- see AuditResult.conclusion
    evidence_hash   TEXT,
    report_hash     TEXT,
    run_params      TEXT,                   -- JSON: 时间范围、预处理等
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    error_message   TEXT,
    FOREIGN KEY (factor_id) REFERENCES factor_metadata(factor_id)
);

-- 预计算评估结果缓存
CREATE TABLE precomputed_results (
    factor_id       TEXT NOT NULL,
    metric_name     TEXT NOT NULL,          -- 'rank_ic_mean' | 'icir' | 'coverage' | ...
    metric_value    REAL,
    metric_meta     TEXT,                   -- JSON: 置信区间、样本数等
    computed_at     TEXT NOT NULL,
    PRIMARY KEY (factor_id, metric_name)
);

-- 适用性地图缓存
CREATE TABLE suitability_cache (
    factor_id       TEXT NOT NULL,
    dim1            TEXT NOT NULL,
    dim1_value      TEXT NOT NULL,
    dim2            TEXT NOT NULL,
    dim2_value      TEXT NOT NULL,
    rank_ic         REAL,
    sample_count    INTEGER,
    evidence_level  TEXT,                   -- 'good' | 'mid' | 'weak' | 'na'
    PRIMARY KEY (factor_id, dim1, dim1_value, dim2, dim2_value)
);
```

### 4.2 初始化策略

MVP 启动时，`factor_loader.py` 扫描 Factors/ 目录下的三个 Skill 仓库，解析 `factor_index.json` 获取因子元数据，解析 `validation_summary_real.json` 获取预计算指标，批量写入 DuckDB。DuckDB 不可用时，读取接口回退到仓库 JSON 文件。

---

## 5. 核心引擎设计

### 5.0 数据加载器（data_loader.py）

**职责：** 从本地 `E:\Quantclass\stock-trading-data-pro` 加载全量 A 股日线数据，合并生成快照 Parquet。

#### 本地数据格式

```
E:\Quantclass\stock-trading-data-pro\
├── sh600000.csv    # 沪市主板
├── sh600001.csv
├── ...
├── sh688xxx.csv    # 科创板
├── sz000001.csv    # 深市主板
├── sz002xxx.csv    # 中小板
├── sz300xxx.csv    # 创业板
├── bj920xxx.csv    # 北交所
└── ...
```

**单文件 CSV 结构（GBK 编码）：**

| 列名 | 类型 | 说明 | 因子计算必需 |
|---|---|---|---|
| 股票代码 | str | 如 `sh600000` | ✅ |
| 股票名称 | str | 中文名称 | — |
| 交易日期 | date | `YYYY-MM-DD` | ✅ |
| 开盘价 | float | 日开盘价 | ✅ |
| 最高价 | float | 日最高价 | ✅ |
| 最低价 | float | 日最低价 | ✅ |
| 收盘价 | float | 日收盘价 | ✅ |
| 前收盘价 | float | 前一日收盘价 | — |
| 成交量 | float | 日成交量（股） | ✅ |
| 成交额 | float | 日成交额（元） | — |
| 流通市值 | float | 流通市值（元） | ✅ |
| 总市值 | float | 总市值（元） | ✅ |
| 净利润TTM | float | 滚动净利润（源文件未提供披露时点） | 仅作数据字段，不直接作为时点正确证据 |
| 现金流TTM | float | 滚动现金流（源文件未提供披露时点） | 仅作数据字段，不等同于 PCF |
| 总资产 | float | 总资产 | 质量维度 |
| 净资产 | float | 净资产 | 质量维度 |
| 总负债 | float | 总负债 | 质量维度 |
| 净利润(当季) | float | 当季净利润（源文件未提供披露时点） | 仅作数据字段 |
| 沪深300成分股 | bool | 是否沪深300 | 股票池过滤 |
| 上证50成分股 | bool | 是否上证50 | 股票池过滤 |
| 中证500成分股 | bool | 是否中证500 | 股票池过滤 |
| 中证1000成分股 | bool | 是否中证1000 | 股票池过滤 |
| 中证2000成分股 | bool | 是否中证2000 | 股票池过滤 |
| 创业板指成分股 | bool | 是否创业板指 | 股票池过滤 |
| 申万一级行业分类 | str | 行业分类 | 行业中性化 |
| 申万二级行业分类 | str | 细分行业 | — |
| 申万三级行业分类 | str | 细分行业 | — |

**缺失字段（需免费三方数据源补充）：**

| 缺失字段 | 补充来源 | 说明 |
|---|---|---|
| ST 状态 | akshare `stock_st_ths` | 是否 ST / *ST |
| 退市日期 | akshare `stock_info_a_code_name` | 退市日期 |
| 复权因子 | baostock `query_adjust_factor` | 后复权因子 |
| 停牌状态 | 从本地数据推断（成交量=0） | 近似判断 |
| 历史 PE/PB | 待选定可靠来源 | 当前 CSV 不提供；成长价值维度保持未测试 |
| 财务披露时点 | 待选定可靠来源 | 当前 CSV 不提供；财务因子不得据此声称无未来数据 |

**加载流程：**

```
1. 页面检查 data/snapshot/ 下是否存在快照 Parquet
   ├── 存在 → 直接加载
   └── 不存在 → 快速降级为预计算展示，不扫描原始 CSV
2. 用户显式运行 `scripts/build_snapshots.py` 后流式构建：
   a. 遍历 E:\Quantclass\stock-trading-data-pro\*.csv
   b. 对每个文件：
      - 使用 GBK 编码读取
      - 跳过第一行（数据来源说明）
      - 标准化列名：股票代码→ts_code, 交易日期→trade_date, 开盘价→open, ...
      - 日期列转为 datetime
      - 可选按闭区间 `date_start/date_end` 过滤
      - 按 (ts_code, trade_date) 排序并去重
      - 立即写入 Parquet row group，不在内存中累积全市场 DataFrame
   c. 提取行情列写入 daily_ohlcv.parquet（ZSTD 压缩）
   d. 提取市值、换手率、利润现金流和资产负债列写入 daily_basic.parquet
   e. 每只股票保留最新一条名称和行业，写入 stock_basic.parquet
3. 先写 `.building` 临时文件；三份均成功后原子替换正式快照
4. 构建参数、行数、范围和文件哈希记录在 `data/snapshot/manifest.json`
```

**关键实现：**

```python
import pandas as pd
from pathlib import Path

DATA_ROOT = Path("E:/Quantclass/stock-trading-data-pro")
SNAPSHOT_DIR = Path("data/snapshot")

COLUMN_MAP = {
    "股票代码": "ts_code",
    "股票名称": "name",
    "交易日期": "trade_date",
    "开盘价": "open",
    "最高价": "high",
    "最低价": "low",
    "收盘价": "close",
    "前收盘价": "pre_close",
    "成交量": "volume",
    "成交额": "amount",
    "流通市值": "circ_mv",
    "总市值": "total_mv",
    "净利润TTM": "net_profit_ttm",
    "现金流TTM": "cash_flow_ttm",
    "总资产": "total_assets",
    "净资产": "net_assets",
    "总负债": "total_liability",
    "净利润(当季)": "net_profit_quarter",
    "新版申万一级行业名称": "industry_l1",
    "新版申万二级行业名称": "industry_l2",
    "新版申万三级行业名称": "industry_l3",
}

def load_all_csvs() -> pd.DataFrame:
    """加载本地所有 CSV 并合并为统一 DataFrame"""
    frames = []
    for csv_path in DATA_ROOT.glob("*.csv"):
        df = pd.read_csv(
            csv_path,
            encoding="gbk",
            skiprows=1,  # 跳过第一行数据来源说明
            parse_dates=["交易日期"]
        )
        df.rename(columns=COLUMN_MAP, inplace=True)
        # 只保留 COLUMN_MAP 中定义的列
        cols = [c for c in COLUMN_MAP.values() if c in df.columns]
        frames.append(df[cols])
    result = pd.concat(frames, ignore_index=True)
    result = result.sort_values(["ts_code", "trade_date"]).drop_duplicates(
        subset=["ts_code", "trade_date"]
    )
    return result
```

### 5.1 因子加载器（factor_loader.py）

**职责：** 扫描三个 Skill 仓库，加载因子元数据和预计算指标。

**输入：** Factors/ 目录路径

**处理流程：**

```
1. 遍历 Factors/*/factor_index.json
2. 对每个因子：
   a. 读取 factor_index.json 获取元数据（factor_id, name_cn, category, params, formula_cn, rationale_cn）
   b. 读取 validation_summary_real.json 获取预计算指标（ic_mean_5d, icir_5d, coverage, turnover, status）
   c. 读取 SKILL.md 获取方向和计算说明
   d. 构建 FactorSpec 对象
   e. 写入 DuckDB factor_metadata 和 precomputed_results 表
3. 返回因子列表
```

**关键点：**
- 仅加载 status="pass" 且 no_future_check=true 的因子
- 预计算指标来自真实数据（A股日线），可直接用于展示
- 因子按 category 分类：动量、反转、趋势、波动、成交量、风险

### 5.2 公式解析器（formula_parser.py）

**职责：** 将受限公式转为 AST，验证安全性和合法性。

**文法定义（Lark EBNF）：**

```python
GRAMMAR = r"""
    ?start: expression

    ?expression: add_expr

    ?add_expr: mul_expr
        | add_expr "+" mul_expr   -> add
        | add_expr "-" mul_expr   -> sub

    ?mul_expr: unary
        | mul_expr "*" unary      -> mul
        | mul_expr "/" unary      -> div

    ?unary: atom
        | "-" unary               -> neg

    ?atom: NUMBER
        | CNAME
        | func_call
        | "(" expression ")"

    func_call: CNAME "(" [expression ("," expression)*] ")"

    NUMBER: /-?\d+(\.\d+)?/
    CNAME: /[a-zA-Z_][a-zA-Z0-9_]*/
    %ignore " "
"""
```

**白名单字段：** `open`, `high`, `low`, `close`, `volume`, `amount`, `total_mv`, `circ_mv`, `turnover_rate`

**白名单函数：** `delay`, `ts_mean`, `ts_sum`, `ts_std`, `rank_cs`, `zscore_cs`, `log`, `abs`

**检查规则：**
1. `delay(x, n)` 中 n 必须 >= 0
2. 滚动窗口函数（ts_mean/ts_sum/ts_std）的窗口参数必须为正整数
3. 所有字段名和函数名必须在白名单内
4. 计算最长回看窗口（max delay + max rolling window）
5. 检查除零、log(0) 或负值风险

### 5.3 因子计算器（factor_computer.py）

**职责：** 调用 agent 中的 `factor.py` 计算因子值。

**处理流程：**

```
1. 根据 factor_id 定位到 Factors/*/factors/{factor_id}-{slug}/scripts/factor.py
2. 通过 importlib 动态加载模块
3. 调用 compute_factor(df) 传入日线数据
4. 返回 (factor_column_name, factor_values_df)
```

**数据输入规范：**
- DataFrame 必须包含列：`open`, `high`, `low`, `close`, `volume`, `trade_date`, `ts_code`
- 数据按 (`ts_code`, `trade_date`) 排序
- 每个 ts_code 独立计算因子值
- 数据来自本地 CSV 合并后的快照 Parquet

### 5.4 数据对齐器（data_aligner.py）

**职责：** 将因子值、收益标签和股票池对齐到统一的时间截面。

**处理流程：**

```
1. 加载因子值 DataFrame（trade_date, ts_code, factor_value）
2. 加载日线行情 DataFrame（trade_date, ts_code, open, close）
3. 构建股票池：按上市/退市日期过滤，剔除 ST 和停牌
4. 计算前瞻收益标签：forward_return = open[t+5] / open[t+1] - 1（跳过停牌）
5. 按 trade_date 对齐因子值和收益标签
6. 返回对齐后的 DataFrame
```

**关键约束：**
- 必须使用历史时点股票池，不可仅用当前上市股票
- 收益标签使用下一交易日开盘价，避免未来信息
- 停牌和涨跌停样本在 P1 中处理

### 5.5 传统评估引擎（traditional_eval.py）

**职责：** 计算完整的传统评估 Tear Sheet 指标。

**核心指标：**

| 指标 | 计算方式 | 说明 |
|---|---|---|
| IC Mean | 每日 Pearson 相关系数均值 | 因子值与收益的线性关系 |
| RankIC Mean | 每日 Spearman 秩相关系数均值 | 排序信息含量 |
| ICIR | IC Mean / IC Std（年化） | 信息比率 |
| IC 显著性 | t 检验 | 是否显著不等于 0 |
| 方向一致率 | 因子方向与 IC 符号一致的天数占比 | 与预期方向的一致性 |
| 分组收益 | 每日等数量 N 分组平均收益 | 单调性检验 |
| 累计收益 | 各分组累计对数收益 | 长期表现 |
| 换手率 | Top/Bottom 分组日均换手率 | 交易成本代理 |
| 衰减 | 1d/5d/10d 预测周期的 IC 变化 | 信号衰减速度 |
| 覆盖率 | 有效因子值占比时间序列 | 数据可用性 |
| 滚动 IC | 63 日滚动 RankIC 均值 | 稳定性 |

**实现要点：**
- 使用 Pandas `groupby("trade_date").apply(...)` 进行逐日截面计算
- 分组收益使用 `pd.qcut(factor, 5, labels=False)` 等数量分组
- 滚动指标使用 `rolling(window=63, min_periods=30)`

### 5.6 Bootstrap 置信区间（bootstrap.py）

**职责：** 按日期分块 Bootstrap 计算 RankIC Mean 的置信区间。

**参数：** 块长=20 日，重复=500 次，固定种子=20260815

**算法：**
```
1. 将日期序列按 20 日分块
2. 对于每次抽样（500次）：
   a. 从块中随机选择 ceil(N/20) 个块（有放回）
   b. 计算该样本的 RankIC Mean
3. 计算 500 个 RankIC Mean 的 2.5% 和 97.5% 分位数作为 95% CI
```

### 5.7 压力测试引擎（stress_test.py）

**职责：** 执行四项对抗式压力测试。

| 测试 | 方法 | 判断标准 |
|---|---|---|
| 数据延迟 | 因子值整体延迟 1 个交易日 | 方向是否保持，RankIC 变化 |
| 剔除微盘 | 每日按 total_mv 剔除最低 20% | 方向是否保持，retention_ratio |
| 市值中性化 | 每日对因子值回归 log(total_mv)，使用残差 | 中性化后 RankIC 是否 > 0.01 |
| 极端贡献剔除 | 剔除 \|z_factor × z_forward_return\| 最大的 1% | retention_ratio = 压力后 RankIC / 基线 RankIC |

**retention_ratio 阈值：**
- >= 80%：稳健
- 50%-80%：敏感
- < 50%：失败

### 5.8 适用性地图引擎（suitability.py）

**职责：** 计算因子在不同维度组合下的表现。

**维度定义：**
- **市值：** 按 total_mv 分位数分为大盘/中盘/小盘/微盘
- **波动率：** 按 20 日波动率分位数分为低/中/高/极高波动
- **风格：** 有可靠历史 PE/PB 时按综合分位数分为成长/平衡/价值；当前本地 CSV 缺少这些字段，因此该维度必须返回未测试
- **时间：** 按自然年或自定义时间段分段

**计算流程：**
```
1. 对每个维度组合，筛选对应子样本
2. 计算子样本的 RankIC Mean、有效样本数
3. 将 RankIC 映射到颜色（绿/黄/红）和饱和度
4. 样本数不足 60 个交易日标记为"证据不足"
5. 方向翻转的子样本标记红色边框
```

### 5.9 重复检测引擎（duplicate_detect.py）

**职责：** 三层因子重复检测。

**第一层：公式结构相似度**
```
1. 将两个因子的受限公式标准化为 AST
2. 比较 AST 的节点类型和结构
3. 检测单调变换关系（如 log、rank、zscore）
4. 计算结构相似度 = 匹配节点数 / 总节点数
```

**第二层：横截面暴露相关性**
```
1. 对每个交易日，计算两个因子值的 Spearman 秩相关
2. 取所有交易日的均值作为暴露相关度
```

**第三层：因子收益相关性**
```
1. 计算两个因子的分组收益序列
2. 计算收益序列的 Pearson 相关系数
```

**判定规则：**
- 暴露相关 > 0.85 且 收益相关 > 0.80：高度相似
- 暴露相关 > 0.70 且 收益相关 > 0.65：中等相似
- 其他：不相似

### 5.10 证据与结论引擎（evidence_engine.py）

**职责：** 根据所有评估和测试结果，生成结构化证据和总体结论。

**五维度评级：**

| 维度 | 检查内容 | 评级 |
|---|---|---|
| 数据完整性 | 覆盖率、缺失值、时间范围 | 通过/存疑/失败/未测试 |
| 时间正确性 | 未来函数、延迟、观察时点 | 通过/存疑/失败/未测试 |
| 统计支持 | IC 显著性、Bootstrap CI | 通过/存疑/失败/未测试 |
| 压力稳健性 | 四项压力测试结果 | 通过/存疑/失败/未测试 |
| 信息独立性 | 重复检测、市值暴露 | 通过/存疑/失败/未测试 |

**总体结论规则：**

| 结论 | 条件 |
|---|---|
| 无效 | 时间正确性失败 |
| 证据不足 | 数据完整性失败或样本数不足 |
| 脆弱 | 统计支持通过但压力稳健性失败 |
| 条件有效 | 所有维度通过但在特定条件下（如小盘） |
| 当前支持 | 所有维度通过且无显著条件限制 |

### 5.11 哈希工具（hash_utils.py）

**职责：** 生成确定性哈希，确保可复现。

**evidence_hash 计算：**
```python
def compute_evidence_hash(
    factor_spec: FactorSpec,
    data_snapshot_hash: str,
    config: dict,
    evaluation_results: dict,
    stress_results: dict,
    duplicate_results: dict,
    suitability_results: dict,
    engine_version: str
) -> str:
    payload = json.dumps({
        "factor_spec": factor_spec.model_dump(exclude_none=True),
        "data_snapshot_hash": data_snapshot_hash,
        "config": config,
        "evaluation_results": evaluation_results,
        "stress_results": stress_results,
        "duplicate_results": duplicate_results,
        "suitability_results": suitability_results,
        "engine_version": engine_version
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
```

**report_hash 计算：** `evidence_hash` + 确定性正式报告载荷的 SHA256；任何 AI 文本、供应商、模型和降级原因均不参与计算。可选 AI 辅助解读使用独立 `ai_analysis_hash`。

---

## 6. Streamlit 页面设计

### 6.1 应用入口（app.py）

```python
import streamlit as st

st.set_page_config(
    page_title="FactorGuard 因子验真台",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 全局状态初始化
if "market" not in st.session_state:
    st.session_state.market = "CN"  # A股
if "time_range" not in st.session_state:
    st.session_state.time_range = "all"
if "selected_factor" not in st.session_state:
    st.session_state.selected_factor = None
if "audit_run_id" not in st.session_state:
    st.session_state.audit_run_id = None

# 侧边栏：市场选择器
with st.sidebar:
    st.markdown("## FactorGuard")
    st.markdown("*因子验真台*")
    st.divider()

    market = st.selectbox(
        "市场",
        ["A股", "港股 (即将支持)", "美股 (即将支持)", "加密货币 (即将支持)", "外汇 (即将支持)"],
        index=0
    )
    st.caption("比赛快照（2024-09-27 至 2025-09-26）")

    st.divider()
    st.markdown("### 因子库（800 个内置标准因子）")
    # 因子库分类展示
    st.divider()
    st.markdown("### 因子导入")
    st.markdown("- 文本描述")
    st.markdown("- 受限公式")
    st.markdown("- 上传因子值")
    st.caption("安全边界：不执行用户上传的 Python 脚本")
    st.divider()
    st.markdown("*研究质量基础设施*")
    st.markdown("*不输出交易信号*")
```

### 6.2 页面一：首页（app.py）

**核心组件：**
- `st.button("新建鉴证")` → 跳转到因子输入页
- 最近运行列表：优先从 DuckDB `audit_runs` 读取，并在当前会话中保留最近结果缓存
- 四个 Demo 入口卡片（Demo A/B/C/D）
- 数据快照状态显示
- 首页与原工作台已合并，侧栏不再保留重复的独立工作台页面

### 6.3 页面二：因子输入（02_因子输入.py）

**标签页：**

| 标签 | 内容 |
|---|---|
| 内置因子 | 因子卡片网格，按类别筛选，显示名称/类别/方向/结论 |
| 文本描述 | `st.text_area` 输入框，AI 解析按钮 |
| 受限公式 | 公式编辑器，实时语法检查 |
| 因子值上传 | `st.file_uploader` 支持 CSV/Parquet |
| Python脚本 | 灰色占位，显示"即将支持" |

**关键交互：**
- 选择内置因子后，直接在页面上显示预计算的关键指标
- 点击"开始鉴证"触发完整评估流程
- 评估流程显示步骤进度条

### 6.4 页面三：传统评估（03_传统评估.py）

**布局：**
- 顶部：时间维度切换（年/季/月）和原始/中性化图表切换
- 指标表格：IC/ICIR/一致率/换手率/覆盖率
- 图表区：滚动 RankIC 折线图、分组收益柱状图、累计收益曲线
- 诊断口径说明

**图表实现（Plotly）：**
```python
import plotly.graph_objects as go

# 滚动 RankIC 图
fig = go.Figure()
fig.add_trace(go.Scatter(
    x=rolling_dates,
    y=rolling_rank_ic,
    mode='lines+markers',
    name='RankIC',
    line=dict(color='#2267a5', width=2)
))
fig.add_hline(y=0, line_dash='dash', line_color='#b8c2ca')
fig.update_layout(
    template='plotly_white',
    height=400,
    margin=dict(l=40, r=40, t=20, b=40)
)
```

### 6.5 页面四：压力测试（04_压力测试.py）

**布局：**
- 筛选按钮：全部/时间/暴露/样本
- 压力测试表格：测试名称、RankIC、保留比例进度条、状态标签、证据解释
- 压力测试结论摘要

### 6.6 页面五：重复性检测（05_重复性检测.py）

**布局：**
- 因子关系判定 + 状态标签
- 关系流程图：当前因子 ↔ 对比因子
- 三层证据雷达图：公式结构/暴露相关/收益相关
- 证据化解释

### 6.7 页面六：适用性地图（06_适用性地图.py）

**布局：**
- 维度选择器：主维度下拉 × 次维度下拉
- 热力图矩阵：Plotly Heatmap
- 颜色图例：绿/黄/红 + 饱和度 + 证据不足
- 预警标记：方向翻转的单元格红色边框

**图表实现（Plotly）：**
```python
import plotly.express as px

fig = px.imshow(
    matrix_data,
    labels=dict(x=dim2_name, y=dim1_name, color="RankIC"),
    x=dim2_values,
    y=dim1_values,
    color_continuous_scale=[
        [0.0, '#a53c3c'],   # 负 RankIC
        [0.3, '#e7ebee'],   # 接近 0
        [0.5, '#fff3d9'],   # 弱正
        [0.7, '#e5f2eb'],   # 中正
        [1.0, '#176c49']    # 强正
    ],
    text_auto=True
)
```

### 6.8 页面七：大师方法拆解（07_大师方法拆解.py）

**参考来源：** `DataSource/ai-berkshire/` 的四种大师视角（段永平/巴菲特/芒格/李录）和 `quality-screen`（去劣筛选）Skill。

**布局：**

**Tab 1：方法来源**
- 来源标题、原文引用、出处链接
- 对应的 ai-berkshire Skill 名称（如 `quality-screen`）
- 方法适用范围说明

**Tab 2：原则拆解**
- 四大视角卡片：
  - 段永平视角：商业模式与用户价值
  - 巴菲特视角：财务质量与内在价值
  - 芒格视角：行业竞争与护城河
  - 李录视角：风险管理与治理层评估
- 每项原则 → 可证伪假设 → 代理因子 → 评级（A/B/C/U）
- 3 条豁免规则面板（参考 quality-screen 的豁免A/B/C）

**Tab 3：代理因子送检**
- 代理边界表格：原则、代理因子、评级、数据状态、鉴证按钮
- B 级代理：显示"送检"按钮，可完整走评估和鉴证流程
- C/U 级代理：显示"不可鉴证"状态，附局限说明
- 批量送检功能

**Tab 4：方法论局限性**
- 引用 ai-berkshire quality-screen 的局限性声明
- "通过筛选不等于确定好"
- 仍需进一步研究的维度列表

**关键原则（来自 ai-berkshire AGENTS.md）：**
- 所有判断附数据来源，区分事实与观点
- 清晰标注低置信度结论、不完整数据和信源缺口
- 本项目用于学习和研究，不构成投资建议

### 6.9 页面八：报告与凭证（08_报告与凭证.py）

**标签页：**
| 标签 | 内容 |
|---|---|
| 总览 | 总体结论（大号文字）、最严重问题、证据支持/不支持、推荐下一测试 |
| 数据与时间质检 | 闸门清单、数据质量指标 |
| 复现凭证 | JSON 格式凭证（factor_id/version/data_snapshot/hashes） |
| 导出 | HTML/Markdown/JSON 下载按钮 |

---

## 7. 因子数据加载流程

### 7.1 启动时

```
app.py
    ├── data_loader.py
    │   ├── 检查 data/snapshot/daily_ohlcv.parquet 是否存在
    │   ├── 不存在 → 遍历 E:\Quantclass\stock-trading-data-pro\*.csv
    │   │   ├── GBK 编码读取 + 列名标准化
    │   │   ├── 合并为 daily_ohlcv.parquet + daily_basic.parquet + stock_basic.parquet
    │   │   └── 可选：通过 akshare/baostock 补充 ST 状态和退市日期
    │   └── 存在 → 直接加载 Parquet（秒级完成）
    │
    └── factor_loader.py
        ├── 扫描 Factors/*/factor_index.json
        ├── 解析因子元数据 → DuckDB factor_metadata
        ├── 扫描 Factors/*/validation_summary_real.json
        │   ├── 提取 ic_mean_5d, icir_5d, coverage, turnover, status
        │   └── 写入 DuckDB precomputed_results
        └── 返回可用因子列表

内置因子 Demo 数据：
    ├── Demo A: 未来函数因子（通过在 formula 中设置负 delay 模拟）
    ├── Demo B: 重复因子对（选择两个公式结构相似但命名不同的因子）
    ├── Demo C: 小微盘暴露因子（选择 ic_mean_5d 高但市值敏感的因子）
    └── Demo D: 大师方法代理（参考 ai-berkshire quality-screen 的 7 条指标，
                 选取 B 级代理构建可验证因子，其余标记"不可鉴证"）
```

### 7.2 鉴证运行时

```
用户选择因子 → 点击"开始鉴证"
    ├── 步骤 1: 输入检查
    │   ├── 公式解析（公式因子）
    │   ├── 文件校验（上传因子）
    │   └── 质检引擎（P0检查项）
    ├── 步骤 2: 数据对齐
    │   ├── 加载因子值
    │   ├── 加载行情数据
    │   ├── 构建股票池
    │   └── 对齐因子值 × 收益标签
    ├── 步骤 3: 传统评估
    │   ├── IC/RankIC/ICIR/显著性
    │   ├── 分组收益/累计收益
    │   ├── 换手率/衰减/覆盖率
    │   ├── Bootstrap 置信区间
    │   └── 滚动表现
    ├── 步骤 4: 压力测试
    │   ├── 数据延迟
    │   ├── 剔除微盘
    │   ├── 市值中性化
    │   └── 极端贡献剔除
    ├── 步骤 5: 重复检测
    │   ├── 公式结构相似度
    │   ├── 横截面暴露相关
    │   └── 因子收益相关
    ├── 步骤 6: 适用性地图
    │   └── 多维度交叉计算
    ├── 步骤 7: 证据生成
    │   ├── 五维度评级
    │   ├── 总体结论
    │   └── 证据记录
    ├── 步骤 8: 哈希计算
    │   └── evidence_hash + report_hash
    └── 步骤 9: 结果持久化
        └── 写入 DuckDB audit_runs 表
```

---

## 8. MVP 数据流

### 8.1 数据来源优先级

| 层级 | 来源 | 字段 | 策略 |
|---|---|---|---|
| 主数据源 | 本地 CSV `E:\Quantclass\stock-trading-data-pro` | OHLCV、市值、换手率、利润/现金流、资产负债、行业分类 | 通过显式 CLI 流式转换为 Parquet；页面不自动建库 |
| 补充数据源 | akshare / baostock | ST 状态、退市日期、复权因子 | 按需调用，缓存到本地，接口不可用时降级处理 |
| 预计算指标 | Factors/*/validation_summary_real.json | IC、ICIR、覆盖率、换手率 | 直接读取 JSON，写入 DuckDB 缓存 |

### 8.2 内置因子展示（无需计算）

MVP 利用现有 validation_summary_real.json 中的预计算指标，直接展示：
- IC Mean (5日预测)：`ic_mean_5d`
- ICIR (5日)：`icir_5d`
- 覆盖率：`coverage`
- 换手率：`turnover_top_quintile`
- 样本量：`sample_rows`
- 状态：`status`

这些指标来自真实数据，可直接用于 Demo 展示。

### 8.3 Demo 数据构造

| Demo | 因子选择 | 数据构造方式 |
|---|---|---|
| Demo A | 选择一个 status="pass" 的因子 | 在 formula 中写入 delay=-1，触发时间正确性失败 |
| Demo B | 选择 R001 和 R034（5日动量 vs 5日delta动量） | 两者公式结构相似但命名不同，触发重复检测 |
| Demo C | 选择 R072 | 展示剔除微盘和市值中性化测试；无实时数据时明确标为演示/未测试 |
| Demo D | 参考 ai-berkshire quality-screen 的 7 条去劣指标 | 资本效率代理可进入实时鉴证；缺少公告时点会被证据引擎限制为 `insufficient`，其余代理保持不可鉴证 |

### 8.4 预计算指标 vs 实时计算

- **内置因子：** 有正式行情快照时按 base/transform 契约实时计算；无快照时只展示历史预计算摘要
- **文本描述/公式因子：** 基于本地数据执行完整的实时计算流程
- **上传因子值：** 执行质检 + 传统评估 + 压力测试
- **Demo 因子：** 混合使用预计算数据 + 手动构造的异常数据

### 8.5 三方数据源降级策略

当 akshare / baostock 不可用时的降级处理：

| 缺失字段 | 降级方案 | 影响 |
|---|---|---|
| ST 状态 | 不做 ST 剔除，仅根据成交量=0 过滤停牌 | 股票池包含少量 ST 股票，对评估影响有限 |
| 退市日期 | 不做退市过滤，使用数据最后出现日期 | 可能包含已退市股票的历史数据，不影响回测 |
| 复权因子 | 使用原始价格，不做复权调整 | 对短期因子（5-20日）影响较小，对长期因子有偏差 |

降级后系统仍可完整运行，仅在数据完整性维度标记为"存疑"。

---

## 9. 环境配置

### 9.1 requirements.txt

```
streamlit>=1.28.0
plotly>=5.18.0
pandas>=2.1.0
numpy>=1.26.0
scipy>=1.11.0
lark>=1.1.0
pydantic>=2.5.0
pyarrow>=14.0.0
openpyxl>=3.1.0
duckdb>=1.0.0
```

### 9.2 setup.bat（Windows 一键初始化）

```batch
@echo off
echo ========================================
echo FactorGuard MVP 环境初始化
echo ========================================

REM 创建虚拟环境
python -m venv venv

REM 激活虚拟环境
call venv\Scripts\activate.bat

REM 升级 pip
python -m pip install --upgrade pip

REM 安装依赖
pip install -r requirements.txt

echo.
echo ========================================
echo 环境初始化完成！
echo 运行命令: venv\Scripts\activate.bat
echo 启动应用: streamlit run app.py
echo ========================================
pause
```

### 9.3 启动命令

```bash
# 激活虚拟环境
venv\Scripts\activate.bat

# 启动 Streamlit
streamlit run app.py

# 或指定端口
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

---

## 10. 关键设计决策

### 10.1 为什么用 DuckDB 而不是纯文件？

- 因子元数据查询需要分类筛选、排序、模糊搜索，SQL 比文件扫描更高效
- 鉴证运行记录需要持久化历史，支持"最近运行"列表
- 预计算指标缓存表使内置因子展示从 O(N) 文件读取降为 O(1) 单表查询

### 10.2 为什么 MVP 不实时计算所有因子？

- 实时计算需要完整的历史行情数据，本地数据虽已包含，但首次合并 Parquet 快照有耗时
- MVP 优先展示产品完整流程，预计算指标来自真实数据，具备足够的演示真实性
- 内置因子直接使用预计算指标，秒级响应，用户体验流畅

### 10.3 为什么 Demo 数据混合真实和构造？

- Demo A/B/C/D 需要展示异常场景，真实数据中不一定存在
- 混合方式可以保证 Demo 稳定复现，同时主力因子展示真实数据

### 10.4 受限公式解析器为什么用 Lark 而不是 eval？

- PRD 明确要求"不允许调用 Python eval"
- Lark 生成 AST 后可以静态分析，检测潜在风险
- AST 可以用于公式标准化和结构相似度计算

### 10.5 为什么主数据源用本地 CSV 而不是 TuShare？

- 本地数据集已覆盖 A 股全量日线行情（沪深京三地），包含 OHLCV、市值、换手率、利润/现金流、资产负债和行业分类；不含 PE/PB
- 零网络依赖，无 API 调用频率限制，适合离线 Demo 演示
- 显式构建 Parquet 快照后，后续加载秒级完成；页面启动不会隐式扫描 CSV
- 缺失字段（ST 状态、退市日期、复权因子）通过免费三方数据源按需补充，且均有降级方案

---

## 11. 测试计划

### 11.1 单元测试

| 模块 | 测试内容 | 工具 |
|---|---|---|
| formula_parser | 正例/反例公式解析 | pytest |
| traditional_eval | 黄金测试（小数据已知结果） | pytest |
| stress_test | 边界条件（空数据、全NaN） | pytest |
| duplicate_detect | 三层检测阈值验证 | pytest |
| hash_utils | 确定性验证（相同输入相同hash） | pytest |

### 11.2 集成测试

- 端到端流程：内置因子选择 → 评估 → 鉴证 → 报告
- 四个 Demo 的稳定复现
- 离线模式：断网下所有页面正常展示

### 11.3 验收测试

- 手工复核：选取样本日期，手工计算 IC/RankIC，与系统输出对比
- 黄金测试：使用小型人工数据验证所有指标
- 确定性重跑：同一配置两次运行，evidence_hash 一致

---

## 12. 风险与应对

| 风险 | 概率 | 影响 | 应对 |
|---|---|---|---|
| 本地数据路径不存在或权限不足 | 低 | 高 | 启动时检查路径，提示用户确认；支持通过 config.py 配置自定义路径 |
| 本地 CSV 文件编码异常 | 低 | 中 | 使用 `errors="ignore"` 容错读取，记录异常文件列表 |
| 首次启动快照生成耗时较长 | 中 | 低 | 显示进度条，生成后缓存复用 |
| akshare/baostock 接口不可用 | 中 | 低 | 完整降级策略（见 8.5），系统仍可核心运行 |
| 因子计算性能不足 | 低 | 中 | 预计算 + 缓存策略，MVP 不实时计算 |
| Streamlit 页面性能 | 低 | 中 | 使用 st.cache_data 缓存计算结果 |
| AI 接口不可用 | 中 | 低 | 模板降级方案，确定性文本替代 |
| 团队仅 1 名技术 | 高 | 高 | 简化 Demo 数据构造，优先完成核心流程 |

---

## 9. AI 辅助解读隔离契约

`engine/ai_analysis.py` 是非权威 sidecar。它只接收结构化证据摘要，不接收原始 DataFrame、本地路径或 API Key；Pydantic 模型拒绝未知字段。模型输出必须保持正式结论不变，只能引用输入中存在的 `evidence_id`，且文本中的数字必须来自证据内容。

模型不可用、超时、网络错误、非 JSON、结构错误、结论冲突、引用错误或数字校验失败时，统一生成确定性的 `rule_fallback`。成功结果标记 `model`。`ai_analysis_hash` 独立覆盖证据哈希、供应商、模型、提示词版本和经校验的 AI 载荷；正式 `report_hash` 永不覆盖 AI 文本。

模型适配采用 OpenAI-compatible Chat Completions。内置 `openai`、`deepseek`、`dashscope`、`zhipu`、`moonshot`、`siliconflow` 和 `custom` 七种供应商配置。非敏感字段按“页面显式值 > `FACTORGUARD_LLM_*` 环境覆盖 > 供应商预设”解析；未声明供应商的旧版 Base URL/模型配置按 `custom` 保持兼容。页面可选择供应商、编辑模型 ID，并仅在自定义模式下填写 Base URL。

`FACTORGUARD_LLM_API_KEY` 是唯一密钥来源。报告页只调用布尔状态函数，不读取或保存密钥；配置对象的调试表示、请求正文、AI 返回结果、session state、日志与哈希均不包含密钥。缺少密钥、不支持的供应商、非法 URL 或不完整自定义配置直接规则降级。

报告页把 AI 结果保留在 Streamlit session state，不写入 `audit_runs` 正式字段；HTML、Markdown、JSON 三种下载只包含确定性审计结果，按钮数量固定为 3。

正式报告由确定性审计引擎生成；大模型只提供可引用、可校验、可降级的投研辅助解读，不参与正式裁决。

---

> **文档版本：** 1.1 | **更新日期：** 2026-08-21 | **对应 PRD：** FactorGuard_PRD_V1.1
