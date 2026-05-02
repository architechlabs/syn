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


def _offline_scene(prompt: str) -> Dict[str, Any]:
    """Deterministic local fallback used when no API key is configured."""
    entities = _entities_from_prompt(prompt)
    room_match = re.search(r"Room context:\s*(.*?)\s*Entities and capabilities:", prompt, flags=re.S)
    room = room_match.group(1).strip() if room_match else "unspecified"
    intent_match = re.search(r"User intent:\s*(.*?)\s*Constraints:", prompt, flags=re.S)
    intent = intent_match.group(1).strip() if intent_match else "Create a scene"

    actions = []
    entity_map = {}
    for index, entity in enumerate(entities):
        entity_id = entity.get("entity_id", "")
        domain = entity.get("domain") or entity_id.split(".", 1)[0]
        caps = set(entity.get("capabilities", []))
        state = entity.get("state", {})
        data: Dict[str, Any] = {}
        service = "turn_on"

        if domain == "light":
            if "brightness" in caps:
                data["brightness"] = 120
            if "color_temp" in caps:
                data["color_temp"] = 370
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
        actions.append(
            {
                "entity_id": entity_id,
                "domain": domain,
                "service": service,
                "data": data,
                "rationale": "Safe local fallback action based on advertised capabilities",
                "priority": max(0, 100 - index),
            }
        )

    return {
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


async def _call_ai_provider(prompt: str, settings) -> Dict[str, Any]:
    try:
        from openai import APITimeoutError, AsyncOpenAI

        client = AsyncOpenAI(
            base_url=settings.base_url,
            api_key=settings.api_key,
            timeout=settings.request_timeout,
            max_retries=0,
        )
        stream = await client.chat.completions.create(
            model=settings.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
            extra_body={"chat_template_kwargs": {"thinking": False}},
            stream=True,
        )
        chunks: list[str] = []
        async for chunk in stream:
            if not getattr(chunk, "choices", None):
                continue
            delta = getattr(chunk.choices[0], "delta", None)
            content = delta.get("content") if isinstance(delta, dict) else getattr(delta, "content", None)
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
