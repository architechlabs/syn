"""Zero-effort entity selection helpers for Syn scene planning."""

from __future__ import annotations

import re
from typing import Any


LIGHTING_WORDS = {
    "light",
    "lights",
    "brightness",
    "bright",
    "dim",
    "color",
    "colour",
    "rgb",
    "scene",
    "party",
    "horror",
    "movie",
    "cozy",
    "focus",
    "office",
    "wake",
    "sleep",
}
MEDIA_WORDS = {"movie", "tv", "music", "audio", "volume", "speaker", "media"}
FAN_WORDS = {"fan", "air", "breeze", "cool", "ventilate"}
ALL_WORDS = {"all", "everything", "whole", "entire", "everywhere"}
SAFE_DOMAINS = {"light", "switch", "fan", "media_player"}


def _tokens(value: str | None) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9_]+", (value or "").lower()) if len(token) >= 2}


def _haystack(entity: dict[str, Any]) -> str:
    return " ".join(
        str(part or "")
        for part in (
            entity.get("entity_id"),
            entity.get("name"),
            entity.get("room"),
            entity.get("domain"),
            " ".join(entity.get("capabilities") or []),
        )
    ).lower()


def _entity_score(entity: dict[str, Any], prompt_tokens: set[str], room_tokens: set[str]) -> int:
    domain = entity.get("domain")
    if domain not in SAFE_DOMAINS:
        return -10_000

    score = 0
    caps = set(entity.get("capabilities") or [])
    haystack = _haystack(entity)

    if domain == "light":
        score += 100 if prompt_tokens & LIGHTING_WORDS else 70
        if "brightness" in caps:
            score += 16
        if {"rgb_color", "effect"} & caps:
            score += 14
        if "color_temp" in caps:
            score += 8
    elif domain == "media_player":
        score += 85 if prompt_tokens & MEDIA_WORDS else 8
    elif domain == "fan":
        score += 85 if prompt_tokens & FAN_WORDS else 6
    elif domain == "switch":
        score += 30

    for token in prompt_tokens | room_tokens:
        if token and token in haystack:
            score += 18
    if entity.get("room") and room_tokens and any(token in str(entity.get("room")).lower() for token in room_tokens):
        score += 40
    if str(entity.get("source") or "") == "storage":
        score -= 4
    return score


def auto_select_entities(
    entities: list[dict[str, Any]],
    prompt: str | None = None,
    room_id: str | None = None,
    max_entities: int | None = None,
) -> list[dict[str, Any]]:
    """Choose a small, safe set of likely scene devices when the user selects none.

    The add-on can discover many entities. This function keeps the zero-click
    path useful without touching every device in the house by default.
    """

    prompt_tokens = _tokens(prompt)
    room_tokens = _tokens(room_id)
    wants_all = bool(prompt_tokens & ALL_WORDS)
    default_limit = 24 if wants_all else 8
    limit = max_entities or default_limit

    candidates = [
        (entity, _entity_score(entity, prompt_tokens, room_tokens))
        for entity in entities
        if isinstance(entity, dict)
    ]
    candidates = [(entity, score) for entity, score in candidates if score > 0]
    candidates.sort(
        key=lambda item: (
            item[1],
            1 if item[0].get("domain") == "light" else 0,
            str(item[0].get("room") or ""),
            str(item[0].get("name") or item[0].get("entity_id") or ""),
        ),
        reverse=True,
    )

    selected = [entity for entity, _ in candidates[:limit]]
    if selected:
        return selected

    # Last resort: keep it conservative and controllable.
    return [
        entity for entity in entities
        if isinstance(entity, dict) and entity.get("domain") in SAFE_DOMAINS
    ][: min(limit, 4)]
