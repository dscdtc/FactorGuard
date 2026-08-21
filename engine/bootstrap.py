"""
Bootstrap 模块
- 使用 Block Bootstrap 估计 RankIC Mean 的置信区间
"""
import numpy as np
import pandas as pd
from config import DEFAULT_BOOTSTRAP_BLOCKS, DEFAULT_BOOTSTRAP_REPS, DEFAULT_BOOTSTRAP_SEED


def bootstrap_rank_ic(aligned_df: pd.DataFrame,
                      block_size: int = DEFAULT_BOOTSTRAP_BLOCKS,
                      n_reps: int = DEFAULT_BOOTSTRAP_REPS,
                      seed: int = DEFAULT_BOOTSTRAP_SEED,
                      daily_rank_ic: dict | None = None) -> dict:
    """Block Bootstrap 估计 RankIC Mean 的置信区间

    1. 将日期序列按 block_size 分块
    2. 每次抽样：从块中随机选择 ceil(N/blocks) 个块（有放回）
    3. 计算该样本的 RankIC Mean
    4. 重复 n_reps 次
    5. 返回 mean, ci_lower, ci_upper, std

    Parameters
    ----------
    aligned_df : pd.DataFrame
        对齐后的 DataFrame，含 ts_code, trade_date, factor_value, forward_return
    block_size : int
        块大小（交易日数），默认 20
    n_reps : int
        重复次数，默认 500
    seed : int
        随机种子

    Returns
    -------
    dict
        {"mean": float, "ci_lower": float, "ci_upper": float, "std": float}
    """
    df = aligned_df.copy()
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.dropna(subset=['factor_value', 'forward_return'])
    df = df[~np.isinf(df['factor_value']) & ~np.isinf(df['forward_return'])]

    if df.empty:
        return {"mean": 0.0, "ci_lower": 0.0, "ci_upper": 0.0, "std": 0.0}

    dates = sorted(df['trade_date'].unique())
    n_dates = len(dates)

    if n_dates < block_size:
        block_size = max(1, n_dates)

    # 将日期序列按 block_size 分块
    blocks = []
    for i in range(0, n_dates, block_size):
        block = dates[i:i + block_size]
        blocks.append(block)

    n_blocks = len(blocks)
    blocks_per_rep = max(1, int(np.ceil(n_dates / block_size)))

    rng = np.random.RandomState(seed)

    # 预计算每日 RankIC —— 优先使用传入的预计算结果
    if daily_rank_ic is not None:
        local_rank_ic = daily_rank_ic["rank_ic"]
    else:
        local_rank_ic = {}
        for date in dates:
            day = df[df['trade_date'] == date]
            if len(day) < 10:
                continue
            ric = day['factor_value'].rank().corr(day['forward_return'].rank())
            if not np.isnan(ric):
                local_rank_ic[date] = ric

    if not local_rank_ic:
        return {"mean": 0.0, "ci_lower": 0.0, "ci_upper": 0.0, "std": 0.0}

    # Bootstrap
    boot_means = []
    for _ in range(n_reps):
        # 从块中随机选择 blocks_per_rep 个块（有放回）
        sampled_block_indices = rng.randint(0, n_blocks, size=blocks_per_rep)
        sampled_dates = []
        for idx in sampled_block_indices:
            sampled_dates.extend(blocks[idx])

        # 计算该样本的 RankIC Mean
        sampled_ics = [local_rank_ic[d] for d in sampled_dates if d in local_rank_ic]
        if sampled_ics:
            boot_means.append(np.mean(sampled_ics))

    boot_means = np.array(boot_means)

    mean = float(np.mean(boot_means)) if len(boot_means) > 0 else 0.0
    std = float(np.std(boot_means, ddof=1)) if len(boot_means) > 1 else 0.0
    ci_lower = float(np.percentile(boot_means, 2.5)) if len(boot_means) > 0 else 0.0
    ci_upper = float(np.percentile(boot_means, 97.5)) if len(boot_means) > 0 else 0.0

    return {
        "mean": mean,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "std": std,
    }