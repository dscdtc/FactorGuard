"""Run the one-stop audit page against the frozen competition snapshot."""

import json
from pathlib import Path
import sys

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests" / "artifacts" / "apptest_real_audit.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.factor_loader import get_factor_by_id


def main() -> None:
    spec = get_factor_by_id("R001")
    assert spec is not None

    at = AppTest.from_file(
        str(ROOT / "pages" / "09_鉴证运行.py"), default_timeout=180
    )
    at.session_state["selected_factor_id"] = spec.factor_id
    at.session_state["selected_factor_name"] = spec.name_cn
    at.session_state["selected_factor_spec"] = spec
    at.session_state["forward_period"] = 5
    at.run(timeout=180)
    assert not at.exception

    start = next(button for button in at.button if "开始鉴证" in button.label)
    start.click().run(timeout=180)
    assert not at.exception

    state = at.session_state.filtered_state
    audit_results = state["audit_results"]
    stress = audit_results["stress_test"]
    audit = audit_results["audit_result"]
    tests = stress["test_results"]

    assert len(tests) == 4
    assert all(item["verdict"] != "untested" for item in tests)
    assert audit["conclusion"] == "insufficient"
    assert audit["evidence_dimensions"]["统计支持"] == "fail"
    assert state["recent_runs"][0]["verdict"] == audit["conclusion"]

    payload = {
        "factor_id": spec.factor_id,
        "rows": audit_results["data_align"]["rows"],
        "stocks": audit_results["data_align"]["stocks"],
        "rank_ic_mean": audit_results["traditional_eval"]["rank_ic_mean"],
        "stress_verdicts": {
            item["test_name"]: item["verdict"] for item in tests
        },
        "conclusion": audit["conclusion"],
        "evidence_dimensions": audit["evidence_dimensions"],
    }
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(OUTPUT)


if __name__ == "__main__":
    main()
