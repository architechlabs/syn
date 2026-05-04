"""Home Assistant API helpers for add-on-side discovery."""

from __future__ import annotations

import os
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from .settings import DEFAULT_OPTIONS_PATH, _read_options, mask_secret

SUPPORTED_DOMAINS = {"light", "switch", "fan", "media_player", "climate", "cover"}
DEFAULT_HA_API_URL = "http://supervisor/core/api"
DEFAULT_MANUAL_HA_API_URL = "http://homeassistant:8123/api"
DEFAULT_HA_CONFIG_PATH = Path("/config")
MAX_DELAY_MS = 30_000
MAX_DURATION_MS = 300_000
MAX_INTERVAL_MS = 10_000
MAX_REPEAT = 12


@dataclass(frozen=True)
class HAApiSettings:
    base_url: str
    token: str
    source: str

    @property
    def configured(self) -> bool:
        return bool(self.token)

    @property
    def masked_token(self) -> str:
        return mask_secret(self.token)


def load_ha_api_settings() -> HAApiSettings:
    options = _read_options(Path(os.getenv("ADDON_OPTIONS_PATH", str(DEFAULT_OPTIONS_PATH))))
    supervisor_token = os.getenv("SUPERVISOR_TOKEN", "").strip()
    manual_token = (
        os.getenv("HA_TOKEN")
        or os.getenv("HOME_ASSISTANT_TOKEN")
        or str(options.get("ha_token") or "")
    ).strip()
    token = manual_token or supervisor_token
    source = "manual" if manual_token else "supervisor" if supervisor_token else "missing"
    configured_url = (os.getenv("HA_API_URL") or str(options.get("ha_url") or "")).strip()
    if manual_token and configured_url.rstrip("/") == DEFAULT_HA_API_URL:
        base_url = DEFAULT_MANUAL_HA_API_URL
    elif configured_url:
        base_url = configured_url.rstrip("/")
    elif manual_token:
        base_url = DEFAULT_MANUAL_HA_API_URL
    else:
        base_url = DEFAULT_HA_API_URL
    return HAApiSettings(
        base_url=base_url,
        token=token,
        source=source,
    )


