import json
import re
import asyncio
from typing import Any, Dict
import logging
from .settings import load_ai_settings

logger = logging.getLogger("addon.ai_client")


class AIProviderTimeout(RuntimeError):
    """Raised when the configured AI provider does not answer in time."""


class AIProviderError(RuntimeError):
    """Raised when the configured AI provider fails."""


def _provider_kind(settings) -> str:
    preset = getattr(settings, "provider_preset", "auto")
    if preset and preset != "auto":
        return preset

    model = settings.model.lower()
    if model.startswith("z-ai/") or "glm" in model:
        return "glm"
    if "deepseek" in model:
        return "deepseek"
    return "generic"


def _chat_completion_kwargs(prompt: str, settings) -> dict[str, Any]:
    """Build provider-specific chat parameters without leaking provider quirks elsewhere."""

    kwargs: dict[str, Any] = {
        "model": settings.model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": settings.temperature,
        "max_tokens": settings.max_tokens,
        "stream": True,
    }

    provider = _provider_kind(settings)
    if provider == "glm":
        kwargs["top_p"] = 1
        chat_template_kwargs = {
            "enable_thinking": bool(getattr(settings, "enable_thinking", False)),
        }
        if chat_template_kwargs["enable_thinking"]:
            chat_template_kwargs["clear_thinking"] = False
        kwargs["extra_body"] = {
            "chat_template_kwargs": chat_template_kwargs,
        }
    elif provider == "deepseek":
        kwargs["extra_body"] = {"chat_template_kwargs": {"thinking": False}}

    return kwargs


def _delta_content(delta: Any) -> str | None:
    if isinstance(delta, dict):
        return delta.get("content")
    return getattr(delta, "content", None)


def _extract_json_object(content: Any) -> Dict[str, Any]:
    """Parse a JSON object from common chat-completion response shapes."""
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        raise ValueError("AI response content is not text or JSON")

    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def _entities_from_prompt(prompt: str) -> list[dict[str, Any]]:
    match = re.search(
        r"Entities and capabilities:\s*(\[.*?\])\s*Capability/service contract:",
        prompt,
        flags=re.S,
    )
    if not match:
        return []
    try:
        parsed = json.loads(match.group(1))
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


FALLBACK_PALETTE = (
    [255, 0, 120],
    [0, 180, 255],
    [140, 0, 255],
    [0, 255, 120],
    [255, 180, 0],
)

HORROR_PALETTE = (
    [150, 0, 25],
    [70, 0, 120],
    [15, 0, 80],
)


def _fallback_style(intent: str) -> str:
    text = intent.lower()
    if any(phrase in text for phrase in ("full brightness", "maximum brightness", "max brightness", "100%", "brightest")):
        return "full_brightness"
    if any(word in text for word in ("party", "dance", "club", "disco", "rainbow")):
        return "party"
    if any(word in text for word in ("horror", "scary", "spooky", "haunted", "creepy")):
        return "horror"
    if any(word in text for word in ("office", "work", "focus", "study", "reading")):
        return "office"
    if any(word in text for word in ("movie", "cozy", "cosy", "night", "relax", "dim", "sleep")):
        return "cozy"
    return "general"


def _wants_motion(intent: str, style: str) -> bool:
    text = intent.lower()
    return style in {"party", "horror"} or any(
        word in text
        for word in ("smooth", "fade", "gradual", "transition", "pulse", "loop", "changing", "animate", "animated")
    )


def _fallback_kelvin(entity: dict[str, Any], target: int) -> int:
    attrs = ((entity.get("state") or {}).get("attributes") or {})
    minimum = attrs.get("min_color_temp_kelvin") or 2000
    maximum = attrs.get("max_color_temp_kelvin") or 6500
    try:
        minimum = int(minimum)
        maximum = int(maximum)
    except (TypeError, ValueError):
        minimum, maximum = 2000, 6500
    return max(minimum, min(maximum, int(target)))


