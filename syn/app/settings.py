"""Runtime settings loaded from Home Assistant add-on options."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_OPTIONS_PATH = Path("/data/options.json")
DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "meta/llama-3.2-3b-instruct"
LEGACY_DEFAULT_MODELS = {"deepseek-ai/deepseek-v4-pro", "deepseek-ai/deepseek-v4-flash", "z-ai/glm-5.1"}
DEFAULT_TEMPERATURE = 0.2
DEFAULT_REQUEST_TIMEOUT = 90.0
DEFAULT_MAX_TOKENS = 4096
DEFAULT_PROVIDER_PRESET = "auto"
DEFAULT_ENABLE_THINKING = False
LEGACY_DEFAULT_TEMPERATURES = {0, 0.0, "0", "0.0"}
LEGACY_DEFAULT_TIMEOUTS = {30, 30.0, "30", "30.0"}
LEGACY_DEFAULT_MAX_TOKENS = {1800, "1800"}


@dataclass(frozen=True)
class AISettings:
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    temperature: float = DEFAULT_TEMPERATURE
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT
    max_tokens: int = DEFAULT_MAX_TOKENS
    fallback_on_error: bool = True
    provider_preset: str = DEFAULT_PROVIDER_PRESET
    enable_thinking: bool = DEFAULT_ENABLE_THINKING
    options_path: Path = DEFAULT_OPTIONS_PATH

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key.strip())


def _read_options(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as options_file:
        data = json.load(options_file)
    return data if isinstance(data, dict) else {}


def _coerce_temperature(value: Any) -> float:
    try:
        temperature = float(value)
    except (TypeError, ValueError):
        return DEFAULT_TEMPERATURE
    return min(1.0, max(0.0, temperature))


def _coerce_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, number))


def _coerce_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, number))


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if value is None:
        return default
    return bool(value)


def _normalize_model(model: str, env_model: str | None = None) -> str:
    if env_model:
        return model or DEFAULT_MODEL
    return DEFAULT_MODEL if model in LEGACY_DEFAULT_MODELS else model or DEFAULT_MODEL


def _normalize_provider_preset(value: str) -> str:
    preset = (value or DEFAULT_PROVIDER_PRESET).strip().lower()
    return preset if preset in {"auto", "glm", "deepseek", "generic"} else DEFAULT_PROVIDER_PRESET


def load_ai_settings(options_path: Path | None = None) -> AISettings:
    """Load AI settings from env overrides first, then add-on options."""

    resolved_options_path = options_path or Path(os.getenv("ADDON_OPTIONS_PATH", str(DEFAULT_OPTIONS_PATH)))
    options = _read_options(resolved_options_path)
    api_key = (
        os.getenv("OPENAI_API_KEY")
        or os.getenv("NVIDIA_API_KEY")
        or str(options.get("api_key") or "")
    ).strip()
    base_url = (os.getenv("AI_BASE_URL") or str(options.get("base_url") or DEFAULT_BASE_URL)).strip()
    env_model = os.getenv("AI_MODEL")
    model = _normalize_model((env_model or str(options.get("model") or DEFAULT_MODEL)).strip(), env_model)
    temperature_source = os.getenv("AI_TEMPERATURE", options.get("temperature", DEFAULT_TEMPERATURE))
    if os.getenv("AI_TEMPERATURE") is None and temperature_source in LEGACY_DEFAULT_TEMPERATURES:
        temperature_source = DEFAULT_TEMPERATURE
    temperature = _coerce_temperature(temperature_source)
    timeout_source = os.getenv("AI_REQUEST_TIMEOUT", options.get("request_timeout", DEFAULT_REQUEST_TIMEOUT))
    if os.getenv("AI_REQUEST_TIMEOUT") is None and timeout_source in LEGACY_DEFAULT_TIMEOUTS:
        timeout_source = DEFAULT_REQUEST_TIMEOUT
    request_timeout = _coerce_float(
        timeout_source,
        DEFAULT_REQUEST_TIMEOUT,
        5.0,
        120.0,
    )
    max_tokens_source = os.getenv("AI_MAX_TOKENS", options.get("max_tokens", DEFAULT_MAX_TOKENS))
    if os.getenv("AI_MAX_TOKENS") is None and max_tokens_source in LEGACY_DEFAULT_MAX_TOKENS:
        max_tokens_source = DEFAULT_MAX_TOKENS
    max_tokens = _coerce_int(
        max_tokens_source,
        DEFAULT_MAX_TOKENS,
        256,
        8192,
    )
    fallback_on_error = _coerce_bool(
        os.getenv("AI_FALLBACK_ON_ERROR", options.get("fallback_on_error", True)),
        default=True,
    )
    provider_preset = _normalize_provider_preset(
        os.getenv("AI_PROVIDER_PRESET")
        or str(options.get("provider_preset") or DEFAULT_PROVIDER_PRESET)
    )
    enable_thinking = _coerce_bool(
        os.getenv("AI_ENABLE_THINKING", options.get("enable_thinking", DEFAULT_ENABLE_THINKING)),
        default=DEFAULT_ENABLE_THINKING,
    )

    return AISettings(
        api_key=api_key,
        base_url=base_url.rstrip("/") or DEFAULT_BASE_URL,
        model=model or DEFAULT_MODEL,
        temperature=temperature,
        request_timeout=request_timeout,
        max_tokens=max_tokens,
        fallback_on_error=fallback_on_error,
        provider_preset=provider_preset,
        enable_thinking=enable_thinking,
        options_path=resolved_options_path,
    )


def mask_secret(value: str) -> str:
    """Return a safe display form for secrets."""

    if not value:
        return "not configured"
    if len(value) <= 8:
        return "configured"
    return f"{value[:4]}...{value[-4:]}"
