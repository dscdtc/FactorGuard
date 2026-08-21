"""
传统评估页面 - Tear Sheet
展示因子的传统量化评估指标，包括 IC、RankIC、分组收益、换手率等
"""
import streamlit as st
import pandas as pd
import numpy as np
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from engine.traditional_eval import (
    evaluate_factor, evaluate_by_time_dimension,
    compute_factor_distribution, compute_ic_decay,
    compute_factor_autocorr, compute_neutralized_compare,
    compute_daily_rank_ic,
)
from engine.bootstrap import bootstrap_rank_ic
from engine.factor_computer import load_aligned_data
from engine.factor_loader import get_precomputed_metrics
from engine.data_loader import get_ohlcv_data, get_basic_data
from engine.run_recorder import save_run
from ui.chart_utils import (
    create_rolling_ic_chart, create_group_return_chart,
    create_distribution_chart, create_coverage_chart,
    create_decay_chart, create_cumulative_return_chart,
    create_autocorr_chart,
)
from ui.metric_cards import render_metric_row, render_verdict_badge
from ui.color_utils import COLOR_SCHEME
from config import DEFAULT_BOOTSTRAP_BLOCKS, DEFAULT_BOOTSTRAP_REPS, DEFAULT_BOOTSTRAP_SEED

st.set_page_config(page_title="传统评估", page_icon="\U0001f4ca", layout="wide")

# ============================================================
# 辅助函数
# ============================================================
def evaluate_by_time_dimension_custom(df: pd.DataFrame, period_col: str) -> pd.DataFrame:
    """按自定义分段聚合指标"""
    from engine.traditional_eval import evaluate_factor
    rows = []
    for period, group in df.groupby(period_col):
        result = evaluate_factor(group, factor_col='factor_value', return_col='forward_return')
        rows.append({
            'period': period,
            'ic_mean': result['ic_mean'],
            'rank_ic_mean': result['rank_ic_mean'],
            'icir': result['icir'],
            'direction_consistency': result['direction_consistency'],
            'coverage': result['coverage'],
            'sample_count': result['sample_count'],
        })
    return pd.DataFrame(rows)

# ============================================================
# 前提条件检查
# ============================================================
if "selected_factor_id" not in st.session_state or st.session_state.selected_factor_id is None:
    st.warning("\u26a0\ufe0f 请先在因子输入页面选择一个因子")
    st.stop()

factor_id = st.session_state.selected_factor_id
factor_name = st.session_state.get("selected_factor_name", factor_id)
factor_spec = st.session_state.get("selected_factor_spec", None)

# ============================================================
# 页面标题
# ============================================================
st.title(f"{factor_name} \u2014 传统评估 Tear Sheet")

# ============================================================
# 预计算参考指标（来自 validation_summary_real.json）
# ============================================================
precomputed = {}
try:
    precomputed = get_precomputed_metrics(factor_id)
except Exception:
    pass

if precomputed:
    with st.expander("📊 预计算参考指标", expanded=False):
        ref_cols = st.columns(4)
        with ref_cols[0]:
            ic_m = precomputed.get("ic_mean_5d")
            st.metric("IC Mean (5D)", f"{ic_m:.4f}" if isinstance(ic_m, (int, float)) else "N/A")
        with ref_cols[1]:
            icir = precomputed.get("icir_5d")
            st.metric("ICIR", f"{icir:.4f}" if isinstance(icir, (int, float)) else "N/A")
        with ref_cols[2]:
            cov = precomputed.get("coverage")
            st.metric("覆盖率", f"{cov:.1%}" if isinstance(cov, (int, float)) else "N/A")
        with ref_cols[3]:
            to = precomputed.get("turnover")
            st.metric("换手率 (Top)", f"{to:.1%}" if isinstance(to, (int, float)) else "N/A")

        ref_cols2 = st.columns(4)
        with ref_cols2[0]:
            ls = precomputed.get("long_short_mean_5d")
            st.metric("Long-Short Mean", f"{ls:.4f}" if isinstance(ls, (int, float)) else "N/A")
        with ref_cols2[1]:
            sr = precomputed.get("sample_rows")
            st.metric("样本行数", f"{sr:,}" if isinstance(sr, (int, float)) else "N/A")
        with ref_cols2[2]:
            ur = precomputed.get("usable_rows")
            st.metric("有效行数", f"{ur:,}" if isinstance(ur, (int, float)) else "N/A")
        with ref_cols2[3]:
            status_val = precomputed.get("status", "N/A")
            st.metric("验证状态", str(status_val))

        st.caption("*以上指标来自 factor validation 预计算，仅供参考。下方为基于当前数据快照的实时计算。*")