def _api_failure_message(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code:
        body = getattr(response, "text", "") or ""
        detail = f": {body[:220]}" if body else ""
        return f"Home Assistant API returned HTTP {status_code}{detail}"
    return f"Home Assistant API failed: {exc.__class__.__name__}"


def _capabilities(domain: str, attrs: dict[str, Any]) -> list[str]:
    caps = {"on_off"} if domain in {"light", "switch", "fan", "media_player", "cover"} else set()
    supported_color_modes = set(attrs.get("supported_color_modes") or [])

    if domain == "light":
        if "brightness" in attrs or "brightness" in supported_color_modes:
            caps.add("brightness")
        if "color_temp" in attrs or "color_temp" in supported_color_modes or "min_color_temp_kelvin" in attrs:
            caps.add("color_temp")
        if "rgb_color" in attrs or {"rgb", "rgbw", "rgbww", "hs"} & supported_color_modes:
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


def _read_storage_file(name: str, config_path: Path | None = None) -> dict[str, Any]:
    config_path = config_path or DEFAULT_HA_CONFIG_PATH
    path = config_path / ".storage" / name
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _storage_items(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    items = data.get(key)
    return [item for item in items or [] if isinstance(item, dict)]


def _fallback_capabilities(domain: str) -> list[str]:
    if domain in {"light", "switch", "fan", "media_player", "cover"}:
        return ["on_off"]
    if domain == "climate":
        return ["mode"]
    return []


def _load_storage_registries(config_path: Path | None = None) -> tuple[dict[str, str], dict[str, str]]:
    config_path = config_path or DEFAULT_HA_CONFIG_PATH
    area_data = _read_storage_file("core.area_registry", config_path)
    device_data = _read_storage_file("core.device_registry", config_path)
    entity_data = _read_storage_file("core.entity_registry", config_path)

    area_names = {
        area.get("area_id"): area.get("name", area.get("area_id"))
        for area in _storage_items(area_data, "areas")
        if area.get("area_id")
    }
    device_areas = {
        device.get("id"): device.get("area_id")
        for device in _storage_items(device_data, "devices")
        if device.get("id") and device.get("area_id")
    }
    entity_areas: dict[str, str] = {}
    for entity in _storage_items(entity_data, "entities"):
        entity_id = entity.get("entity_id")
        area_id = entity.get("area_id") or device_areas.get(entity.get("device_id"))
        if entity_id and area_id:
            entity_areas[entity_id] = area_names.get(area_id, area_id)
    return area_names, entity_areas


def _list_entities_from_storage(room_id: str | None = None, config_path: Path | None = None) -> list[dict[str, Any]]:
    config_path = config_path or DEFAULT_HA_CONFIG_PATH
    entity_data = _read_storage_file("core.entity_registry", config_path)
    _, entity_areas = _load_storage_registries(config_path)
    entities: list[dict[str, Any]] = []
    for entry in _storage_items(entity_data, "entities"):
        entity_id = entry.get("entity_id")
        if not isinstance(entity_id, str) or "." not in entity_id:
            continue
        if entry.get("disabled_by") or entry.get("hidden_by"):
            continue
        domain = entity_id.split(".", 1)[0]
        if domain not in SUPPORTED_DOMAINS:
            continue
        name = entry.get("name") or entry.get("original_name") or entry.get("unique_id") or entity_id
        room = entity_areas.get(entity_id)
        entities.append(
            {
                "entity_id": entity_id,
                "domain": domain,
                "capabilities": _fallback_capabilities(domain),
                "state": {
                    "value": "unknown",
                    "attributes": {"friendly_name": name},
                },
                "room": room,
                "name": name,
                "source": "storage",
            }
        )

    if room_id:
        room_key = room_id.strip().lower()
        entities = [
            entity for entity in entities
            if (entity.get("room") or "").lower() == room_key
            or room_key in (entity.get("entity_id") or "").lower()
            or room_key in (entity.get("name") or "").lower()
        ]
    return entities


async def _get_json(path: str, settings: HAApiSettings) -> Any:
    import httpx

    headers = {"Authorization": f"Bearer {settings.token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.get(f"{settings.base_url}{path}", headers=headers)
        response.raise_for_status()
        return response.json()


async def _post_json(path: str, payload: dict[str, Any], settings: HAApiSettings) -> Any:
    import httpx

    headers = {"Authorization": f"Bearer {settings.token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(f"{settings.base_url}{path}", headers=headers, json=payload)
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()


def _clean_service_payload(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned = {key: value for key, value in payload.items() if value is not None}
    if "color_temp" in cleaned and isinstance(cleaned["color_temp"], int) and cleaned["color_temp"] > 1000:
        cleaned["color_temp_kelvin"] = cleaned.pop("color_temp")
    if cleaned.get("effect"):
        for key in ("color_temp", "color_temp_kelvin", "rgb_color", "xy_color", "hs_color"):
            cleaned.pop(key, None)
    elif "effect" in cleaned:
        cleaned.pop("effect", None)
    return cleaned


def _retry_payloads(domain: str, service: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    primary = _clean_service_payload(payload)
    attempts = [primary]
    if domain == "light" and service == "turn_on":
        without_effect = dict(primary)
        without_effect.pop("effect", None)
        if without_effect != primary:
            attempts.append(without_effect)

        without_color = dict(without_effect)
        for key in ("color_temp", "color_temp_kelvin", "rgb_color", "xy_color", "hs_color"):
            without_color.pop(key, None)
        if without_color != attempts[-1]:
            attempts.append(without_color)

        minimal = {"entity_id": primary["entity_id"]}
        if "brightness" in primary:
            minimal["brightness"] = primary["brightness"]
        if minimal != attempts[-1]:
            attempts.append(minimal)

    unique: list[dict[str, Any]] = []
    for attempt in attempts:
        if attempt not in unique:
            unique.append(attempt)
    return unique


def _bounded_action_int(action: dict[str, Any], key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(action.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _payload_with_timing(action: dict[str, Any]) -> dict[str, Any]:
    payload = {"entity_id": action.get("entity_id")}
    payload.update(action.get("data") or {})
    duration_ms = _bounded_action_int(action, "duration_ms", 0, 0, MAX_DURATION_MS)
    if (
        duration_ms
        and action.get("domain") == "light"
        and action.get("service") == "turn_on"
        and payload.get("transition") is None
    ):
        payload["transition"] = round(duration_ms / 1000, 2)
    return payload


def _scene_automation(scene: dict[str, Any]) -> dict[str, int | str]:
    automation = scene.get("automation") if isinstance(scene.get("automation"), dict) else {}
    mode = str(automation.get("mode") or "one_shot")
    repeat_default = 1 if mode == "one_shot" else 1
    repeat = _bounded_action_int(automation, "repeat", repeat_default, 1, MAX_REPEAT)
    interval_ms = _bounded_action_int(automation, "interval_ms", 0, 0, MAX_INTERVAL_MS)
    return {"mode": mode, "repeat": repeat, "interval_ms": interval_ms}


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
        return _list_entities_from_storage(room_id)

    try:
        states, (_, entity_areas) = await asyncio.gather(
            _get_json("/states", settings),
            _load_registries(settings),
        )
    except Exception:
        return _list_entities_from_storage(room_id)

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
        try:
            area_names, _ = await _load_registries(settings)
            if area_names:
                return [{"area_id": area_id, "name": name} for area_id, name in sorted(area_names.items())]
        except Exception:
            pass

    area_names, _ = _load_storage_registries()
    if area_names:
        return [{"area_id": area_id, "name": name} for area_id, name in sorted(area_names.items())]

    entities = await list_entities()
    rooms = sorted({entity.get("room") for entity in entities if entity.get("room")})
    return [{"area_id": room, "name": room.replace("_", " ").title()} for room in rooms]


async def discovery_status() -> dict[str, Any]:
    settings = load_ha_api_settings()
    if not settings.configured:
        areas = await list_areas()
        entities = await list_entities()
        if entities:
            return {
                "ok": True,
                "message": "Syn found devices from Home Assistant's registry. Add a Home Assistant token in the add-on options to enable live states and Apply Preview.",
                "entity_count": len(entities),
                "area_count": len(areas),
                "base_url": settings.base_url,
                "token_source": settings.source,
                "source": "storage",
                "domains": sorted({entity["domain"] for entity in entities}),
            }
        return {
            "ok": False,
            "message": "Syn cannot read Home Assistant yet. Add a Home Assistant token in the add-on options, then restart Syn.",
            "entity_count": 0,
            "area_count": 0,
            "base_url": settings.base_url,
            "token_source": settings.source,
            "source": "none",
        }

    try:
        raw_states = await _get_json("/states", settings)
        areas, entities = await asyncio.gather(list_areas(), list_entities())
    except Exception as exc:
        areas = await list_areas()
        entities = await list_entities()
        if entities:
            return {
                "ok": True,
                "message": f"{_api_failure_message(exc)}. Syn is using registry fallback. Add/fix Home Assistant token in add-on options for live states and Apply Preview.",
                "entity_count": len(entities),
                "area_count": len(areas),
                "base_url": settings.base_url,
                "token_source": settings.source,
                "source": "storage",
                "domains": sorted({entity["domain"] for entity in entities}),
            }
        return {
            "ok": False,
            "message": f"{_api_failure_message(exc)} and registry fallback found no usable entities.",
            "entity_count": 0,
            "area_count": 0,
            "base_url": settings.base_url,
            "token_source": settings.source,
            "source": "none",
        }

    return {
        "ok": True,
        "message": "Home Assistant discovery is working.",
        "entity_count": len(entities) or len(raw_states or []),
        "area_count": len(areas),
        "base_url": settings.base_url,
        "token_source": settings.source,
        "source": "api",
        "domains": sorted({entity["domain"] for entity in entities}),
    }


async def execute_scene_actions(
    scene: dict[str, Any],
    sequence_repeat_override: int | None = None,
) -> dict[str, Any]:
    settings = load_ha_api_settings()
    if not settings.configured:
        return {
            "overall_status": "failed",
            "message": "Apply Preview needs Home Assistant API access. Add a Home Assistant token in the add-on options, then restart Syn.",
            "actions": [],
        }

    actions = scene.get("actions", []) or []
    if not actions:
        return {
            "overall_status": "failed",
            "message": "Scene has no executable actions.",
            "actions": [],
            "actions_executed": 0,
            "actions_failed": 0,
        }

    automation = _scene_automation(scene)
    sequence_repeat = (
        max(1, min(MAX_REPEAT, int(sequence_repeat_override)))
        if sequence_repeat_override is not None
        else int(automation["repeat"])
    )
    sequence_interval_ms = int(automation["interval_ms"])
    planned_calls = sequence_repeat * sum(_bounded_action_int(action, "repeat", 1, 1, MAX_REPEAT) for action in actions)
    results = []
    for sequence_index in range(sequence_repeat):
        for action in actions:
            domain = action.get("domain")
            service = action.get("service")
            entity_id = action.get("entity_id")
            if not domain or not service or not entity_id:
                results.append({"entity_id": entity_id, "status": "skipped", "message": "Missing domain/service/entity_id"})
                continue
            delay_ms = _bounded_action_int(action, "delay_ms", 0, 0, MAX_DELAY_MS)
            interval_ms = _bounded_action_int(action, "interval_ms", 0, 0, MAX_INTERVAL_MS)
            repeat = _bounded_action_int(action, "repeat", 1, 1, MAX_REPEAT)
            if delay_ms:
                await asyncio.sleep(delay_ms / 1000)

            for repeat_index in range(repeat):
                payload = _payload_with_timing(action)
                attempts = _retry_payloads(domain, service, payload)
                last_exc: Exception | None = None
                try:
                    applied_payload = attempts[0]
                    for index, attempt in enumerate(attempts):
                        try:
                            await _post_json(f"/services/{domain}/{service}", attempt, settings)
                            applied_payload = attempt
                            result = {
                                "entity_id": entity_id,
                                "service": f"{domain}.{service}",
                                "data": applied_payload,
                                "status": "success",
                            }
                            if sequence_repeat > 1:
                                result["sequence_index"] = sequence_index + 1
                                result["sequence_repeat"] = sequence_repeat
                            if repeat > 1:
                                result["repeat_index"] = repeat_index + 1
                                result["repeat"] = repeat
                            if index > 0:
                                result["message"] = "Applied after simplifying unsupported light data"
                            results.append(result)
                            last_exc = None
                            break
                        except Exception as exc:
                            last_exc = exc
                    if last_exc:
                        raise last_exc
                except Exception as exc:
                    failed_result = {
                        "entity_id": entity_id,
                        "service": f"{domain}.{service}",
                        "data": attempts[0],
                        "status": "failed",
                        "message": _api_failure_message(exc),
                    }
                    if sequence_repeat > 1:
                        failed_result["sequence_index"] = sequence_index + 1
                        failed_result["sequence_repeat"] = sequence_repeat
                    if repeat > 1:
                        failed_result["repeat_index"] = repeat_index + 1
                        failed_result["repeat"] = repeat
                    results.append(failed_result)

                if repeat_index < repeat - 1 and interval_ms:
                    await asyncio.sleep(interval_ms / 1000)
        if sequence_index < sequence_repeat - 1 and sequence_interval_ms:
            await asyncio.sleep(sequence_interval_ms / 1000)

    failed = [result for result in results if result["status"] == "failed"]
    skipped = [result for result in results if result["status"] == "skipped"]
    succeeded = [result for result in results if result["status"] == "success"]
    status = "success" if succeeded and not failed and not skipped else "failed"
    return {
        "overall_status": status,
        "message": f"Applied {len(succeeded)} of {planned_calls} service calls across {len(actions)} scene actions.",
        "actions": results,
        "actions_executed": len(succeeded),
        "actions_failed": len(failed),
    }
