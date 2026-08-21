from pathlib import Path
import json
import os
import sys
from streamlit.testing.v1 import AppTest


OUTPUT = Path("tests") / "artifacts" / "apptest_full_flow.txt"
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
ROOT = Path(__file__).resolve().parents[1]
os.environ["FACTORGUARD_OFFLINE_MODE"] = "1"
for name in (
    "FACTORGUARD_LLM_PROVIDER",
    "FACTORGUARD_LLM_BASE_URL",
    "FACTORGUARD_LLM_API_KEY",
    "FACTORGUARD_LLM_MODEL",
    "FACTORGUARD_LLM_TIMEOUT",
):
    os.environ.pop(name, None)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_page(path: str, session_state: dict, timeout: int = 60):
    at = AppTest.from_file(str(ROOT / path), default_timeout=timeout)
    for key, value in session_state.items():
        at.session_state[key] = value
    at.run(timeout=timeout)
    return at


def main():
    shared_state = {
        "selected_factor_id": "R001",
        "selected_factor_name": "R001",
        "audit_results": {},
    }

    results = []

    trad = run_page("pages/03_传统评估.py", shared_state)
    shared_state.update(trad.session_state.filtered_state)
    assert not trad.exception
    assert shared_state["audit_results"]["traditional_eval"]["source"] == "precomputed"
    results.append(("03_传统评估", len(trad.exception), list(shared_state.get("audit_results", {}).keys())))

    stress = run_page("pages/04_压力测试.py", shared_state)
    shared_state.update(stress.session_state.filtered_state)
    assert not stress.exception
    assert shared_state["audit_results"]["stress_test"]["source"] == "demo"
    assert shared_state["audit_results"]["stress_test"]["summary"]["overall_verdict"] == "untested"
    results.append(("04_压力测试", len(stress.exception), list(shared_state.get("audit_results", {}).keys())))

    dup = run_page("pages/05_重复性检测.py", shared_state)
    shared_state.update(dup.session_state.filtered_state)
    assert not dup.exception
    assert "duplicate_check" not in shared_state["audit_results"]
    results.append(("05_重复性检测", len(dup.exception), list(shared_state.get("audit_results", {}).keys())))

    suit = run_page("pages/06_适用性地图.py", shared_state)
    shared_state.update(suit.session_state.filtered_state)
    assert not suit.exception
    assert shared_state["audit_results"]["suitability"]["source"] == "demo"
    results.append(("06_适用性地图", len(suit.exception), "suitability_results" in shared_state))

    report = run_page("pages/08_报告与凭证.py", shared_state)
    shared_state.update(report.session_state.filtered_state)
    assert not report.exception
    assert len(report.download_button) == 3
    assert [tab.label for tab in report.tabs] == [
        "总览",
        "AI 辅助解读",
        "数据与时间质检",
        "传统评估",
        "压力测试",
        "重复性",
        "适用性",
        "复现凭证",
    ]
    assert "run_persistence_error" not in shared_state
    assert any("证据不足" in item.value for item in report.markdown)
    provider_select = next(
        item for item in report.selectbox if item.label == "模型供应商"
    )
    assert provider_select.value == "openai"
    assert len(provider_select.options) == 7
    assert any(item.label == "模型 ID" for item in report.text_input)
    assert all("API Key" not in item.label for item in report.text_input)
    ai_button = next(button for button in report.button if button.label == "生成 AI 辅助解读")
    ai_button.click().run(timeout=60)
    assert not report.exception
    ai_analysis = report.session_state.filtered_state["audit_results"]["ai_analysis"]
    assert ai_analysis["source"] == "rule_fallback"
    assert ai_analysis["provider"] == "openai"
    assert ai_analysis["model"] == "gpt-4.1-mini"
    assert ai_analysis["fallback_reason"]
    assert ai_analysis["ai_analysis_hash"]
    assert len(report.download_button) == 3
    results.append(("08_报告与凭证", len(report.exception), len(report.download_button)))

    shared_state.update(report.session_state.filtered_state)
    secret_sentinel = "factor-guard-session-secret-sentinel"
    os.environ["FACTORGUARD_LLM_PROVIDER"] = "openai"
    os.environ["FACTORGUARD_LLM_BASE_URL"] = "http://127.0.0.1:9/v1"
    os.environ["FACTORGUARD_LLM_API_KEY"] = secret_sentinel
    os.environ["FACTORGUARD_LLM_MODEL"] = "test-model"
    os.environ["FACTORGUARD_LLM_TIMEOUT"] = "1"
    secure_report = run_page("pages/08_报告与凭证.py", shared_state)
    secure_button = next(
        button for button in secure_report.button if button.label == "生成 AI 辅助解读"
    )
    secure_button.click().run(timeout=60)
    secure_state_json = json.dumps(
        secure_report.session_state.filtered_state,
        ensure_ascii=False,
        default=str,
    )
    assert secret_sentinel not in secure_state_json
    assert secure_report.session_state.filtered_state["audit_results"]["ai_analysis"]["source"] == "rule_fallback"

    lines = []
    for item in results:
        lines.append(str(item))
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(str(OUTPUT))


if __name__ == "__main__":
    main()