# ============================================================
# 顶部控件
# ============================================================
col_ctrl1, col_ctrl2, col_ctrl3 = st.columns([1, 1, 1])

with col_ctrl1:
    time_dim = st.selectbox(
        "时间维度",
        options=["年", "季", "月", "自定义"],
        index=0,
        key="trad_time_dim"
    )

with col_ctrl2:
    time_range = st.selectbox(
        "时间范围",
        options=["全量", "近3年", "近5年", "自定义起止日期", "样本外预留"],
        index=0,
        key="trad_time_range"
    )

# 自定义时间维度设置
custom_dim_periods = None
if time_dim == "自定义":
    with col_ctrl3:
        custom_dim_input = st.text_input(
            "自定义分段（逗号分隔年份，如 2020,2021,2022-2024）",
            placeholder="2020-2022, 2023-2025",
            key="trad_custom_dim",
        )
        if custom_dim_input.strip():
            # 解析自定义分段
            custom_dim_periods = []
            for part in custom_dim_input.split(","):
                part = part.strip()
                if "-" in part:
                    parts = part.split("-")
                    if len(parts) == 2:
                        try:
                            start, end = int(parts[0]), int(parts[1])
                            custom_dim_periods.extend(range(start, end + 1))
                        except ValueError:
                            pass
                else:
                    try:
                        custom_dim_periods.append(int(part))
                    except ValueError:
                        pass
            st.caption(f"已设置 {len(custom_dim_periods)} 个分段: {custom_dim_periods[:5]}{'...' if len(custom_dim_periods) > 5 else ''}")
    if not custom_dim_input.strip():
        with col_ctrl3:
            st.info("请输入自定义分段，如 2020,2021,2022-2024")

# 自定义时间范围设置
custom_start = None
custom_end = None
oos_ratio = None
if time_range == "自定义起止日期":
    with col_ctrl3:
        c1, c2 = st.columns(2)
        with c1:
            custom_start = st.date_input("开始日期", value=None, key="trad_custom_start")
        with c2:
            custom_end = st.date_input("结束日期", value=None, key="trad_custom_end")
elif time_range == "样本外预留":
    with col_ctrl3:
        oos_ratio = st.slider(
            "样本外预留比例",
            min_value=0.05,
            max_value=0.50,
            value=0.20,
            step=0.05,
            format="%.0f%%",
            key="trad_oos_ratio",
            help="将最近 N% 的数据作为样本外测试集，仅用历史数据计算指标"
        )

if time_dim == "自定义" and not custom_dim_input.strip():
    with col_ctrl3:
        pass  # 已显示 info 提示

if time_range not in ("自定义起止日期", "样本外预留") and time_dim != "自定义":
    with col_ctrl3:
        st.caption("")  # 占位

# ============================================================
# 数据获取与评估计算（优化版：预计算 + 并行 + 渐进式UI）
# ============================================================
forward_period = st.session_state.get("forward_period", 5)
t_start = time.time()

# 尝试加载对齐数据（自动从 OHLCV 快照计算）
with st.spinner("正在加载和计算因子数据..."):
    aligned_data = load_aligned_data(st.session_state, forward_period)

if aligned_data is None or aligned_data.empty:
    st.warning("\u26a0\ufe0f 未找到对齐后的因子数据，请先在因子输入页面选择因子")
    st.stop()

# 时间范围过滤
df = aligned_data.copy()
df['trade_date'] = pd.to_datetime(df['trade_date'])

if time_range == "近3年":
    max_date = df['trade_date'].max()
    cutoff = max_date - pd.DateOffset(years=3)
    df = df[df['trade_date'] >= cutoff]
elif time_range == "近5年":
    max_date = df['trade_date'].max()
    cutoff = max_date - pd.DateOffset(years=5)
    df = df[df['trade_date'] >= cutoff]
elif time_range == "自定义起止日期":
    if custom_start is not None:
        df = df[df['trade_date'] >= pd.to_datetime(custom_start)]
    if custom_end is not None:
        df = df[df['trade_date'] <= pd.to_datetime(custom_end)]
