"""Export saved Syn scenes into Home Assistant native scene/script files."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Any

import yaml

from .ha_client import (
    MAX_DELAY_MS,
    MAX_DURATION_MS,
    MAX_INTERVAL_MS,
    MAX_REPEAT,
    _clean_service_payload,
    _post_json,
    load_ha_api_settings,
)
from .version_sync import resolve_ha_config_path

SYN_ID_PREFIX = "syn_"
MAX_NATIVE_NAME = 80


@dataclass(frozen=True)
class NativeIds:
    scene_id: str
    start_script_id: str
    stop_script_id: str


def _utcnow() -> str:
    return datetime.utcnow().isoformat()


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    if not safe:
        safe = "scene"
    if not safe.startswith(SYN_ID_PREFIX):
        safe = f"{SYN_ID_PREFIX}{safe}"
    return safe[:120]


def native_ids(scene_id: str) -> NativeIds:
    base = _safe_id(scene_id)
    return NativeIds(
        scene_id=base,
        start_script_id=f"{base}_start",
        stop_script_id=f"{base}_stop",
    )


def _native_name(scene: dict[str, Any]) -> str:
    name = str(scene.get("scene_name") or "Syn Scene").strip() or "Syn Scene"
    if not name.lower().startswith("syn"):
        name = f"Syn - {name}"
    return name[:MAX_NATIVE_NAME]


def _native_scene_name(scene: dict[str, Any]) -> str:
    name = _native_name(scene)
    if _is_animated(scene) and "snapshot" not in name.lower():
        name = f"{name} Snapshot"
    return name[:MAX_NATIVE_NAME]


def _native_run_name(scene: dict[str, Any]) -> str:
    name = _native_name(scene)
    if _is_animated(scene) and "loop" not in name.lower():
        name = f"{name} Loop"
    return name[:MAX_NATIVE_NAME]


def _is_animated(scene: dict[str, Any]) -> bool:
    automation = scene.get("automation") if isinstance(scene.get("automation"), dict) else {}
    if str(automation.get("mode") or "").lower() in {"loop", "sequence"}:
        return True
    return any(
        isinstance(action, dict)
        and any(action.get(key) for key in ("delay_ms", "duration_ms", "interval_ms", "repeat"))
        for action in scene.get("actions", []) or []
    )


def _read_yaml(path: Path, fallback: Any) -> Any:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return deepcopy(fallback)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return deepcopy(fallback) if data is None else data


def _scripts_mapping(data: Any, scripts_path: Path) -> dict[str, Any]:
    """Return a scripts mapping while tolerating HA's empty-list placeholder."""

    if isinstance(data, dict):
        return data
    if isinstance(data, list) and not data:
        return {}
    raise ValueError(f"{scripts_path} must contain a YAML mapping or an empty list to export Syn scripts safely")


def _write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )


def _state_from_action(action: dict[str, Any]) -> dict[str, Any] | None:
    entity_id = action.get("entity_id")
    domain = action.get("domain")
    service = action.get("service")
    if not entity_id or not domain or not service:
        return None

    data = _clean_service_payload(action.get("data") or {})
    if domain == "light":
        if service == "turn_off":
            return {"state": "off"}
        if service != "turn_on":
            return None
        state: dict[str, Any] = {"state": "on"}
        for key in (
            "brightness",
            "color_temp",
            "color_temp_kelvin",
            "rgb_color",
            "xy_color",
            "hs_color",
            "effect",
        ):
            if key in data:
                state[key] = data[key]
        return state

    if domain in {"switch", "fan", "media_player"}:
        if service == "turn_off":
            return {"state": "off"}
        if service == "turn_on":
            state = {"state": "on"}
            for key in ("percentage", "preset_mode", "oscillating", "volume_level", "source"):
                if key in data:
                    state[key] = data[key]
            return state

    return None


