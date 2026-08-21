"""
IO 工具

提供安全读取 CSV、Parquet 读写、目录创建等常用文件操作工具。
所有函数基于 pandas 实现，不依赖外部 API。
"""

import os
import pandas as pd
try:
    from config import DATA_LOCAL, DATA_SNAPSHOT, FACTOR_CACHE
except ImportError:
    from ..config import DATA_LOCAL, DATA_SNAPSHOT, FACTOR_CACHE


def read_csv_safe(filepath, **kwargs):
    """
    安全读取 CSV 文件，自动尝试 utf-8 和 gbk 编码。

    首先尝试 utf-8 编码读取，如果失败则尝试 gbk 编码。

    Parameters
    ----------
    filepath : str or Path
        CSV 文件路径
    **kwargs
        传递给 pd.read_csv 的其他参数

    Returns
    -------
    pd.DataFrame
        读取的数据框

    Raises
    ------
    ValueError
        如果所有编码尝试均失败
    """
    encodings = ['utf-8', 'gbk', 'gb2312', 'utf-8-sig']

    for enc in encodings:
        try:
            return pd.read_csv(filepath, encoding=enc, **kwargs)
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception as e:
            # 非编码错误，直接抛出
            raise

    raise ValueError(
        f"无法读取文件 {filepath}，所有编码尝试均失败: {encodings}"
    )


def save_parquet(df, filepath):
    """
    保存 DataFrame 为 Parquet 文件。

    自动确保目标目录存在。

    Parameters
    ----------
    df : pd.DataFrame
        要保存的数据框
    filepath : str or Path
        目标文件路径
    """
    ensure_dir(os.path.dirname(str(filepath)))
    df.to_parquet(filepath, index=False)


def load_parquet(filepath):
    """
    加载 Parquet 文件。

    Parameters
    ----------
    filepath : str or Path
        Parquet 文件路径

    Returns
    -------
    pd.DataFrame
        读取的数据框
    """
    return pd.read_parquet(filepath)


def ensure_dir(path):
    """
    确保目录存在，不存在则递归创建。

    Parameters
    ----------
    path : str or Path
        目录路径
    """
    os.makedirs(str(path), exist_ok=True)