elif time_range == "样本外预留":
    if oos_ratio is not None and oos_ratio > 0:
        dates_sorted = sorted(df['trade_date'].unique())
        split_idx = int(len(dates_sorted) * (1 - oos_ratio))
        if split_idx > 0 and split_idx < len(dates_sorted):
            cutoff_date = dates_sorted[split_idx]
            df = df[df['trade_date'] <= cutoff_date]
            st.info(f"样本外预留 {oos_ratio:.0%}：仅使用 {dates_sorted[0].strftime('%Y-%m-%d')} ~ {cutoff_date.strftime('%Y-%m-%d')} 的数据，最近 {len(dates_sorted) - split_idx} 个交易日作为样本外")

if df.empty:
    st.warning("\u26a0\ufe0f 所选时间范围内无有效数据")
    st.stop()

# ============================================================
# 缓存检查：避免重复计算
# ============================================================
cache_key = f"eval_{factor_id}_{time_range}"
cached = st.session_state.get(cache_key)

if cached is not None:
    st.info("📦 使用缓存数据（无需重新计算）")
    eval_result = cached["eval_result"]
    boot_result = cached["boot_result"]
    daily_ric = cached["daily_ric"]
    dist_result = cached["dist_result"]
    decay_result = cached["decay_result"]
    autocorr_result = cached["autocorr_result"]
    neut_result = cached["neut_result"]
    time_dim_df = cached["time_dim_df"]
    ohlcv_data = st.session_state.get("ohlcv_df")
else:
    # ============================================================
    # 阶段 1：预计算每日 RankIC（一次计算，多处复用）
    # ============================================================
    with st.status("正在计算评估指标...", expanded=True) as status:
        st.write("⏳ 预计算每日 RankIC...")
        daily_ric = compute_daily_rank_ic(df, factor_col='factor_value', return_col='forward_return')

        # 核心指标计算
        st.write("⏳ 计算核心指标与 Bootstrap...")
        eval_result = evaluate_factor(df, factor_col='factor_value', return_col='forward_return',
                                       daily_rank_ic=daily_ric)
        boot_result = bootstrap_rank_ic(
            df,
            block_size=DEFAULT_BOOTSTRAP_BLOCKS,
            n_reps=DEFAULT_BOOTSTRAP_REPS,
            seed=DEFAULT_BOOTSTRAP_SEED,
            daily_rank_ic=daily_ric
        )

        # 加载 OHLCV 数据（优先使用缓存）
        ohlcv_data = st.session_state.get("ohlcv_df")
        if ohlcv_data is None:
            ohlcv_data = get_ohlcv_data()
            st.session_state["ohlcv_df"] = ohlcv_data

        # 阶段 2：并行计算其余指标
        st.write("⏳ 并行计算图表数据...")
        progress_bar = st.progress(0, text="准备中...")

        dim_map = {"年": "year", "季": "quarter", "月": "month"}
        time_dim_key = dim_map.get(time_dim, "year")

        # 定义并行任务
        def _compute_dist():
            return ("dist", compute_factor_distribution(df))

        def _compute_decay():
            return ("decay", compute_ic_decay(df, ohlcv_df=ohlcv_data))

        def _compute_autocorr():
            return ("autocorr", compute_factor_autocorr(df))

        def _compute_neut():
            if ohlcv_data is not None and not ohlcv_data.empty:
                return ("neut", compute_neutralized_compare(df, ohlcv_data))
            return ("neut", None)

        def _compute_time_dim():
            if time_dim == "自定义" and custom_dim_periods:
                df_custom = df.copy()
                df_custom['_trade_year'] = df_custom['trade_date'].dt.year
                df_custom['_custom_period'] = None
                for i, period in enumerate(custom_dim_periods):
                    df_custom.loc[df_custom['_trade_year'] == period, '_custom_period'] = f"P{period}"
                df_custom = df_custom[df_custom['_custom_period'].notna()]
                if df_custom.empty:
                    return ("time_dim", pd.DataFrame())
                return ("time_dim", evaluate_by_time_dimension_custom(df_custom, '_custom_period'))
            return ("time_dim", evaluate_by_time_dimension(df, dim=time_dim_key, daily_rank_ic=daily_ric))

        tasks = [_compute_dist, _compute_decay, _compute_autocorr, _compute_neut, _compute_time_dim]
        results = {}
        n_tasks = len(tasks)

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(task): task.__name__ for task in tasks}
            completed = 0
            for future in as_completed(futures):
                key, value = future.result()
                results[key] = value
                completed += 1
                progress_bar.progress(completed / n_tasks, text=f"已完成 {completed}/{n_tasks} 项...")

        # 提取结果
        dist_result = results.get("dist", {"factor_values": [], "coverage_dates": [], "coverage_values": []})
        decay_result = results.get("decay", {"periods": [], "rank_ic_values": []})
        autocorr_result = results.get("autocorr", {"lags": [], "autocorr_values": []})
        neut_result = results.get("neut", None)
        time_dim_df = results.get("time_dim", pd.DataFrame())

        progress_bar.empty()
        elapsed = time.time() - t_start
        status.update(label=f"计算完成（耗时 {elapsed:.1f}s）", state="complete", expanded=False)

        # 缓存计算结果
        st.session_state[cache_key] = {
            "eval_result": eval_result,
            "boot_result": boot_result,
            "daily_ric": daily_ric,
            "dist_result": dist_result,
            "decay_result": decay_result,
            "autocorr_result": autocorr_result,
            "neut_result": neut_result,
            "time_dim_df": time_dim_df,
        }

        # 保存运行记录到工作台
        rank_ic = eval_result.get("rank_ic_mean", 0)
        icir_val = eval_result.get("icir", 0)
        if rank_ic >= 0.03 and icir_val >= 0.5:
            verdict = "supported"
        elif rank_ic >= 0.01 and icir_val >= 0.3:
            verdict = "conditional"
        elif rank_ic >= 0:
            verdict = "fragile"
        else:
            verdict = "invalid"
        save_run(factor_name, factor_id, verdict,
                  f"RankIC: {rank_ic:.4f}, ICIR: {icir_val:.4f}, "
                  f"覆盖率: {eval_result.get('coverage', 0):.1%}",
                  st.session_state)

