"""
表格样式工具
"""
import pandas as pd
import streamlit as st
from config import COLOR_PASS, COLOR_WARN, COLOR_FAIL, COLOR_NEUTRAL, COLOR_UNTESTED


def style_dataframe(df, highlight_cols=None):
    """返回带样式的 DataFrame column_config"""
    config = {}
    if highlight_cols is None:
        highlight_cols = []

    for col in df.columns:
        if pd.api.types.is_float_dtype(df[col]):
            config[col] = st.column_config.NumberColumn(
                col,
                format="%.4f",
                help=f"{col} (数值)"
            )
        elif pd.api.types.is_integer_dtype(df[col]):
            config[col] = st.column_config.NumberColumn(
                col,
                format="%d",
                help=f"{col} (整数)"
            )
        else:
            config[col] = st.column_config.TextColumn(
                col,
                help=f"{col}"
            )

    return st.dataframe(df, column_config=config, width='stretch')


def style_metric_table(df):
    """为指标表格添加条件格式"""
    column_config = {}

    for col in df.columns:
        if pd.api.types.is_float_dtype(df[col]):
            column_config[col] = st.column_config.NumberColumn(
                col,
                format="%.4f"
            )
        elif pd.api.types.is_integer_dtype(df[col]):
            column_config[col] = st.column_config.NumberColumn(
                col,
                format="%d"
            )
        elif "IC" in col.upper() or "t值" in col or "t_stat" in col.lower():
            column_config[col] = st.column_config.NumberColumn(
                col,
                format="%.4f"
            )
        elif "p值" in col or "p_value" in col.lower() or "pval" in col.lower():
            column_config[col] = st.column_config.NumberColumn(
                col,
                format="%.4f"
            )
        elif "收益" in col or "return" in col.lower():
            column_config[col] = st.column_config.NumberColumn(
                col,
                format="%.4f%%"
            )
        elif "比例" in col or "ratio" in col.lower():
            column_config[col] = st.column_config.ProgressColumn(
                col,
                format="%.2f",
                min_value=0.0,
                max_value=1.0
            )
        else:
            column_config[col] = st.column_config.TextColumn(col)

    return st.dataframe(df, column_config=column_config, width='stretch')