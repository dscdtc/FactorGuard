"""
DuckDB 查询引擎模块
- 提供统一的 DuckDB 查询接口
- 支持 Parquet 文件直接查询（无需加载到 pandas）
- 支持内存数据库操作
"""
import duckdb
import pandas as pd
from pathlib import Path
from typing import Optional

from config import (
    DB_PATH,
    OHLCV_PARQUET,
    BASIC_PARQUET,
    STOCK_BASIC_PARQUET,
)


class DuckDBQuery:
    """DuckDB 查询封装类

    Usage:
        dq = DuckDBQuery()
        # 直接查询 Parquet 文件
        df = dq.query_parquet("SELECT * FROM ohlcv WHERE trade_date = '2024-01-02'")
        # 执行 SQL
        df = dq.query("SELECT factor_id, name_cn FROM factor_metadata")
    """

    def __init__(self, db_path: Optional[str] = None):
        """初始化 DuckDB 连接

        Parameters
        ----------
        db_path : str, optional
            数据库文件路径，为 None 时使用内存数据库
        """
        if db_path:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = duckdb.connect(db_path)
        else:
            self._conn = duckdb.connect(":memory:")

    def attach_parquet(self, name: str, path: str) -> None:
        """将 Parquet 文件注册为 DuckDB 视图

        Parameters
        ----------
        name : str
            视图名称
        path : str
            Parquet 文件路径
        """
        self._conn.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM '{path}'")

    def attach_default_snapshots(self) -> None:
        """注册默认的快照 Parquet 文件"""
        if OHLCV_PARQUET.exists():
            self.attach_parquet("ohlcv", str(OHLCV_PARQUET))
        if BASIC_PARQUET.exists():
            self.attach_parquet("daily_basic", str(BASIC_PARQUET))
        if STOCK_BASIC_PARQUET.exists():
            self.attach_parquet("stock_basic", str(STOCK_BASIC_PARQUET))

    def query_parquet(self, sql: str, path: Optional[str] = None) -> pd.DataFrame:
        """直接查询 Parquet 文件

        Parameters
        ----------
        sql : str
            SQL 查询语句，表名使用 'data' 或已注册的视图名
        path : str, optional
            Parquet 文件路径，为 None 时使用已注册的视图

        Returns
        -------
        pd.DataFrame
        """
        if path:
            return self._conn.execute(
                sql.replace("FROM data", f"FROM '{path}'")
            ).df()
        return self._conn.execute(sql).df()

    def query(self, sql: str, params: Optional[list] = None) -> pd.DataFrame:
        """执行任意 SQL 查询

        Parameters
        ----------
        sql : str
            SQL 查询语句
        params : list, optional
            参数化查询参数

        Returns
        -------
        pd.DataFrame
        """
        if params:
            return self._conn.execute(sql, params).df()
        return self._conn.execute(sql).df()

    def execute(self, sql: str, params: Optional[list] = None) -> None:
        """执行非查询 SQL（INSERT/UPDATE/DELETE/CREATE）

        Parameters
        ----------
        sql : str
            SQL 语句
        params : list, optional
            参数化查询参数
        """
        if params:
            self._conn.execute(sql, params)
        else:
            self._conn.execute(sql)

    def get_conn(self) -> duckdb.DuckDBPyConnection:
        """获取原始 DuckDB 连接"""
        return self._conn

    def close(self) -> None:
        """关闭连接"""
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False