# ============================================================
# 指标卡片行（核心指标立即展示）
# ============================================================
st.markdown("### \U0001f4ca 核心指标")

metrics = [
    {
        "label": "IC Mean",
        "value": f"{eval_result['ic_mean']:.4f}",
        "help_text": "因子值与未来收益的 Pearson 相关系数均值"
    },
    {
        "label": "RankIC Mean",
        "value": f"{eval_result['rank_ic_mean']:.4f}",
        "help_text": "因子排名与未来收益排名的 Spearman 相关系数均值"
    },
    {
        "label": "ICIR",
        "value": f"{eval_result['icir']:.4f}",
        "help_text": "IC 信息比率 = IC Mean / IC Std × sqrt(252)"
    },
    {
        "label": "方向一致率",
        "value": f"{eval_result['direction_consistency']:.2%}",
        "help_text": "因子方向与收益方向一致的比例"
    },
    {
        "label": "覆盖率",
        "value": f"{eval_result['coverage']:.2%}",
        "help_text": "有效因子值占股票池的比例"
    },
]

render_metric_row(metrics)

# ============================================================
# Bootstrap 置信区间
# ============================================================
st.markdown("### \U0001f4cf RankIC Bootstrap 估计")
boot_cols = st.columns(4)
with boot_cols[0]:
    st.metric("Bootstrap Mean", f"{boot_result['mean']:.4f}")
with boot_cols[1]:
    st.metric("95% CI 下限", f"{boot_result['ci_lower']:.4f}")
with boot_cols[2]:
    st.metric("95% CI 上限", f"{boot_result['ci_upper']:.4f}")
with boot_cols[3]:
    st.metric("Bootstrap Std", f"{boot_result['std']:.4f}")

# ============================================================
# 图表区
# ============================================================
st.markdown("---")
chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    rolling_ic = eval_result['rolling_ic']
    if not rolling_ic.empty:
        fig_ric = create_rolling_ic_chart(
            dates=rolling_ic['date'],
            rolling_rank_ic=rolling_ic['rolling_rank_ic'],
            title="滚动 RankIC（63日窗口）"
        )
        st.plotly_chart(fig_ric, width='stretch')
    else:
        st.info("数据不足，无法计算滚动 RankIC")

with chart_col2:
    group_returns = eval_result['group_returns']
    if group_returns and any(r != 0 for r in group_returns):
        fig_gr = create_group_return_chart(
            groups=["G1 (低)", "G2", "G3", "G4", "G5 (高)"],
            returns=group_returns,
            title="分组平均收益"
        )
        st.plotly_chart(fig_gr, width='stretch')
    else:
        st.info("数据不足，无法计算分组收益")

