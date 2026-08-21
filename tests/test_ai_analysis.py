"""Contract tests for the non-authoritative AI analysis sidecar."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pandas as pd
import pytest

from engine.ai_analysis import (
    PROMPT_VERSION,
    build_ai_input,
    generate_ai_analysis,
    get_provider_presets,
    get_provider_ui_defaults,
    is_model_api_key_configured,
    resolve_model_config,
)
from engine.hash_utils import compute_ai_analysis_hash, compute_report_hash
from models.ai_analysis import AIModelPayload
from models.audit_result import AuditResult
from models.evidence import EvidenceRecord


ROOT = Path(__file__).resolve().parents[1]
MODEL_ENV = {
    "FACTORGUARD_LLM_BASE_URL": "https://llm.example.test/v1",
    "FACTORGUARD_LLM_API_KEY": "secret-api-key",
    "FACTORGUARD_LLM_MODEL": "test-model",
}
EXPECTED_PROVIDERS = {
    "openai": ("https://api.openai.com/v1", "gpt-4.1-mini"),
    "deepseek": ("https://api.deepseek.com", "deepseek-chat"),
    "dashscope": (
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "qwen-plus",
    ),
    "zhipu": ("https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
    "moonshot": ("https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    "siliconflow": ("https://api.siliconflow.cn/v1", "Qwen/Qwen3-8B"),
    "custom": ("", ""),
}


def _records():
    return [
        EvidenceRecord(
            evidence_id="E-STATS-001",
            dimension="统计支持",
            severity="warn",
            claim="RankIC Mean = 0.1234",
            metrics={"rank_ic_mean": 0.1234, "sample_count": 120},
            explanation="正式统计证据待补充置信区间。",
        ),
        EvidenceRecord(
            evidence_id="E-STRESS-001",
            dimension="压力稳健性",
            severity="untested",
            claim="压力测试尚未完整执行",
            metrics={},
            explanation="缺少可复现压力测试结果。",
        ),
    ]


def _generate(conclusion="insufficient", *, environment=None, transport=None, records=None):
    return generate_ai_analysis(
        "R001",
        conclusion,
        {"统计支持": "warn", "压力稳健性": "untested"},
        _records() if records is None else records,
        "evidence-hash-1",
        environment=environment,
        transport=transport,
    )


def _valid_response(summary="围绕已有证据继续复核"):
    return {
        "conclusion": "insufficient",
        "summary": summary,
        "counter_arguments": [
            {"text": "复核统计支持证据。", "evidence_ids": ["E-STATS-001"]}
        ],
        "next_experiments": [
            {"text": "补充压力稳健性测试。", "evidence_ids": ["E-STRESS-001"]}
        ],
    }


def test_missing_model_environment_uses_rule_fallback():
    result = _generate(environment={})

    assert result.source == "rule_fallback"
    assert result.model == "deterministic-rules"
    assert result.fallback_reason
    assert result.conclusion == "insufficient"


def test_rule_fallback_is_deterministic():
    first = _generate(environment={}).model_dump()
    second = _generate(environment={}).model_dump()

    assert first == second


def test_valid_model_response_is_accepted():
    calls = []

    def transport(config, payload):
        calls.append((config, payload))
        return _valid_response()

    result = _generate(environment=MODEL_ENV, transport=transport)

    assert result.source == "model"
    assert result.model == "test-model"
    assert result.fallback_reason is None
    assert len(calls) == 1


def test_provider_presets_have_expected_compatible_defaults():
    presets = {preset.provider_id: preset for preset in get_provider_presets()}

    assert set(presets) == set(EXPECTED_PROVIDERS)
    for provider_id, (base_url, model) in EXPECTED_PROVIDERS.items():
        assert presets[provider_id].base_url == base_url
        assert presets[provider_id].default_model == model


@pytest.mark.parametrize(
    "provider_id",
    ["openai", "deepseek", "dashscope", "zhipu", "moonshot", "siliconflow"],
)
def test_provider_preset_resolves_chat_completions_endpoint(provider_id):
    config, error_message = resolve_model_config(
        {"FACTORGUARD_LLM_API_KEY": "secret-api-key"},
        provider=provider_id,
    )

    expected_base, expected_model = EXPECTED_PROVIDERS[provider_id]
    assert error_message is None
    assert config is not None
    assert config.provider == provider_id
    assert config.base_url == expected_base
    assert config.model == expected_model
    assert config.endpoint == expected_base.rstrip("/") + "/chat/completions"


def test_configuration_precedence_is_explicit_then_environment_then_preset():
    environment = {
        "FACTORGUARD_LLM_PROVIDER": "openai",
        "FACTORGUARD_LLM_BASE_URL": "https://gateway.example.test/v1",
        "FACTORGUARD_LLM_API_KEY": "secret-api-key",
        "FACTORGUARD_LLM_MODEL": "environment-model",
    }

    environment_config, error_message = resolve_model_config(
        environment,
        provider="deepseek",
    )
    explicit_config, explicit_error = resolve_model_config(
        environment,
        provider="deepseek",
        base_url="https://explicit.example.test/v1",
        model="explicit-model",
    )

    assert error_message is None
    assert environment_config is not None
    assert environment_config.provider == "deepseek"
    assert environment_config.base_url == "https://gateway.example.test/v1"
    assert environment_config.model == "environment-model"
    assert explicit_error is None
    assert explicit_config is not None
    assert explicit_config.base_url == "https://explicit.example.test/v1"
    assert explicit_config.model == "explicit-model"


def test_legacy_environment_only_configuration_remains_supported():
    config, error_message = resolve_model_config(MODEL_ENV)

    assert error_message is None
    assert config is not None
    assert config.provider == "custom"
    assert config.base_url == MODEL_ENV["FACTORGUARD_LLM_BASE_URL"]
    assert config.model == MODEL_ENV["FACTORGUARD_LLM_MODEL"]


def test_provider_ui_defaults_and_key_status_never_return_secret():
    environment = {
        "FACTORGUARD_LLM_PROVIDER": "deepseek",
        "FACTORGUARD_LLM_BASE_URL": "https://gateway.example.test/v1",
        "FACTORGUARD_LLM_API_KEY": "secret-api-key",
        "FACTORGUARD_LLM_MODEL": "private-model",
    }

    ui_defaults = get_provider_ui_defaults("deepseek", environment)

    assert ui_defaults == ("private-model", "https://gateway.example.test/v1")
    assert is_model_api_key_configured(environment) is True
    assert "secret-api-key" not in repr(ui_defaults)


def test_unknown_provider_and_incomplete_custom_provider_fall_back():
    incomplete_custom = generate_ai_analysis(
        "R001",
        "insufficient",
        {"统计支持": "warn"},
        _records(),
        "evidence-hash-1",
        provider="custom",
        model="custom-model",
        base_url="",
        environment={"FACTORGUARD_LLM_API_KEY": "secret-api-key"},
        transport=lambda *_: _valid_response(),
    )
    unsupported = generate_ai_analysis(
        "R001",
        "insufficient",
        {"统计支持": "warn"},
        _records(),
        "evidence-hash-1",
        provider="not-a-provider",
        model="custom-model",
        base_url="https://llm.example.test/v1",
        environment={"FACTORGUARD_LLM_API_KEY": "secret-api-key"},
        transport=lambda *_: _valid_response(),
    )

    assert incomplete_custom.source == "rule_fallback"
    assert "FACTORGUARD_LLM_BASE_URL" in incomplete_custom.fallback_reason
    assert unsupported.source == "rule_fallback"
    assert "不支持的模型供应商" in unsupported.fallback_reason


def test_selected_provider_without_api_key_falls_back_without_calling_transport():
    calls = []
    result = generate_ai_analysis(
        "R001",
        "insufficient",
        {"统计支持": "warn"},
        _records(),
        "evidence-hash-1",
        provider="deepseek",
        model="deepseek-chat",
        environment={},
        transport=lambda *_: calls.append(True),
    )

    assert result.source == "rule_fallback"
    assert result.provider == "deepseek"
    assert result.model == "deepseek-chat"
    assert result.fallback_reason == "模型未配置：FACTORGUARD_LLM_API_KEY"
    assert calls == []


@pytest.mark.parametrize(
    "response",
    [
        {**_valid_response(), "conclusion": "supported"},
        (
            {
                **_valid_response(),
                "counter_arguments": [
                    {"text": "复核。", "evidence_ids": ["E-NOT-REAL"]}
                ],
            }
        ),
        {**_valid_response(summary="结果为 99.99")},
        "not-json",
    ],
)
def test_invalid_model_output_falls_back(response):
    result = _generate(environment=MODEL_ENV, transport=lambda *_: response)

    assert result.source == "rule_fallback"
    assert result.model == "test-model"
    assert result.fallback_reason


@pytest.mark.parametrize("exc", [TimeoutError("timed out"), OSError("network down")])
def test_timeout_and_network_errors_fall_back(exc):
    def transport(*_):
        raise exc

    result = _generate(environment=MODEL_ENV, transport=transport)

    assert result.source == "rule_fallback"
    assert result.fallback_reason == str(exc)


def test_model_request_excludes_key_paths_and_raw_dataframe():
    captured = {}
    records = _records()
    records[0].metrics["raw_frame"] = pd.DataFrame({"close": [1, 2]})

    def transport(config, payload):
        captured["config"] = config
        captured["payload"] = payload
        return _valid_response()

    result = _generate(environment=MODEL_ENV, transport=transport, records=records)
    payload_text = json.dumps(captured["payload"], ensure_ascii=False, default=str)

    assert result.source == "model"
    assert MODEL_ENV["FACTORGUARD_LLM_API_KEY"] not in payload_text
    assert "F:\\Quantclass" not in payload_text
    assert "DataFrame" not in payload_text
    assert "raw_frame" not in captured["payload"]["messages"][1]["content"]
    assert captured["config"].api_key == MODEL_ENV["FACTORGUARD_LLM_API_KEY"]
    assert MODEL_ENV["FACTORGUARD_LLM_API_KEY"] not in result.model_dump_json()
    assert MODEL_ENV["FACTORGUARD_LLM_API_KEY"] not in result.ai_analysis_hash
    assert MODEL_ENV["FACTORGUARD_LLM_API_KEY"] not in repr(captured["config"])


def test_transport_error_cannot_expose_api_key_in_fallback_reason():
    def transport(config, _payload):
        raise RuntimeError(f"request rejected for {config.api_key}")

    result = _generate(environment=MODEL_ENV, transport=transport)

    assert result.source == "rule_fallback"
    assert MODEL_ENV["FACTORGUARD_LLM_API_KEY"] not in result.fallback_reason
    assert "[api-key-redacted]" in result.fallback_reason


def test_model_input_redacts_local_paths():
    record = _records()[0]
    record.explanation = r"原始文件：F:\Quantclass\stock-trading-data-pro"
    payload = build_ai_input("R001", "insufficient", {}, [record], "eh")
    encoded = json.dumps(payload, ensure_ascii=False)

    assert "F:\\Quantclass" not in encoded
    assert "[local-path-redacted]" in encoded


def test_empty_environment_does_not_fall_back_to_process_environment(monkeypatch):
    monkeypatch.setenv("FACTORGUARD_LLM_BASE_URL", MODEL_ENV["FACTORGUARD_LLM_BASE_URL"])
    monkeypatch.setenv("FACTORGUARD_LLM_API_KEY", MODEL_ENV["FACTORGUARD_LLM_API_KEY"])
    monkeypatch.setenv("FACTORGUARD_LLM_MODEL", MODEL_ENV["FACTORGUARD_LLM_MODEL"])

    result = _generate(environment={})

    assert result.source == "rule_fallback"


def test_empty_evidence_uses_a_real_input_evidence_id():
    result = _generate(environment={}, records=[])

    cited = {
        evidence_id
        for item in result.counter_arguments + result.next_experiments
        for evidence_id in item.evidence_ids
    }
    assert cited == {"E-UNAVAILABLE"}


def test_ai_text_does_not_change_formal_report_hash():
    formal_payload = {"conclusion": "insufficient", "dimensions": {"统计支持": "warn"}}
    report_hash = compute_report_hash("evidence-hash-1", formal_payload)
    first = _generate(environment=MODEL_ENV, transport=lambda *_: _valid_response("文本 A"))
    second = _generate(environment=MODEL_ENV, transport=lambda *_: _valid_response("文本 B"))

    assert first.ai_analysis_hash != second.ai_analysis_hash
    assert compute_report_hash("evidence-hash-1", formal_payload) == report_hash


def test_ai_analysis_hash_changes_with_text_model_and_prompt_version():
    first = _generate(environment=MODEL_ENV, transport=lambda *_: _valid_response("文本 A"))
    second = _generate(environment=MODEL_ENV, transport=lambda *_: _valid_response("文本 B"))

    assert first.ai_analysis_hash != second.ai_analysis_hash
    assert compute_ai_analysis_hash(
        "evidence-hash-1",
        first.model_dump(exclude={"ai_analysis_hash", "fallback_reason", "disclaimer"}),
        model="another-model",
        prompt_version=PROMPT_VERSION,
    ) != first.ai_analysis_hash
    assert compute_ai_analysis_hash(
        "evidence-hash-1",
        first.model_dump(exclude={"ai_analysis_hash", "fallback_reason", "disclaimer"}),
        model=first.model,
        prompt_version="factor-guard-ai-audit-v2",
    ) != first.ai_analysis_hash


def test_provider_and_model_changes_only_change_ai_analysis_hash():
    environment = {"FACTORGUARD_LLM_API_KEY": "secret-api-key"}
    formal_payload = {"conclusion": "insufficient", "dimensions": {"统计支持": "warn"}}
    report_hash = compute_report_hash("evidence-hash-1", formal_payload)
    openai = generate_ai_analysis(
        "R001",
        "insufficient",
        {"统计支持": "warn", "压力稳健性": "untested"},
        _records(),
        "evidence-hash-1",
        provider="openai",
        model="shared-model",
        environment=environment,
        transport=lambda *_: _valid_response(),
    )
    deepseek = generate_ai_analysis(
        "R001",
        "insufficient",
        {"统计支持": "warn", "压力稳健性": "untested"},
        _records(),
        "evidence-hash-1",
        provider="deepseek",
        model="shared-model",
        environment=environment,
        transport=lambda *_: _valid_response(),
    )
    another_model = generate_ai_analysis(
        "R001",
        "insufficient",
        {"统计支持": "warn", "压力稳健性": "untested"},
        _records(),
        "evidence-hash-1",
        provider="openai",
        model="another-model",
        environment=environment,
        transport=lambda *_: _valid_response(),
    )

    assert openai.ai_analysis_hash != deepseek.ai_analysis_hash
    assert openai.ai_analysis_hash != another_model.ai_analysis_hash
    assert compute_report_hash("evidence-hash-1", formal_payload) == report_hash


def test_formal_exports_exclude_ai_text_and_page_has_three_downloads():
    source_path = ROOT / "pages" / "08_报告与凭证.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    download_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "download_button"
    ]
    assert len(download_calls) == 3

    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_generate_html_report", "_generate_markdown_report"}
    ]
    namespace = {
        "get_verdict_color": lambda _: "#000000",
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source_path), "exec"), namespace)
    audit = AuditResult(
        factor_id="R001",
        run_id="run-1",
        timestamp="2026-01-01T00:00:00",
        conclusion="insufficient",
        evidence_dimensions={"统计支持": "warn"},
    )
    records = _records()
    html = namespace["_generate_html_report"](audit, records, "evidence-hash-1", "report-hash-1")
    markdown = namespace["_generate_markdown_report"](
        audit, records, "evidence-hash-1", "report-hash-1"
    )

    assert "文本 A" not in html + markdown
    assert "ai_analysis" not in html + markdown
    assert "evidence-hash-1" in html + markdown

    page_source = source_path.read_text(encoding="utf-8")
    assert "FACTORGUARD_LLM_API_KEY" in page_source
    assert "type=\"password\"" not in page_source
    assert "password_input" not in page_source
    assert "os.environ" not in page_source


def test_ai_payload_model_rejects_extra_fields():
    with pytest.raises(Exception):
        AIModelPayload.model_validate({**_valid_response(), "formal_conclusion": "insufficient"})
