"""Home Assistant API helpers for add-on-side discovery."""

from __future__ import annotations

import os
import asyncio
from dataclasses import dataclass
from typing import Any

SUPPORTED_DOMAINS = {"light", "switch", "fan", "media_player", "climate", "cover"}
DEFAULT_HA_API_URL = "http://supervisor/core/api"


@dataclass(frozen=True)
class HAApiSettings:
    base_url: str
    token: str

    @property
    def configured(self) -> bool:
        return bool(self.token)


def load_ha_api_settings() -> HAApiSettings:
    return HAApiSettings(
        base_url=os.getenv("HA_API_URL", DEFAULT_HA_API_URL).rstrip("/"),
        token=os.getenv("SUPERVISOR_TOKEN", ""),
    )


def _capabilities(domain: str, attrs: dict[str, Any]) -> list[str]:
    caps = {"on_off"} if domain in {"light", "switch", "fan", "media_player", "cover"} else set()
    supported_color_modes = set(attrs.get("supported_color_modes") or [])

    if domain == "light":
        if "brightness" in attrs or "brightness" in supported_color_modes:
            caps.add("brightness")
        if "color_temp" in attrs or "color_temp" in supported_color_modes or "min_color_temp_kelvin" in attrs:
            caps.add("color_temp")
        if "rgb_color" in attrs or {"rgb", "hs"} & supported_color_modes:
            caps.add("rgb_color")
        if "xy_color" in attrs or "xy" in supported_color_modes:
            caps.add("xy_color")
        if attrs.get("effect_list"):
            caps.add("effect")
    elif domain == "media_player":
        caps.add("media_control")
        if "volume_level" in attrs:
            caps.add("volume")
        if "is_volume_muted" in attrs:
            caps.add("mute")
        if attrs.get("source_list"):
            caps.add("source")
    elif domain == "fan":
        if "percentage" in attrs or attrs.get("percentage_step"):
            caps.add("percentage")
        if "oscillating" in attrs:
            caps.add("oscillate")
    elif domain == "climate":
        if "temperature" in attrs or "target_temp" in attrs:
            caps.add("target_temp")
        if attrs.get("hvac_modes"):
            caps.add("mode")

    return sorted(caps)


def _room_for_state(state: dict[str, Any]) -> str | None:
    attrs = state.get("attributes") or {}
    for key in ("area_id", "room", "area", "device_class"):
        value = attrs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _normalize_state(state: dict[str, Any]) -> dict[str, Any] | None:
    entity_id = state.get("entity_id")
    if not isinstance(entity_id, str) or "." not in entity_id:
        return None
    domain = entity_id.split(".", 1)[0]
    if domain not in SUPPORTED_DOMAINS:
        return None
    attrs = state.get("attributes") or {}
    if not isinstance(attrs, dict):
        attrs = {}

    return {
        "entity_id": entity_id,
        "domain": domain,
        "capabilities": _capabilities(domain, attrs),
        "state": {
            "value": state.get("state", "unknown"),
            "attributes": attrs,
        },
        "room": _room_for_state(state),
        "name": attrs.get("friendly_name") or entity_id,
    }


async def _get_json(path: str, settings: HAApiSettings) -> Any:
    import httpx

    headers = {"Authorization": f"Bearer {settings.token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.get(f"{settings.base_url}{path}", headers=headers)
        response.raise_for_status()
        return response.json()


async def _try_get_json(path: str, settings: HAApiSettings) -> Any:
    try:
        return await _get_json(path, settings)
    except Exception:
        return None


async def _load_registries(settings: HAApiSettings) -> tuple[dict[str, str], dict[str, str]]:
    areas_raw, entities_raw, devices_raw = await asyncio.gather(
        _try_get_json("/config/area_registry/list", settings),
        _try_get_json("/config/entity_registry/list", settings),
        _try_get_json("/config/device_registry/list", settings),
    )
    area_names = {
        area.get("area_id"): area.get("name", area.get("area_id"))
        for area in areas_raw or []
        if isinstance(area, dict) and area.get("area_id")
    }
    device_areas = {
        device.get("id"): device.get("area_id")
        for device in devices_raw or []
        if isinstance(device, dict) and device.get("id") and device.get("area_id")
    }
    entity_areas: dict[str, str] = {}
    for entity in entities_raw or []:
        if not isinstance(entity, dict) or not entity.get("entity_id"):
            continue
        area_id = entity.get("area_id") or device_areas.get(entity.get("device_id"))
        if area_id:
            entity_areas[entity["entity_id"]] = area_names.get(area_id, area_id)
    return area_names, entity_areas


async def list_entities(room_id: str | None = None) -> list[dict[str, Any]]:
    settings = load_ha_api_settings()
    if not settings.configured:
        return []

    states, (_, entity_areas) = await asyncio.gather(
        _get_json("/states", settings),
        _load_registries(settings),
    )
    entities = [_normalize_state(state) for state in states if isinstance(state, dict)]
    filtered = [entity for entity in entities if entity]
    for entity in filtered:
        registry_room = entity_areas.get(entity["entity_id"])
        if registry_room:
            entity["room"] = registry_room
    if room_id:
        room_key = room_id.strip().lower()
        filtered = [
            entity for entity in filtered
            if (entity.get("room") or "").lower() == room_key
            or room_key in (entity.get("entity_id") or "").lower()
            or room_key in (entity.get("name") or "").lower()
        ]
    return filtered


async def list_areas() -> list[dict[str, str]]:
    settings = load_ha_api_settings()
    if settings.configured:
        area_names, _ = await _load_registries(settings)
        if area_names:
            return [{"area_id": area_id, "name": name} for area_id, name in sorted(area_names.items())]

    entities = await list_entities()
    rooms = sorted({entity.get("room") for entity in entities if entity.get("room")})
    return [{"area_id": room, "name": room.replace("_", " ").title()} for room in rooms]


async def discovery_status() -> dict[str, Any]:
    settings = load_ha_api_settings()
    if not settings.configured:
        return {
            "ok": False,
            "message": "SUPERVISOR_TOKEN is not available, so Syn cannot read Home Assistant entities.",
            "entity_count": 0,
            "area_count": 0,
            "base_url": settings.base_url,
        }

    try:
        areas, entities = await asyncio.gather(list_areas(), list_entities())
    except Exception as exc:
        return {
            "ok": False,
            "message": f"Home Assistant discovery failed: {exc.__class__.__name__}",
            "entity_count": 0,
            "area_count": 0,
            "base_url": settings.base_url,
        }

    return {
        "ok": True,
        "message": "Home Assistant discovery is working.",
        "entity_count": len(entities),
        "area_count": len(areas),
        "base_url": settings.base_url,
        "domains": sorted({entity["domain"] for entity in entities}),
    }
