"""Runtime settings loaded from Home Assistant add-on options."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_OPTIONS_PATH = Path("/data/options.json")
DEFAULT_MODEL = "deepseek-ai/deepseek-v4-pro"
DEFAULT_TEMPERATURE = 0.0


@dataclass(frozen=True)
class AISettings:
    api_key: str = ""
    model: str = DEFAULT_MODEL
    temperature: float = DEFAULT_TEMPERATURE
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


def load_ai_settings(options_path: Path | None = None) -> AISettings:
    """Load AI settings from env overrides first, then add-on options."""

    resolved_options_path = options_path or Path(os.getenv("ADDON_OPTIONS_PATH", str(DEFAULT_OPTIONS_PATH)))
    options = _read_options(resolved_options_path)
    api_key = (
        os.getenv("OPENAI_API_KEY")
        or os.getenv("NVIDIA_API_KEY")
        or str(options.get("api_key") or "")
    ).strip()
    model = (os.getenv("AI_MODEL") or str(options.get("model") or DEFAULT_MODEL)).strip()
    temperature = _coerce_temperature(os.getenv("AI_TEMPERATURE", options.get("temperature", DEFAULT_TEMPERATURE)))

    return AISettings(
        api_key=api_key,
        model=model or DEFAULT_MODEL,
        temperature=temperature,
        options_path=resolved_options_path,
    )


def mask_secret(value: str) -> str:
    """Return a safe display form for secrets."""

    if not value:
        return "not configured"
    if len(value) <= 8:
        return "configured"
    return f"{value[:4]}...{value[-4:]}"