def _offline_scene(prompt: str) -> Dict[str, Any]:
    """Deterministic local fallback used when no API key is configured."""
    entities = _entities_from_prompt(prompt)
    room_match = re.search(r"Room context:\s*(.*?)\s*Entities and capabilities:", prompt, flags=re.S)
    room = room_match.group(1).strip() if room_match else "unspecified"
    intent_match = re.search(r"User intent:\s*(.*?)\s*Constraints:", prompt, flags=re.S)
    intent = intent_match.group(1).strip() if intent_match else "Create a scene"
    style = _fallback_style(intent)
    wants_motion = _wants_motion(intent, style)

    actions = []
    entity_map = {}
    for index, entity in enumerate(entities):
        entity_id = entity.get("entity_id", "")
        domain = entity.get("domain") or entity_id.split(".", 1)[0]
        caps = set(entity.get("capabilities", []))
        state = entity.get("state", {})
        data: Dict[str, Any] = {}
        timing: Dict[str, int] = {}
        service = "turn_on"

        if domain == "light":
            if wants_motion and style in {"party", "horror"} and "rgb_color" in caps:
                palette = FALLBACK_PALETTE if style == "party" else HORROR_PALETTE
                if "brightness" in caps:
                    data["brightness"] = 185 if style == "party" else 55
                for phase in range(min(3, len(palette))):
                    phase_data = dict(data)
                    phase_data["rgb_color"] = palette[(index + phase) % len(palette)]
                    phase_data["transition"] = 1.2
                    entity_map[entity_id] = {
                        "entity_id": entity_id,
                        "domain": domain,
                        "capabilities": sorted(caps),
                    }
                    actions.append(
                        {
                            "entity_id": entity_id,
                            "domain": domain,
                            "service": service,
                            "data": phase_data,
                            "rationale": "Local fallback color phase based on advertised RGB capability",
                            "priority": max(0, 100 - index * 10 - phase),
                            "delay_ms": phase * 1200,
                            "duration_ms": 1200,
                        }
                    )
                continue
            if style == "full_brightness":
                if "brightness" in caps:
                    data["brightness"] = 255
                if "color_temp" in caps:
                    data["color_temp_kelvin"] = _fallback_kelvin(entity, 6500)
            elif style == "party" and "rgb_color" in caps:
                if "brightness" in caps:
                    data["brightness"] = 185
                data["rgb_color"] = FALLBACK_PALETTE[index % len(FALLBACK_PALETTE)]
            elif style == "horror" and "rgb_color" in caps:
                if "brightness" in caps:
                    data["brightness"] = 55
                data["rgb_color"] = [150, 0, 25]
            elif style == "office":
                if "brightness" in caps:
                    data["brightness"] = 190
                if "color_temp" in caps:
                    data["color_temp_kelvin"] = _fallback_kelvin(entity, 4200)
            elif style == "cozy":
                if "brightness" in caps:
                    data["brightness"] = 64
                if "color_temp" in caps:
                    data["color_temp_kelvin"] = _fallback_kelvin(entity, 2700)
            elif "brightness" in caps:
                data["brightness"] = 120
            if wants_motion:
                data["transition"] = 5
                timing["duration_ms"] = 5000
        elif domain == "media_player":
            if "volume" in caps:
                data["volume_level"] = 0.35
                service = "volume_set"
            else:
                service = "turn_on"
        elif domain in {"switch", "fan"}:
            service = "turn_on"
        else:
            continue

        entity_map[entity_id] = {
            "entity_id": entity_id,
            "domain": domain,
            "capabilities": sorted(caps),
        }
        action = {
            "entity_id": entity_id,
            "domain": domain,
            "service": service,
            "data": data,
            "rationale": "Safe local fallback action based on advertised capabilities",
            "priority": max(0, 100 - index),
        }
        action.update(timing)
        actions.append(action)

    scene = {
        "scene_name": "AI Scene Draft",
        "description": "Local deterministic scene draft generated without an API key.",
        "intent": intent,
        "target_room": room,
        "actions": actions,
        "confidence": 0.45 if actions else 0.2,
        "warnings": ["No API key configured; generated a conservative local fallback."],
        "assumptions": ["Only advertised entities and capabilities were used."],
        "entity_map": entity_map,
    }
    if wants_motion and style in {"party", "horror"}:
        scene["automation"] = {
            "mode": "sequence",
            "summary": "Short local fallback color choreography.",
            "repeat": 2,
            "interval_ms": 500,
        }
    return scene


async def _call_ai_provider(prompt: str, settings) -> Dict[str, Any]:
    try:
        from openai import APITimeoutError, AsyncOpenAI

        client = AsyncOpenAI(
            base_url=settings.base_url,
            api_key=settings.api_key,
            timeout=settings.request_timeout,
            max_retries=0,
        )
        stream = await client.chat.completions.create(**_chat_completion_kwargs(prompt, settings))
        chunks: list[str] = []
        async for chunk in stream:
            if not getattr(chunk, "choices", None):
                continue
            delta = getattr(chunk.choices[0], "delta", None)
            content = _delta_content(delta)
            if content:
                chunks.append(content)
    except Exception as exc:
        if exc.__class__.__name__ == "APITimeoutError":
            raise AIProviderTimeout(f"AI provider timed out after {settings.request_timeout:g}s") from exc
        raise AIProviderError(f"AI provider request failed: {exc.__class__.__name__}") from exc

    content = "".join(chunks).strip()
    if not content:
        raise AIProviderError("AI provider returned empty content")
    return _extract_json_object(content)


async def call_ai_model(prompt: str) -> Dict[str, Any]:
    """Call the configured OpenAI-compatible model with clean fallback handling."""

    settings = load_ai_settings()
    if not settings.has_api_key:
        logger.warning("No API key found; returning deterministic local fallback")
        return _offline_scene(prompt)

    try:
        return await asyncio.wait_for(
            _call_ai_provider(prompt, settings),
            timeout=settings.request_timeout + 5,
        )
    except asyncio.TimeoutError as exc:
        error = AIProviderTimeout(f"AI provider timed out after {settings.request_timeout:g}s")
        if settings.fallback_on_error:
            logger.warning("%s; using local fallback", error)
            scene = _offline_scene(prompt)
            scene["warnings"].append(str(error))
            return scene
        raise error from exc
    except (AIProviderTimeout, AIProviderError, ValueError) as exc:
        if settings.fallback_on_error:
            logger.warning("%s; using local fallback", exc)
            scene = _offline_scene(prompt)
            scene["warnings"].append(str(exc))
            return scene
        raise
