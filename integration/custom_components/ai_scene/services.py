import logging
from .discovery import discover_room_entities
from .scene_executor import execute_scene
from typing import Any

try:
    from homeassistant.core import HomeAssistant, ServiceCall
except ModuleNotFoundError:  # Allows local addon tests without Home Assistant installed.
    HomeAssistant = Any
    ServiceCall = Any

_LOGGER = logging.getLogger(__name__)


async def call_addon_generate(hass: HomeAssistant, payload: dict) -> dict:
    """Call the add-on HTTP API to generate a scene."""
    import httpx

    addon_url = hass.data.get("ai_scene_addon_url") or "http://localhost:8000"
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{addon_url}/generate_scene", json=payload, timeout=60)
        r.raise_for_status()
        return r.json()


async def call_addon_preview(hass: HomeAssistant, payload: dict) -> dict:
    """Call the add-on HTTP API to preview a scene."""
    import httpx

    addon_url = hass.data.get("ai_scene_addon_url") or "http://localhost:8000"
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{addon_url}/preview_scene", json=payload, timeout=60)
        r.raise_for_status()
        return r.json()


async def call_addon_commit(hass: HomeAssistant, scene_id: str) -> dict:
    import httpx

    addon_url = hass.data.get("ai_scene_addon_url") or "http://localhost:8000"
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{addon_url}/commit_scene/{scene_id}", timeout=20)
        r.raise_for_status()
        return r.json()


async def call_addon_scene_action(hass: HomeAssistant, action: str, scene_id: str) -> dict:
    import httpx

    addon_url = hass.data.get("ai_scene_addon_url") or "http://localhost:8000"
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{addon_url}/{action}/{scene_id}", timeout=90)
        r.raise_for_status()
        return r.json()


async def build_generation_payload(hass: HomeAssistant, call: ServiceCall) -> dict:
    room_id = call.data.get("room_id")
    return {
        "user_prompt": call.data.get("user_prompt") or call.data.get("prompt"),
        "room_id": room_id,
        "constraints": call.data.get("constraints") or {},
        "entities": call.data.get("entities") or await discover_room_entities(hass, room_id),
    }


async def generate_service(hass: HomeAssistant, call: ServiceCall) -> dict:
    payload = await build_generation_payload(hass, call)
    result = await call_addon_generate(hass, payload)
    hass.data.setdefault("ai_scene", {})["last_generated"] = result
    return result


async def preview_service(hass: HomeAssistant, call: ServiceCall) -> dict:
    _LOGGER.info("Preview called: %s", call.data)
    payload = await build_generation_payload(hass, call)
    result = await call_addon_preview(hass, payload)
    hass.data.setdefault("ai_scene", {})["last_preview"] = result
    return result


async def commit_service(hass: HomeAssistant, call: ServiceCall) -> dict:
    _LOGGER.info("Commit called: %s", call.data)
    scene_id = call.data.get("scene_id")
    if not scene_id:
        raise ValueError("scene_id is required")
    result = await call_addon_commit(hass, scene_id)
    hass.data.setdefault("ai_scene", {})["last_commit"] = result
    return result


async def execute_service(hass: HomeAssistant, call: ServiceCall) -> dict:
    scene = call.data.get("scene")
    if not scene:
        last = hass.data.get("ai_scene", {}).get("last_generated") or {}
        scene = last.get("scene")
    if not scene:
        raise ValueError("scene payload or a generated scene is required")
    result = await execute_scene(hass, scene)
    hass.data.setdefault("ai_scene", {})["last_execution"] = result
    return result


async def start_scene_service(hass: HomeAssistant, call: ServiceCall) -> dict:
    scene_id = call.data.get("scene_id")
    if not scene_id:
        raise ValueError("scene_id is required")
    result = await call_addon_scene_action(hass, "start_scene", scene_id)
    hass.data.setdefault("ai_scene", {})["last_start"] = result
    return result


async def stop_scene_service(hass: HomeAssistant, call: ServiceCall) -> dict:
    scene_id = call.data.get("scene_id")
    if not scene_id:
        raise ValueError("scene_id is required")
    result = await call_addon_scene_action(hass, "stop_scene", scene_id)
    hass.data.setdefault("ai_scene", {})["last_stop"] = result
    return result


async def deactivate_scene_service(hass: HomeAssistant, call: ServiceCall) -> dict:
    scene_id = call.data.get("scene_id")
    if not scene_id:
        raise ValueError("scene_id is required")
    result = await call_addon_scene_action(hass, "deactivate_scene", scene_id)
    hass.data.setdefault("ai_scene", {})["last_deactivate"] = result
    return result
