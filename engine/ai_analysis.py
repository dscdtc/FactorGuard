"""Evidence-constrained model analysis with deterministic fallback."""

from __future__ import annotations

import json
import math
import numbers
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence
from urllib import error, request
from urllib.parse import urlsplit

from engine.hash_utils import compute_ai_analysis_hash
from models.ai_analysis import AIAnalysisItem, AIAnalysisResult, AIModelPayload


PROMPT_VERSION = "factor-guard-ai-audit-v1"
DISCLAIMER = "AI 辅助解读，不构成正式鉴证结论。"
_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:\.\d+)?%?")
_LOCAL_PATH_PATTERN = re.compile(r"(?:(?:[A-Za-z]:[\\/])|(?:\\\\))[^\s\"'<>]+")


@dataclass(frozen=True)
class ProviderPreset:
    provider_id: str
    display_name: str
    base_url: str
    default_model: str


PROVIDER_PRESETS = (
    ProviderPreset("openai", "OpenAI", "https://api.openai.com/v1", "gpt-4.1-mini"),
    ProviderPreset("deepseek", "DeepSeek", "https://api.deepseek.com", "deepseek-chat"),
    ProviderPreset(
        "dashscope",
        "通义千问 / DashScope",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "qwen-plus",
    ),
    ProviderPreset(
        "zhipu",
        "智谱",
        "https://open.bigmodel.cn/api/paas/v4",
        "glm-4-flash",
    ),
    ProviderPreset(
        "moonshot",
        "Moonshot / Kimi",
        "https://api.moonshot.cn/v1",
        "moonshot-v1-8k",
    ),
    ProviderPreset(
        "siliconflow",
        "硅基流动",
        "https://api.siliconflow.cn/v1",
        "Qwen/Qwen3-8B",
    ),
    ProviderPreset("custom", "自定义 OpenAI-compatible", "", ""),
)
_PROVIDER_BY_ID = {preset.provider_id: preset for preset in PROVIDER_PRESETS}
_PROVIDER_ALIASES = {
    "qwen": "dashscope",
    "tongyi": "dashscope",
    "aliyun": "dashscope",
    "glm": "zhipu",
    "bigmodel": "zhipu",
    "kimi": "moonshot",
    "silicon-flow": "siliconflow",
    "openai-compatible": "custom",
}


def _json_safe(value):
    """Keep model input to JSON primitives and drop non-auditable objects."""
    if isinstance(value, str):
        return _LOCAL_PATH_PATTERN.sub("[local-path-redacted]", value)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, Mapping):
        return {
            _LOCAL_PATH_PATTERN.sub("[local-path-redacted]", str(key)): safe_value
            for key, item in value.items()
            if (safe_value := _json_safe(item)) is not _UNSAFE
        }
    if isinstance(value, (list, tuple)):
        return [safe_value for item in value if (safe_value := _json_safe(item)) is not _UNSAFE]
    return _UNSAFE


class _UnsafeValue:
    pass


_UNSAFE = _UnsafeValue()


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    base_url: str
    api_key: str = field(repr=False)
    model: str
    timeout: float = 20.0

    @property
    def endpoint(self) -> str:
        base = self.base_url.rstrip("/")
        return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


@dataclass(frozen=True)
class ModelSettings:
    provider: str
    base_url: str
    model: str


def get_provider_presets() -> tuple[ProviderPreset, ...]:
    """Return public, non-secret provider defaults for UI and tests."""
    return PROVIDER_PRESETS


def get_provider_preset(provider: str) -> ProviderPreset:
    provider_id = _normalize_provider_id(provider)
    if provider_id not in _PROVIDER_BY_ID:
        raise ValueError(f"不支持的模型供应商：{provider}")
    return _PROVIDER_BY_ID[provider_id]


def _normalize_provider_id(provider: object) -> str:
    provider_id = str(provider or "").strip().lower()
    return _PROVIDER_ALIASES.get(provider_id, provider_id)