# ============================================================
# T017: 因子值分布与覆盖率
# ============================================================
st.markdown("---")
st.markdown("### \U0001f4ca 因子值分布与覆盖率")
dist_col1, dist_col2 = st.columns(2)

with dist_col1:
    if dist_result['factor_values']:
        fig_dist = create_distribution_chart(
            dist_result['factor_values'],
            title="因子值分布"
        )
        st.plotly_chart(fig_dist, width='stretch')
    else:
        st.info("数据不足，无法绘制因子值分布")

with dist_col2:
    if dist_result['coverage_dates']:
        fig_cov = create_coverage_chart(
            dist_result['coverage_dates'],
            dist_result['coverage_values'],
            title="覆盖率时间序列"
        )
        st.plotly_chart(fig_cov, width='stretch')
    else:
        st.info("数据不足，无法绘制覆盖率时间序列")

# ============================================================
# T019: 预测周期衰减
# ============================================================
st.markdown("---")
st.markdown("### \U0001f4c9 预测周期 IC 衰减")
decay_col1, decay_col2 = st.columns(2)

with decay_col1:
    if decay_result['periods']:
        fig_decay = create_decay_chart(
            periods=decay_result['periods'],
            ic_values=decay_result['rank_ic_values'],
            title="RankIC 衰减（不同预测周期）"
        )
        st.plotly_chart(fig_decay, width='stretch')
    else:
        st.info("数据不足，无法计算 IC 衰减")

with decay_col2:
    st.markdown("""
    **IC 衰减说明：**
    - 展示因子在不同预测周期（1/5/10/20日）上的 RankIC 表现
    - 优秀的因子应该在较长的预测周期上仍保持显著的 IC
    - 急剧衰减可能表明因子预测能力短期有效，长期不可靠
    """)

# ============================================================
# T021: 累计收益与换手率
# ============================================================
st.markdown("---")
st.markdown("### \U0001f4c8 累计收益与换手率")
cum_col1, cum_col2 = st.columns(2)

with cum_col1:
    cum_returns = eval_result['cumulative_returns']
    if cum_returns and any(len(v) > 0 for v in cum_returns.values()):
        # 获取所有分组中最长的日期序列
        max_len = max(len(v) for v in cum_returns.values())
        cum_dates = sorted(df['trade_date'].unique())[-max_len:] if max_len > 0 else []
        cum_data = [cum_returns.get(f"G{i+1}", []) for i in range(5)]
        # 确保每个序列长度一致
        cum_data = [list(c) if len(c) == max_len else [0.0] * max_len for c in cum_data]
        fig_cum = create_cumulative_return_chart(
            dates=cum_dates,
            cumulative_returns=cum_data,
            labels=["G1 (低)", "G2", "G3", "G4", "G5 (高)"],
            title="分组累计收益"
        )
        st.plotly_chart(fig_cum, width='stretch')
    else:
        st.info("数据不足，无法计算累计收益")

with cum_col2:
    st.metric("Top 换手率", f"{eval_result['turnover_top']:.4f}")
    st.metric("Bottom 换手率", f"{eval_result['turnover_bottom']:.4f}")
    st.caption("换手率 = 1 / 分组内股票数，值越高说明分组内股票变化越频繁")

# ============================================================
# T022: 因子自相关与中性化对比
# ============================================================
st.markdown("---")
st.markdown("### \U0001f4ca 因子自相关与中性化对比")
auto_col1, auto_col2 = st.columns(2)

with auto_col1:
    if autocorr_result['lags']:
        fig_auto = create_autocorr_chart(
            lags=autocorr_result['lags'],
            autocorr_values=autocorr_result['autocorr_values'],
            title="因子自相关（跨股票均值）"
        )
        st.plotly_chart(fig_auto, width='stretch')
    else:
        st.info("数据不足，无法计算因子自相关")

with auto_col2:
    if neut_result is not None:
        orig = neut_result['original_rank_ic_mean']
        neut = neut_result['neutralized_rank_ic_mean']
        change = neut - orig
        st.metric("原始 RankIC Mean", f"{orig:.4f}")
        st.metric("市值中性化后 RankIC Mean", f"{neut:.4f}", delta=f"{change:.4f}")
        if abs(orig) > 0.001:
            retention = abs(neut / orig) if abs(orig) > 1e-9 else 1.0
            st.metric("中性化保留率", f"{retention:.1%}")
        st.caption("中性化保留率越低，说明因子越依赖市值暴露")
    else:
        st.info("无市值数据，无法计算中性化对比")