def _snapshot_entities(scene: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entities: dict[str, dict[str, Any]] = {}
    animated = _is_animated(scene)
    for action in scene.get("actions", []) or []:
        if not isinstance(action, dict):
            continue
        entity_id = action.get("entity_id")
        native_state = _state_from_action(action)
        if not entity_id or native_state is None:
            continue
        if animated and entity_id in entities:
            continue
        entities[entity_id] = native_state
    return entities


def _bounded_int(source: dict[str, Any], key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(source.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _delay_step(delay_ms: int) -> dict[str, Any] | None:
    if delay_ms <= 0:
        return None
    return {"delay": {"milliseconds": delay_ms}}


def _action_payload(action: dict[str, Any]) -> dict[str, Any]:
    payload = dict(action.get("data") or {})
    duration_ms = _bounded_int(action, "duration_ms", 0, 0, MAX_DURATION_MS)
    if (
        duration_ms
        and action.get("domain") == "light"
        and action.get("service") == "turn_on"
        and payload.get("transition") is None
    ):
        payload["transition"] = round(duration_ms / 1000, 2)
    return _clean_service_payload(payload)


def _native_action_step(action: dict[str, Any]) -> dict[str, Any] | None:
    entity_id = action.get("entity_id")
    domain = action.get("domain")
    service = action.get("service")
    if not entity_id or not domain or not service:
        return None
    if domain not in {"light", "switch", "fan", "media_player", "cover", "climate"}:
        return None
    step: dict[str, Any] = {
        "action": f"{domain}.{service}",
        "target": {"entity_id": entity_id},
    }
    data = _action_payload(action)
    if data:
        step["data"] = data
    return step


def _native_action_sequence(scene: dict[str, Any]) -> list[dict[str, Any]]:
    sequence: list[dict[str, Any]] = []
    for action in scene.get("actions", []) or []:
        if not isinstance(action, dict):
            continue
        delay_ms = _bounded_int(action, "delay_ms", 0, 0, MAX_DELAY_MS)
        delay = _delay_step(delay_ms)
        if delay:
            sequence.append(delay)

        step = _native_action_step(action)
        if step is None:
            continue

        repeat = _bounded_int(action, "repeat", 1, 1, MAX_REPEAT)
        interval_ms = _bounded_int(action, "interval_ms", 0, 0, MAX_INTERVAL_MS)
        if repeat == 1:
            sequence.append(step)
            continue

        repeated = [step]
        repeated_delay = _delay_step(interval_ms)
        if repeated_delay:
            repeated.append(repeated_delay)
        sequence.append({"repeat": {"count": repeat, "sequence": repeated}})
    return sequence or [{"stop": "Syn scene has no Home Assistant-compatible actions."}]


def _scene_interval_ms(scene: dict[str, Any]) -> int:
    automation = scene.get("automation") if isinstance(scene.get("automation"), dict) else {}
    return _bounded_int(automation, "interval_ms", 750, 250, MAX_INTERVAL_MS)


def _native_start_sequence(scene_id: str, scene: dict[str, Any]) -> list[dict[str, Any]]:
    sequence = _native_action_sequence(scene)
    if not _is_animated(scene):
        return sequence

    interval = _delay_step(_scene_interval_ms(scene))
    loop_sequence = [*sequence]
    if interval:
        loop_sequence.append(interval)
    return [
        {
            "repeat": {
                "while": [
                    {
                        "condition": "template",
                        "value_template": "{{ true }}",
                    }
                ],
                "sequence": loop_sequence,
            }
        }
    ]


def _managed_scene_entry(scene_id: str, scene: dict[str, Any]) -> dict[str, Any]:
    ids = native_ids(scene_id)
    entities = _snapshot_entities(scene)
    return {
        "id": ids.scene_id,
        "name": _native_scene_name(scene),
        "entities": entities,
        "icon": "mdi:creation",
    }


def _start_script_entry(scene_id: str, scene: dict[str, Any]) -> dict[str, Any]:
    return {
        "alias": _native_run_name(scene),
        "description": (
            "Runs the Syn scene directly in Home Assistant. Animated scenes keep "
            "looping in this script until the matching stop script is run."
        ),
        "icon": "mdi:creation",
        "mode": "restart",
        "sequence": _native_start_sequence(scene_id, scene),
    }


def _stop_script_entry(scene_id: str, scene: dict[str, Any]) -> dict[str, Any]:
    name = _native_run_name(scene)
    return {
        "alias": f"Stop {name}"[:MAX_NATIVE_NAME],
        "description": (
            "Stops the native Home Assistant loop script for this Syn scene. "
            "Devices are left at their current color/brightness instead of being shut off."
        ),
        "icon": "mdi:stop-circle-outline",
        "mode": "single",
        "sequence": [
            {
                "action": "script.turn_off",
                "target": {"entity_id": f"script.{native_ids(scene_id).start_script_id}"},
            }
        ],
    }


def _upsert_native_files(config_path: Path, scene_id: str, scene: dict[str, Any]) -> dict[str, Any]:
    ids = native_ids(scene_id)
    scenes_path = config_path / "scenes.yaml"
    scripts_path = config_path / "scripts.yaml"

    scenes = _read_yaml(scenes_path, [])
    if not isinstance(scenes, list):
        raise ValueError(f"{scenes_path} must contain a YAML list to export Syn scenes safely")
    scenes = [
        entry
        for entry in scenes
        if not (isinstance(entry, dict) and entry.get("id") == ids.scene_id)
    ]
    scene_entry = _managed_scene_entry(scene_id, scene)
    if scene_entry["entities"]:
        scenes.append(scene_entry)
    _write_yaml(scenes_path, scenes)

    scripts = _scripts_mapping(_read_yaml(scripts_path, {}), scripts_path)
    scripts[ids.start_script_id] = _start_script_entry(scene_id, scene)
    scripts[ids.stop_script_id] = _stop_script_entry(scene_id, scene)
    _write_yaml(scripts_path, scripts)

    return {
        "native_scene_id": ids.scene_id if scene_entry["entities"] else None,
        "start_script_id": f"script.{ids.start_script_id}",
        "stop_script_id": f"script.{ids.stop_script_id}",
        "scenes_path": str(scenes_path),
        "scripts_path": str(scripts_path),
        "animated": _is_animated(scene),
    }


def _remove_native_entries(config_path: Path, scene_id: str) -> dict[str, Any]:
    ids = native_ids(scene_id)
    scenes_path = config_path / "scenes.yaml"
    scripts_path = config_path / "scripts.yaml"
    removed = {"scene": False, "start_script": False, "stop_script": False}

    if scenes_path.exists():
        scenes = _read_yaml(scenes_path, [])
        if isinstance(scenes, list):
            next_scenes = []
            for entry in scenes:
                if isinstance(entry, dict) and entry.get("id") == ids.scene_id:
                    removed["scene"] = True
                    continue
                next_scenes.append(entry)
            _write_yaml(scenes_path, next_scenes)

    if scripts_path.exists():
        scripts = _read_yaml(scripts_path, {})
        if isinstance(scripts, dict):
            removed["start_script"] = scripts.pop(ids.start_script_id, None) is not None
            removed["stop_script"] = scripts.pop(ids.stop_script_id, None) is not None
            _write_yaml(scripts_path, scripts)

    return removed


async def _reload_domain(domain: str) -> dict[str, Any]:
    settings = load_ha_api_settings()
    if not settings.configured:
        return {"ok": False, "message": "Home Assistant token is not configured."}
    try:
        await _post_json(f"/services/{domain}/reload", {}, settings)
    except Exception as exc:
        return {"ok": False, "message": f"{domain}.reload failed: {exc.__class__.__name__}"}
    return {"ok": True, "message": f"{domain}.reload called"}


async def reload_native_artifacts() -> dict[str, Any]:
    scene_reload, script_reload = await _reload_domain("scene"), await _reload_domain("script")
    return {"scene": scene_reload, "script": script_reload}


async def export_scene_to_home_assistant(
    scene_id: str,
    scene: dict[str, Any],
    *,
    logger=None,
) -> dict[str, Any]:
    """Create native HA scene/script YAML artifacts for a saved Syn scene."""

    config_path = resolve_ha_config_path()
    if not config_path.exists():
        return {
            "ok": False,
            "message": f"Home Assistant config path is not available: {config_path}",
            "scene_id": scene_id,
        }
    try:
        details = _upsert_native_files(config_path, scene_id, scene)
        reloads = await reload_native_artifacts()
    except Exception as exc:
        if logger:
            logger.exception("Native Home Assistant export failed for %s", scene_id)
        return {
            "ok": False,
            "message": f"Native Home Assistant export failed: {exc}",
            "scene_id": scene_id,
        }

    scene["haos"] = {
        "exported": True,
        "exported_at": _utcnow(),
        **details,
        "reload": reloads,
    }
    reload_ok = all(result.get("ok") for result in reloads.values())
    return {
        "ok": True,
        "message": (
            "Saved to Home Assistant scenes/scripts and reload requested."
            if reload_ok
            else "Saved to Home Assistant YAML. Reload Home Assistant scenes/scripts if they do not appear immediately."
        ),
        "scene_id": scene_id,
        **details,
        "reload": reloads,
    }


async def remove_scene_from_home_assistant(scene_id: str, *, logger=None) -> dict[str, Any]:
    """Remove generated native HA artifacts for a deleted Syn scene."""

    config_path = resolve_ha_config_path()
    if not config_path.exists():
        return {
            "ok": False,
            "message": f"Home Assistant config path is not available: {config_path}",
            "scene_id": scene_id,
        }
    try:
        removed = _remove_native_entries(config_path, scene_id)
        reloads = await reload_native_artifacts()
    except Exception as exc:
        if logger:
            logger.exception("Native Home Assistant removal failed for %s", scene_id)
        return {
            "ok": False,
            "message": f"Native Home Assistant removal failed: {exc}",
            "scene_id": scene_id,
        }
    return {
        "ok": True,
        "message": "Removed generated Home Assistant scene/script entries.",
        "scene_id": scene_id,
        "removed": removed,
        "reload": reloads,
    }