def get_default_provider_id(environment: Mapping[str, str] | None = None) -> str:
    """Choose a safe UI default without exposing any secret value."""
    env = os.environ if environment is None else environment
    configured = _normalize_provider_id(env.get("FACTORGUARD_LLM_PROVIDER", ""))
    if configured in _PROVIDER_BY_ID:
        return configured

    base_url = env.get("FACTORGUARD_LLM_BASE_URL", "").strip().lower()
    if base_url:
        for preset in PROVIDER_PRESETS:
            if preset.base_url and base_url.startswith(preset.base_url.lower()):
                return preset.provider_id
        return "custom"
    return "openai"


def get_provider_ui_defaults(
    provider: str,
    environment: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Return model and base URL defaults; never return the API key."""
    env = os.environ if environment is None else environment
    preset = get_provider_preset(provider)
    model = env.get("FACTORGUARD_LLM_MODEL", "").strip() or preset.default_model
    base_url = env.get("FACTORGUARD_LLM_BASE_URL", "").strip() or preset.base_url
    return model, base_url


def is_model_api_key_configured(environment: Mapping[str, str] | None = None) -> bool:
    """Expose key presence only; callers cannot obtain the secret through this API."""
    env = os.environ if environment is None else environment
    return bool(env.get("FACTORGUARD_LLM_API_KEY", "").strip())


def _resolve_model_settings(
    environment: Mapping[str, str],
    *,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> tuple[ModelSettings | None, str | None]:
    has_explicit_setting = any(value is not None for value in (provider, model, base_url))
    has_environment_setting = any(
        environment.get(name, "").strip()
        for name in (
            "FACTORGUARD_LLM_PROVIDER",
            "FACTORGUARD_LLM_BASE_URL",
            "FACTORGUARD_LLM_API_KEY",
            "FACTORGUARD_LLM_MODEL",
        )
    )
    if not has_explicit_setting and not has_environment_setting:
        return None, "模型未配置：FACTORGUARD_LLM_API_KEY"

    raw_provider = (
        provider
        if provider is not None
        else environment.get("FACTORGUARD_LLM_PROVIDER", "").strip()
    )
    if raw_provider:
        provider_id = _normalize_provider_id(raw_provider)
    elif environment.get("FACTORGUARD_LLM_BASE_URL", "").strip() or environment.get(
        "FACTORGUARD_LLM_MODEL", ""
    ).strip():
        provider_id = "custom"
    else:
        provider_id = "openai"

    if provider_id not in _PROVIDER_BY_ID:
        settings = ModelSettings(
            provider=provider_id or "unknown",
            base_url=(base_url or environment.get("FACTORGUARD_LLM_BASE_URL", "")).strip(),
            model=(model or environment.get("FACTORGUARD_LLM_MODEL", "")).strip(),
        )
        return settings, f"不支持的模型供应商：{raw_provider}"

    preset = _PROVIDER_BY_ID[provider_id]
    resolved_model = (
        str(model).strip()
        if model is not None
        else environment.get("FACTORGUARD_LLM_MODEL", "").strip() or preset.default_model
    )
    resolved_base_url = (
        str(base_url).strip()
        if base_url is not None
        else environment.get("FACTORGUARD_LLM_BASE_URL", "").strip() or preset.base_url
    )
    settings = ModelSettings(provider_id, resolved_base_url, resolved_model)

    missing = []
    if not resolved_base_url:
        missing.append("FACTORGUARD_LLM_BASE_URL")
    if not resolved_model:
        missing.append("FACTORGUARD_LLM_MODEL")
    if missing:
        return settings, "模型未配置：" + "、".join(missing)

    parsed_url = urlsplit(resolved_base_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        return settings, "模型 Base URL 必须是有效的 HTTP(S) 地址"
    if parsed_url.username or parsed_url.password:
        return settings, "模型 Base URL 不得包含凭据"
    return settings, None


def _resolve_model_config_details(
    environment: Mapping[str, str],
    *,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> tuple[ModelConfig | None, str | None, ModelSettings | None]:
    settings, settings_error = _resolve_model_settings(
        environment,
        provider=provider,
        model=model,
        base_url=base_url,
    )
    if settings_error:
        return None, settings_error, settings

    api_key = environment.get("FACTORGUARD_LLM_API_KEY", "").strip()
    if not api_key:
        return None, "模型未配置：FACTORGUARD_LLM_API_KEY", settings
    try:
        timeout = float(environment.get("FACTORGUARD_LLM_TIMEOUT", "20"))
    except ValueError:
        timeout = 20.0
    config = ModelConfig(
        settings.provider,
        settings.base_url,
        api_key,
        settings.model,
        min(60.0, max(1.0, timeout)),
    )
    return config, None, settings


def resolve_model_config(
    environment: Mapping[str, str] | None = None,
    *,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> tuple[ModelConfig | None, str | None]:
    """Resolve explicit overrides, environment values, then provider defaults."""
    env = os.environ if environment is None else environment
    config, config_error, _ = _resolve_model_config_details(
        env,
        provider=provider,
        model=model,
        base_url=base_url,
    )
    return config, config_error


def build_ai_input(
    factor_id: str,
    conclusion: str,
    evidence_dimensions: dict,
    records: Sequence,
    evidence_hash: str,
) -> dict:
    """Build the only data contract allowed to leave FactorGuard."""
    safe_records = []
    for record in records:
        item = record.model_dump() if hasattr(record, "model_dump") else dict(record)
        safe_records.append(
            {
                "evidence_id": _safe_or_default(item.get("evidence_id"), ""),
                "dimension": _safe_or_default(item.get("dimension"), ""),
                "severity": _safe_or_default(item.get("severity"), "untested"),
                "claim": _safe_or_default(item.get("claim"), ""),
                "metrics": _safe_or_default(item.get("metrics", {}), {}),
                "explanation": _safe_or_default(item.get("explanation", ""), ""),
            }
        )
    if not safe_records:
        safe_records.append(
            {
                "evidence_id": "E-UNAVAILABLE",
                "dimension": "证据",
                "severity": "untested",
                "claim": "未提供结构化证据",
                "metrics": {},
                "explanation": "没有可供辅助解读引用的正式证据记录。",
            }
        )
    return {
        "factor_id": _safe_or_default(factor_id, ""),
        "formal_conclusion": _safe_or_default(conclusion, ""),
        "evidence_dimensions": _safe_or_default(evidence_dimensions, {}),
        "evidence_hash": _safe_or_default(evidence_hash, ""),
        "evidence_records": safe_records,
    }


def _safe_or_default(value, default):
    safe_value = _json_safe(value)
    return default if safe_value is _UNSAFE else safe_value


def _request_payload(model: str, ai_input: dict) -> dict:
    system_prompt = (
        "你是 FactorGuard 的投研反方审查员。只能使用用户提供的证据，不能修改正式结论，"
        "不能引入证据中不存在的数字。返回单个 JSON 对象，字段必须为 conclusion、summary、"
        "counter_arguments、next_experiments。后两项各为 1 至 3 个对象，每个对象只有 text 和"
        " evidence_ids；所有 evidence_ids 必须引用输入中的真实证据编号。"
    )
    return {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(ai_input, ensure_ascii=False)},
        ],
    }


def _http_transport(config: ModelConfig, payload: dict) -> str:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    http_request = request.Request(
        config.endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(http_request, timeout=config.timeout) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise RuntimeError(f"模型服务返回 HTTP {exc.code}") from exc
    except error.URLError as exc:
        raise RuntimeError("模型服务不可用或超时") from exc
    try:
        return response_data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("模型响应缺少 choices[0].message.content") from exc


def _parse_model_payload(raw_response) -> AIModelPayload:
    if isinstance(raw_response, dict):
        data = raw_response
    else:
        text = str(raw_response).strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
        data = json.loads(text)
    return AIModelPayload.model_validate(data)


def _safe_fallback_reason(exc: Exception, api_key: str) -> str:
    reason = str(exc)[:300]
    if api_key:
        reason = reason.replace(api_key, "[api-key-redacted]")
    return _LOCAL_PATH_PATTERN.sub("[local-path-redacted]", reason)


def _validate_model_payload(payload: AIModelPayload, ai_input: dict) -> None:
    formal_conclusion = ai_input["formal_conclusion"]
    if payload.conclusion != formal_conclusion:
        raise ValueError("模型试图改变正式结论")

    allowed_ids = {
        item["evidence_id"] for item in ai_input["evidence_records"] if item["evidence_id"]
    }
    cited_ids = {
        evidence_id
        for item in payload.counter_arguments + payload.next_experiments
        for evidence_id in item.evidence_ids
    }
    unknown = sorted(cited_ids - allowed_ids)
    if unknown:
        raise ValueError("模型引用了不存在的证据：" + "、".join(unknown))

    evidence_content = {
        "formal_conclusion": ai_input["formal_conclusion"],
        "evidence_dimensions": ai_input["evidence_dimensions"],
        "evidence_records": [
            {
                "dimension": item["dimension"],
                "severity": item["severity"],
                "claim": item["claim"],
                "metrics": item["metrics"],
                "explanation": item["explanation"],
            }
            for item in ai_input["evidence_records"]
        ],
    }
    allowed_numbers = set(_NUMBER_PATTERN.findall(json.dumps(evidence_content, ensure_ascii=False)))
    generated_text = " ".join(
        [payload.summary]
        + [item.text for item in payload.counter_arguments]
        + [item.text for item in payload.next_experiments]
    )
    invented = sorted(set(_NUMBER_PATTERN.findall(generated_text)) - allowed_numbers)
    if invented:
        raise ValueError("模型引入了证据中不存在的数字：" + "、".join(invented))


def _fallback_payload(ai_input: dict) -> AIModelPayload:
    records = ai_input["evidence_records"]
    priority = {"fail": 0, "warn": 1, "untested": 2, "pass": 3}
    ranked = sorted(records, key=lambda item: (priority.get(item["severity"], 4), item["evidence_id"]))
    selected = ranked[:3] or [
        {
            "evidence_id": "E-UNAVAILABLE",
            "dimension": "证据",
            "severity": "untested",
            "claim": "缺少结构化证据",
        }
    ]
    first = selected[0]
    summary = (
        f"正式结论保持为 {ai_input['formal_conclusion']}。"
        f"当前优先关注{first['dimension']}：{first['claim']}。"
    )
    counter_arguments = [
        AIAnalysisItem(
            text=f"需要说明如何排除“{item['claim']}”对研究结论的影响。",
            evidence_ids=[item["evidence_id"]],
        )
        for item in selected
    ]
    next_experiments = [
        AIAnalysisItem(
            text=f"针对{item['dimension']}补充可复现测试，并保留失败和未测试状态。",
            evidence_ids=[item["evidence_id"]],
        )
        for item in selected
    ]
    return AIModelPayload(
        conclusion=ai_input["formal_conclusion"],
        summary=summary,
        counter_arguments=counter_arguments,
        next_experiments=next_experiments,
    )


def generate_ai_analysis(
    factor_id: str,
    conclusion: str,
    evidence_dimensions: dict,
    records: Sequence,
    evidence_hash: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    environment: Mapping[str, str] | None = None,
    transport: Callable[[ModelConfig, dict], object] | None = None,
) -> AIAnalysisResult:
    """Generate a validated model analysis or a deterministic fallback."""
    ai_input = build_ai_input(
        factor_id, conclusion, evidence_dimensions, records, evidence_hash
    )
    env = os.environ if environment is None else environment
    config, config_error, settings = _resolve_model_config_details(
        env,
        provider=provider,
        model=model,
        base_url=base_url,
    )
    payload = None
    source = "rule_fallback"
    result_provider = settings.provider if settings is not None else "rule_fallback"
    result_model = settings.model if settings and settings.model else "deterministic-rules"
    fallback_reason = config_error

    if config is not None:
        result_provider = config.provider
        result_model = config.model
        try:
            raw_response = (transport or _http_transport)(
                config, _request_payload(config.model, ai_input)
            )
            payload = _parse_model_payload(raw_response)
            _validate_model_payload(payload, ai_input)
            source = "model"
            fallback_reason = None
        except Exception as exc:
            fallback_reason = _safe_fallback_reason(exc, config.api_key)

    if payload is None:
        payload = _fallback_payload(ai_input)

    result = AIAnalysisResult(
        **payload.model_dump(),
        source=source,
        provider=result_provider,
        model=result_model,
        prompt_version=PROMPT_VERSION,
        fallback_reason=fallback_reason,
        disclaimer=DISCLAIMER,
    )
    result.ai_analysis_hash = compute_ai_analysis_hash(
        evidence_hash,
        result.model_dump(exclude={"ai_analysis_hash", "fallback_reason", "disclaimer"}),
        model=result.model,
        prompt_version=PROMPT_VERSION,
    )
    return result
