"""Runtime settings loaded from Home Assistant add-on options."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_OPTIONS_PATH = Path("/data/options.json")
DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "deepseek-ai/deepseek-v4-flash"
DEFAULT_TEMPERATURE = 0.0
DEFAULT_REQUEST_TIMEOUT = 30.0
DEFAULT_MAX_TOKENS = 1800


@dataclass(frozen=True)
class AISettings:
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    temperature: float = DEFAULT_TEMPERATURE
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT
    max_tokens: int = DEFAULT_MAX_TOKENS
    fallback_on_error: bool = True
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
    model = (os.getenv("AI_MODEL") or str(options.get("model") or DEFAULT_MODEL)).strip()
    temperature = _coerce_temperature(os.getenv("AI_TEMPERATURE", options.get("temperature", DEFAULT_TEMPERATURE)))
    request_timeout = _coerce_float(
        os.getenv("AI_REQUEST_TIMEOUT", options.get("request_timeout", DEFAULT_REQUEST_TIMEOUT)),
        DEFAULT_REQUEST_TIMEOUT,
        5.0,
        120.0,
    )
    max_tokens = _coerce_int(
        os.getenv("AI_MAX_TOKENS", options.get("max_tokens", DEFAULT_MAX_TOKENS)),
        DEFAULT_MAX_TOKENS,
        256,
        8192,
    )
    fallback_on_error = _coerce_bool(
        os.getenv("AI_FALLBACK_ON_ERROR", options.get("fallback_on_error", True)),
        default=True,
    )

    return AISettings(
        api_key=api_key,
        base_url=base_url.rstrip("/") or DEFAULT_BASE_URL,
        model=model or DEFAULT_MODEL,
        temperature=temperature,
        request_timeout=request_timeout,
        max_tokens=max_tokens,
        fallback_on_error=fallback_on_error,
        options_path=resolved_options_path,
    )


def mask_secret(value: str) -> str:
    """Return a safe display form for secrets."""

    if not value:
        return "not configured"
    if len(value) <= 8:
        return "configured"
    return f"{value[:4]}...{value[-4:]}"
