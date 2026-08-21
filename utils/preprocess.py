"""
数据预处理工具

提供因子值清洗、标准化、中性化、缩尾处理等常用预处理函数。
所有函数基于 pandas / numpy / sklearn 实现，不依赖外部 API。
"""

import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression


def winsorize(series, limits=(0.01, 0.99)):
    """
    极值缩尾处理（Winsorize）。

    将超出指定分位数范围的值替换为边界值。

    Parameters
    ----------
    series : pd.Series or np.ndarray
        输入数据
    limits : tuple of float, default (0.01, 0.99)
        下界和上界分位数，如 (0.01, 0.99) 表示 1% 和 99% 分位数

    Returns
    -------
    pd.Series
        缩尾后的数据
    """
    if isinstance(series, np.ndarray):
        series = pd.Series(series)
    lower = series.quantile(limits[0])
    upper = series.quantile(limits[1])
    return series.clip(lower=lower, upper=upper)


def zscore(series):
    """
    Z-score 标准化。

    将数据转换为均值为 0、标准差为 1 的分布。

    Parameters
    ----------
    series : pd.Series or np.ndarray
        输入数据

    Returns
    -------
    pd.Series
        标准化后的数据
    """
    if isinstance(series, np.ndarray):
        series = pd.Series(series)
    mean = series.mean()
    std = series.std(ddof=0)
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=series.index)
    return (series - mean) / std


def mad3_zscore(series):
    """
    MAD（中位数绝对偏差）离群值处理。

    将超过 3 倍 MAD 中位数偏差的值缩尾到 3 倍边界。

    步骤:
    1. 计算中位数 median
    2. 计算 MAD = median(|x - median|)
    3. 将超出 [median - 3*MAD, median + 3*MAD] 的值缩尾到边界

    Parameters
    ----------
    series : pd.Series or np.ndarray
        输入数据

    Returns
    -------
    pd.Series
        处理后的数据
    """
    if isinstance(series, np.ndarray):
        series = pd.Series(series)
    median = series.median()
    mad = (series - median).abs().median()
    if mad == 0 or np.isnan(mad):
        return series
    lower = median - 3 * mad
    upper = median + 3 * mad
    return series.clip(lower=lower, upper=upper)


def neutralize(factor_values, market_cap, industry=None):
    """
    市值中性化（对 log(总市值) 回归取残差），可选行业中性化。

    使用线性回归将因子值对 log(市值)（和行业哑变量）回归，取残差作为中性化后的因子值。

    Parameters
    ----------
    factor_values : pd.Series or np.ndarray
        原始因子值
    market_cap : pd.Series or np.ndarray
        总市值序列（会被取 log）
    industry : pd.Series or np.ndarray, optional
        行业分类标签，如果提供则作为哑变量加入回归

    Returns
    -------
    pd.Series
        中性化后的因子值（残差）
    """
    if isinstance(factor_values, np.ndarray):
        factor_values = pd.Series(factor_values)
    if isinstance(market_cap, np.ndarray):
        market_cap = pd.Series(market_cap, index=factor_values.index)

    y = factor_values.values.reshape(-1, 1).astype(float)

    # 构建特征矩阵: log(市值)
    log_cap = np.log(market_cap.replace(0, np.nan)).values.reshape(-1, 1).astype(float)
    X = log_cap.copy()

    if industry is not None:
        if isinstance(industry, np.ndarray):
            industry = pd.Series(industry, index=factor_values.index)
        # 行业哑变量
        industry_dummies = pd.get_dummies(industry, drop_first=True).astype(float)
        industry_dummies = industry_dummies.reindex(factor_values.index)
        X = np.hstack([X, industry_dummies.values])

    # 移除包含 NaN 的行
    valid_mask = ~np.isnan(X).any(axis=1) & ~np.isnan(y).ravel()
    if valid_mask.sum() < 2:
        return factor_values

    X_valid = X[valid_mask]
    y_valid = y[valid_mask]

    model = LinearRegression()
    model.fit(X_valid, y_valid)
    y_pred = model.predict(X_valid)

    residuals = y_valid.ravel() - y_pred.ravel()

    result = pd.Series(np.nan, index=factor_values.index)
    result.iloc[valid_mask] = residuals
    return result


def standardize_cross_section(df, factor_col, date_col='trade_date'):
    """
    按日期分组进行横截面 Z-score 标准化。

    对每个交易日内的因子值分别执行 Z-score 标准化。

    Parameters
    ----------
    df : pd.DataFrame
        包含因子值和日期的数据框
    factor_col : str
        需要标准化的因子列名
    date_col : str, default 'trade_date'
        日期列名

    Returns
    -------
    pd.Series
        标准化后的因子值序列（与输入 df 等长）
    """
    result = df.groupby(date_col)[factor_col].transform(
        lambda x: (x - x.mean()) / x.std(ddof=0) if x.std(ddof=0) > 0 else 0.0
    )
    return result