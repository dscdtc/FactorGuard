"""Check competition-facing entry pages and capability labels."""

from pathlib import Path
import sys

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _visible_text(app: AppTest) -> str:
    values = []
    for element_type in (app.markdown, app.caption, app.info, app.warning, app.title):
        values.extend(str(item.value) for item in element_type)
    return "\n".join(values)


def main() -> None:
    snapshot_ready = all(
        (ROOT / "data" / "snapshot" / name).is_file()
        for name in ("daily_ohlcv.parquet", "daily_basic.parquet")
    )
    home = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not home.exception
    home_text = _visible_text(home)
    assert "2024-09-27 至 2025-09-26" in home_text
    assert "2019-2026" not in home_text
    assert "Python脚本" not in home_text
    metrics = {metric.label: metric.value for metric in home.metric}
    assert metrics["行情快照"] == ("已就绪" if snapshot_ready else "缺失")
    assert metrics["样本区间"] == "2024-09-27 至 2025-09-26"
    assert metrics["覆盖股票"] == "5,473 只"
    assert metrics["样本行数"] == "1,314,224"
    if not snapshot_ready:
        assert "目前只能查看历史预计算摘要" in home_text
    assert any(button.label == "新建鉴证" for button in home.button)
    assert sum(button.label == "运行" for button in home.button) == 4

    factor_input = AppTest.from_file(
        str(ROOT / "pages" / "02_因子输入.py"), default_timeout=60
    ).run()
    assert not factor_input.exception
    factor_input_text = _visible_text(factor_input)
    assert "共 806 / 806 个因子" in factor_input_text
    tab_labels = [tab.label for tab in factor_input.tabs]
    assert len(tab_labels) == 4
    assert all("Python" not in label for label in tab_labels)
    assert any(button.label == "解析为结构化定义" for button in factor_input.button)

    print("entry pages ok")


if __name__ == "__main__":
    main()