# ============================================================
# 详细指标表格
# ============================================================
st.markdown("---")
st.markdown("### \U0001f4cb 详细指标表")

# 构建详细指标表格
detail_data = {
    "指标": [
        "IC Mean", "IC Std", "RankIC Mean", "RankIC Std",
        "ICIR", "IC t-Stat", "IC p-Value",
        "方向一致率", "覆盖率",
        "Top 换手率", "Bottom 换手率",
        "样本数", "日期范围"
    ],
    "数值": [
        f"{eval_result['ic_mean']:.4f}",
        f"{eval_result['ic_std']:.4f}",
        f"{eval_result['rank_ic_mean']:.4f}",
        f"{eval_result['rank_ic_std']:.4f}",
        f"{eval_result['icir']:.4f}",
        f"{eval_result['ic_t_stat']:.4f}",
        f"{eval_result['ic_p_value']:.4f}",
        f"{eval_result['direction_consistency']:.2%}",
        f"{eval_result['coverage']:.2%}",
        f"{eval_result['turnover_top']:.4f}",
        f"{eval_result['turnover_bottom']:.4f}",
        f"{eval_result['sample_count']:,}",
        eval_result['date_range'],
    ],
}

detail_df = pd.DataFrame(detail_data)
st.dataframe(detail_df, width='stretch', hide_index=True)

# ============================================================
# 分组收益明细
# ============================================================
st.markdown("### \U0001f4ca 分组收益明细")
group_labels = ["G1 (低)", "G2", "G3", "G4", "G5 (高)"]
group_data = {
    "分组": group_labels,
    "平均收益": [f"{r:.4f}" for r in eval_result['group_returns']],
}
st.dataframe(pd.DataFrame(group_data), width='stretch', hide_index=True)

# ============================================================
# 时间维度聚合
# ============================================================
st.markdown("---")
st.markdown(f"### \U0001f4c5 按{time_dim}度指标")

if not time_dim_df.empty:
    st.dataframe(time_dim_df, width='stretch', hide_index=True)
else:
    st.info("数据不足，无法按时间维度聚合")

# ============================================================
# 诊断口径说明
# ============================================================
st.markdown("---")
st.markdown("### \U0001f4d6 诊断口径说明")

with st.expander("查看各指标含义与阈值", expanded=False):
    st.markdown("""
    | 指标 | 含义 | 优秀阈值 | 警告阈值 |
    |------|------|----------|----------|
    | **IC Mean** | 因子值与未来收益的 Pearson 相关系数均值 | > 0.03 | < 0.01 |
    | **RankIC Mean** | 因子排名与收益排名的 Spearman 相关系数均值 | > 0.03 | < 0.01 |
    | **ICIR** | IC 信息比率，衡量 IC 的稳定性 | > 0.5 | < 0.3 |
    | **IC t-Stat** | IC 均值的 t 统计量，检验 IC 是否显著非零 | > 2.0 | < 1.65 |
    | **IC p-Value** | IC 的显著性水平 | < 0.05 | > 0.10 |
    | **方向一致率** | 因子方向与收益方向一致的比例 | > 55% | < 50% |
    | **覆盖率** | 有效因子值占股票池的比例 | > 0.8 | < 0.5 |
    | **分组收益** | 按因子值分5组，各组平均收益 | 单调递增 | 不单调 |
    | **Top 换手率** | 高分组日均换手率 | 适中 | 过高/过低 |
    | **滚动 RankIC** | 63日滚动窗口的 RankIC 均值 | 稳定在正值 | 频繁穿越零 |

    **Bootstrap 置信区间**：使用 Block Bootstrap 方法（块长={DEFAULT_BOOTSTRAP_BLOCKS}，重复{DEFAULT_BOOTSTRAP_REPS}次）估计 RankIC Mean 的 95% 置信区间。
    如果置信区间不包含 0，说明因子具有统计显著的预测能力。
    """.format(DEFAULT_BOOTSTRAP_BLOCKS=DEFAULT_BOOTSTRAP_BLOCKS,
               DEFAULT_BOOTSTRAP_REPS=DEFAULT_BOOTSTRAP_REPS))