"""
FactorGuard 全局配置
"""
import os
from pathlib import Path

# 项目根目录
ROOT_DIR = Path(__file__).parent.resolve()


def _configured_path(env_name: str, default: str | Path) -> Path:
    """Return an optional environment override without changing local defaults."""
    value = os.getenv(env_name, "").strip()
    return Path(value).expanduser() if value else Path(default)


# 数据路径
DATA_LOCAL = _configured_path(
    "FACTORGUARD_DATA_LOCAL", "E:/Quantclass/stock-trading-data-pro"
)
DATA_SNAPSHOT = _configured_path(
    "FACTORGUARD_SNAPSHOT_DIR", ROOT_DIR / "data" / "snapshot"
)
FACTOR_CACHE = ROOT_DIR / "data" / "factor_cache"
DB_PATH = ROOT_DIR / "data" / "factor_master.duckdb"

# 因子库路径
FACTORS_DIR = ROOT_DIR / "Factors"

# 数据源路径
DATASOURCE_DIR = ROOT_DIR / "DataSource"

# Parquet 快照文件路径
OHLCV_PARQUET = DATA_SNAPSHOT / "daily_ohlcv.parquet"
BASIC_PARQUET = DATA_SNAPSHOT / "daily_basic.parquet"
STOCK_BASIC_PARQUET = DATA_SNAPSHOT / "stock_basic.parquet"
SNAPSHOT_MANIFEST = DATA_SNAPSHOT / "manifest.json"

# 默认参数
DEFAULT_FORWARD_PERIOD = 5  # 默认预测周期（交易日）
DEFAULT_BOOTSTRAP_BLOCKS = 20  # Bootstrap 块长
DEFAULT_BOOTSTRAP_REPS = 200  # Bootstrap 重复次数
DEFAULT_BOOTSTRAP_SEED = 20260815
ENGINE_VERSION = "1.1.0"

# 颜色映射
COLOR_PASS = "#176c49"
COLOR_WARN = "#d49b2e"
COLOR_FAIL = "#a53c3c"
COLOR_NEUTRAL = "#2267a5"
COLOR_UNTESTED = "#b8c2ca"

# 图表模板
PLOTLY_TEMPLATE = "plotly_white"
CHART_HEIGHT = 400

# 市场列表
MARKETS = ["A股", "港股 (即将支持)", "美股 (即将支持)", "加密货币 (即将支持)", "外汇 (即将支持)"]
MARKET_ACTIVE = "A股"
