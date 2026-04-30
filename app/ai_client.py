import os
import json
import re
from typing import Any, Dict
import logging

logger = logging.getLogger("addon.ai_client")


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


async def call_ai_model(prompt: str) -> Dict[str, Any]:
    """Call NVIDIA-hosted OpenAI-compatible model. Returns parsed JSON.

    If no API key is configured, returns a sample response for local testing.
    """
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("NVIDIA_API_KEY")
    if not api_key:
        logger.warning("No API key found; returning deterministic local fallback")
        return _offline_scene(prompt)

    # Use the OpenAI-compatible client
    try:
        from openai import OpenAI

        client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=api_key)
        # We call a single-turn chat completion and expect JSON in the assistant content
        response = client.chat.completions.create(
            model="deepseek-ai/deepseek-v4-pro",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=4096,
            extra_body={"chat_template_kwargs": {"thinking": False}},
        )

        # response may stream; attempt to extract text
        # For safety, try to access choices[0].message['content']
        if hasattr(response, "choices") and response.choices:
            content = None
            # some clients return message, some delta; handle common shapes
            first = response.choices[0]
            if getattr(first, "message", None):
                message = first.message
                content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
            elif getattr(first, "delta", None):
                delta = first.delta
                content = delta.get("content") if isinstance(delta, dict) else getattr(delta, "content", None)
            else:
                # fallback stringify
                content = str(first)

            return _extract_json_object(content)
        else:
            raise RuntimeError("Unexpected model response shape")
    except Exception as exc:
        logger.exception("AI client error")
        raise
