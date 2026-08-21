# FactorGuard 正式快照

GitHub 源码仓库不跟踪 Parquet 大文件。`manifest.json` 保留正式快照的日期范围、行数、股票数和文件 SHA-256，用于校验 Release 附件。

## 获取方式

1. 从 GitHub Release 下载 `FactorGuard_snapshot_20240927_20250926.zip`。
2. 在仓库根目录解压，确保文件位于 `data/snapshot/`。
3. 对照 `manifest.json` 校验三份 Parquet 的 SHA-256。

也可以在具备原始 CSV 的环境中执行：

```powershell
py scripts\build_snapshots.py --date-start 2024-09-27 --date-end 2025-09-26
```

正式快照文件：

- `daily_ohlcv.parquet`
- `daily_basic.parquet`
- `stock_basic.parquet`

原始 CSV、DuckDB 运行库和 API Key 均不属于 GitHub 源码。
