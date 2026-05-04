from jsonschema import validate
from jsonschema.exceptions import ValidationError
from typing import Any, Dict, List
import json
import os
import logging
import re

logger = logging.getLogger("addon.validator")


class ValidationResult:
    def __init__(self, is_valid: bool, normalized: Dict[str, Any] = None, errors: List[str] = None, warnings: List[str] = None):
        self.is_valid = is_valid
        self.normalized = normalized or {}
        self.errors = errors or []
        self.warnings = warnings or []


# Whitelisted domain->services for safety. Keep small and explicit.
SERVICE_WHITELIST = {
    "light": {"turn_on", "turn_off", "toggle"},
    "media_player": {
        "turn_on",
        "turn_off",
        "volume_set",
        "volume_mute",
        "select_source",
        "media_play",
        "media_pause",
    },
    "switch": {"turn_on", "turn_off", "toggle"},
    "fan": {"turn_on", "turn_off", "set_percentage", "oscillate"},
}


SERVICE_ALIASES = {
    ("light", "set_brightness"): "turn_on",
    ("light", "set_color"): "turn_on",
    ("light", "set_color_temp"): "turn_on",
    ("media_player", "mute"): "volume_mute",
    ("fan", "set_speed"): "set_percentage",
}

CAPABILITY_ALIASES = {
    "rgb": "rgb_color",
    "color": "rgb_color",
    "volume": "volume",
    "source": "source",
    "mute": "mute",
    "speed": "percentage",
}

STYLE_PALETTES = {
    "party": [
        [255, 0, 120],
        [0, 180, 255],
        [140, 0, 255],
        [0, 255, 120],
        [255, 180, 0],
        [255, 40, 40],
    ],
    "horror": [
        [170, 0, 0],
        [85, 0, 130],
        [20, 0, 80],
        [255, 35, 0],
        [110, 0, 35],
    ],
}

MOTION_STYLES = {"party", "horror"}
PHASE_DURATION_MS = 1400
PHASE_PAUSE_MS = 450

EFFECT_PREFERENCES = {
    "party": ("party", "rhythm", "pulse", "pastel", "mojito", "diwali", "club", "rainbow", "color", "flow", "dynamic", "dance"),
    "horror": ("halloween", "fire", "candle", "pulse", "night", "deep", "mystic", "storm", "spooky"),
}

TIMING_FIELDS = ("delay_ms", "duration_ms", "interval_ms", "repeat")
MAX_DELAY_MS = 30_000
MAX_DURATION_MS = 300_000
MAX_INTERVAL_MS = 10_000
MAX_REPEAT = 12

TIMING_ALIASES = (
    ("delay_ms", "delay_ms", "ms", 0, MAX_DELAY_MS),
    ("wait_ms", "delay_ms", "ms", 0, MAX_DELAY_MS),
    ("delay", "delay_ms", "s", 0, MAX_DELAY_MS),
    ("wait", "delay_ms", "s", 0, MAX_DELAY_MS),
    ("delay_seconds", "delay_ms", "s", 0, MAX_DELAY_MS),
    ("duration_ms", "duration_ms", "ms", 0, MAX_DURATION_MS),
    ("fade_ms", "duration_ms", "ms", 0, MAX_DURATION_MS),
    ("transition_ms", "duration_ms", "ms", 0, MAX_DURATION_MS),
    ("duration", "duration_ms", "s", 0, MAX_DURATION_MS),
    ("fade", "duration_ms", "s", 0, MAX_DURATION_MS),
    ("transition_seconds", "duration_ms", "s", 0, MAX_DURATION_MS),
    ("interval_ms", "interval_ms", "ms", 0, MAX_INTERVAL_MS),
    ("interval", "interval_ms", "s", 0, MAX_INTERVAL_MS),
)


def _as_dict(value: Any) -> Dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value or {}


def _string_list(value: Any) -> List[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    normalized: List[str] = []
    for item in items:
        if item is None:
            continue
        if isinstance(item, str):
            text = item
        else:
            try:
                text = json.dumps(item, ensure_ascii=False, sort_keys=True)
            except TypeError:
                text = str(item)
        text = text.strip()
        if text:
            normalized.append(text)
    return list(dict.fromkeys(normalized))


def _timing_value_to_ms(value: Any, default_unit: str = "ms") -> int | None:
    if isinstance(value, str):
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(ms|s|sec|secs|second|seconds)?\s*", value, flags=re.I)
        if not match:
            return None
        number = float(match.group(1))
        unit = (match.group(2) or default_unit).lower()
        return int(round(number * 1000)) if unit.startswith("s") else int(round(number))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        return int(round(number * 1000)) if default_unit == "s" else int(round(number))
    return None


def _bounded_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def _normalize_action_timing(action: Dict[str, Any], warnings: List[str], entity_id: str | None = None) -> Dict[str, int]:
    timing: Dict[str, int] = {}
    label = entity_id or action.get("entity_id") or "action"

    for source, target, unit, minimum, maximum in TIMING_ALIASES:
        if target in timing or source not in action:
            continue
        parsed = _timing_value_to_ms(action.get(source), unit)
        if parsed is None:
            warnings.append(f"Removed invalid timing field '{source}' for {label}")
            continue
        bounded = _bounded_int(parsed, minimum, maximum)
        if bounded != parsed:
            warnings.append(f"Clamped {target} for {label} to {bounded}")
        if bounded:
            timing[target] = bounded

    for source in ("repeat", "repeats", "repeat_count"):
        if "repeat" in timing or source not in action:
            continue
        try:
            repeat = int(action.get(source))
        except (TypeError, ValueError):
            warnings.append(f"Removed invalid repeat field for {label}")
            continue
        bounded = _bounded_int(repeat, 1, MAX_REPEAT)
        if bounded != repeat:
            warnings.append(f"Clamped repeat for {label} to {bounded}")
        timing["repeat"] = bounded

    return timing


def _normalize_scene_automation(raw: Any, warnings: List[str]) -> Dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        warnings.append("Removed invalid scene automation block")
        return None

    automation: Dict[str, Any] = {}
    mode = str(raw.get("mode") or "sequence").strip().lower()
    automation["mode"] = mode if mode in {"one_shot", "sequence", "loop"} else "sequence"
    if raw.get("summary"):
        automation["summary"] = str(raw.get("summary"))[:240]

    try:
        repeat = int(raw.get("repeat", 1))
    except (TypeError, ValueError):
        repeat = 1
    automation["repeat"] = _bounded_int(repeat, 1, MAX_REPEAT)

    interval_ms = _timing_value_to_ms(raw.get("interval_ms", raw.get("interval", 0)), "ms")
    if interval_ms:
        automation["interval_ms"] = _bounded_int(interval_ms, 0, MAX_INTERVAL_MS)

    duration_ms = _timing_value_to_ms(raw.get("duration_ms", raw.get("duration", 0)), "ms")
    if duration_ms:
        automation["duration_ms"] = _bounded_int(duration_ms, 0, MAX_DURATION_MS)

    if automation["mode"] == "one_shot" and automation["repeat"] > 1:
        automation["mode"] = "sequence"
    return automation


def _normalize_caps(entity: Dict[str, Any]) -> set[str]:
    caps = set(entity.get("capabilities", []) or [])
    attrs = (entity.get("state") or {}).get("attributes", {}) or {}
    supported_color_modes = set(attrs.get("supported_color_modes") or [])
    if entity.get("domain") in {"light", "switch", "fan", "media_player"}:
        caps.add("on_off")
    if "brightness" in attrs or "brightness" in supported_color_modes:
        caps.add("brightness")
    if "color_temp" in attrs or "min_color_temp" in attrs or "min_color_temp_kelvin" in attrs or "color_temp" in supported_color_modes:
        caps.add("color_temp")
    if "rgb_color" in attrs or "xy_color" in attrs or {"rgb", "rgbw", "rgbww", "hs"} & supported_color_modes:
        caps.add("rgb_color")
    if "xy_color" in attrs or "xy" in supported_color_modes:
        caps.add("xy_color")
    if attrs.get("effect_list"):
        caps.add("effect")
    if "volume_level" in attrs:
        caps.add("volume")
    if "source_list" in attrs:
        caps.add("source")
    if "is_volume_muted" in attrs:
        caps.add("mute")
    return {CAPABILITY_ALIASES.get(cap, cap) for cap in caps}


def _light_attrs(entity: Dict[str, Any]) -> Dict[str, Any]:
    attrs = (entity.get("state") or {}).get("attributes", {}) or {}
    return attrs if isinstance(attrs, dict) else {}


def _effect_list(entity: Dict[str, Any]) -> List[str]:
    effect_list = _light_attrs(entity).get("effect_list") or []
    return [str(effect) for effect in effect_list if effect]


def _choose_effect(style: str, entity: Dict[str, Any]) -> str | None:
    effects = _effect_list(entity)
    preferences = EFFECT_PREFERENCES.get(style, ())
    matches: List[str] = []
    for wanted in preferences:
        for effect in effects:
            if wanted in effect.lower() and effect not in matches:
                matches.append(effect)
    if not matches:
        return None
    if style in {"party", "horror"}:
        return matches[_stable_index(str(entity.get("entity_id") or ""), len(matches))]
    return matches[0]


def _scene_style(scene: Dict[str, Any]) -> str:
    text = " ".join(
        str(scene.get(key) or "")
        for key in ("scene_name", "description", "intent", "target_room")
    ).lower()
    if any(
        phrase in text
        for phrase in (
            "full brightness",
            "full bright",
            "maximum brightness",
            "max brightness",
            "100%",
            "hundred percent",
            "brightest",
            "all lights full",
            "everything full",
        )
    ):
        return "full_brightness"
    if any(word in text for word in ("party", "dance", "club", "disco", "celebration", "rainbow")):
        return "party"
    if any(word in text for word in ("horror", "scary", "spooky", "haunted", "creepy", "blood", "eerie")):
        return "horror"
    if any(word in text for word in ("office", "work", "focus", "study", "productive", "reading")):
        return "office"
    if any(word in text for word in ("movie", "cinema", "cozy", "cosy", "night", "relax", "dim", "sleep")):
        return "cozy"
    return "general"


def _scene_text(scene: Dict[str, Any]) -> str:
    return " ".join(
        str(scene.get(key) or "")
        for key in ("scene_name", "description", "intent", "target_room")
    ).lower()


def _prefers_effect_mode(scene: Dict[str, Any]) -> bool:
    text = _scene_text(scene)
    return any(phrase in text for phrase in ("effect mode", "wiz effect", "light effect", "use effect", "use effects"))


def _wants_longer_motion(scene: Dict[str, Any]) -> bool:
    text = _scene_text(scene)
    return any(word in text for word in ("ongoing", "continuous", "loop", "looping", "animated", "animation", "changing", "pulse"))


def _scene_mentions_any(scene: Dict[str, Any], words: set[str]) -> bool:
    text = _scene_text(scene)
    return any(word in text for word in words)


def _should_add_missing_entity(scene: Dict[str, Any], entity: Dict[str, Any], existing_domains: set[str]) -> bool:
    domain = entity.get("domain")
    if domain == "light":
        return "light" in existing_domains or _scene_style(scene) in {"party", "horror", "office", "cozy", "full_brightness"}
    if domain == "media_player":
        return "media_player" in existing_domains or _scene_mentions_any(scene, {"movie", "tv", "music", "audio", "speaker", "volume"})
    if domain == "fan":
        return "fan" in existing_domains or _scene_mentions_any(scene, {"fan", "air", "breeze", "cool"})
    if domain == "switch":
        return "switch" in existing_domains
    return False


def _stable_index(value: str, size: int) -> int:
    if size <= 0:
        return 0
    return sum(ord(char) for char in value) % size


def _clamp_kelvin(entity: Dict[str, Any], kelvin: int) -> int:
    attrs = _light_attrs(entity)
    minimum = attrs.get("min_color_temp_kelvin") or 2000
    maximum = attrs.get("max_color_temp_kelvin") or 6500
    try:
        minimum = int(minimum)
        maximum = int(maximum)
    except (TypeError, ValueError):
        minimum, maximum = 2000, 6500
    return max(minimum, min(maximum, int(kelvin)))


def _entity_summary(entity: Dict[str, Any]) -> Dict[str, Any]:
    summary = {
        "entity_id": entity.get("entity_id"),
        "domain": entity.get("domain"),
        "capabilities": sorted(_normalize_caps(entity)),
    }
    effects = _effect_list(entity)
    if effects:
        summary["effects"] = effects
    attrs = _light_attrs(entity)
    if "min_color_temp_kelvin" in attrs:
        summary["min_color_temp_kelvin"] = attrs.get("min_color_temp_kelvin")
    if "max_color_temp_kelvin" in attrs:
        summary["max_color_temp_kelvin"] = attrs.get("max_color_temp_kelvin")
    return summary


def _entity_label(entity: Dict[str, Any]) -> str:
    return str(
        entity.get("name")
        or (entity.get("state") or {}).get("attributes", {}).get("friendly_name")
        or entity.get("entity_id")
        or "selected device"
    )


def _is_dim_scene(scene: Dict[str, Any]) -> bool:
    return _scene_style(scene) == "cozy"


def _infer_entity_id(action: Dict[str, Any], entity_map: Dict[str, Dict[str, Any]]) -> str | None:
    candidates = list(entity_map)
    if action.get("entity_id") in entity_map:
        return action.get("entity_id")

    domain = action.get("domain")
    if domain:
        domain_matches = [eid for eid, entity in entity_map.items() if entity.get("domain") == domain]
        if len(domain_matches) == 1:
            return domain_matches[0]
        return None

    for key in ("entity", "target", "name", "device", "friendly_name"):
        value = str(action.get(key) or "").strip().lower()
        if not value:
            continue
        for eid, entity in entity_map.items():
            names = {
                eid.lower(),
                str(entity.get("name") or "").lower(),
                str(entity.get("friendly_name") or "").lower(),
            }
            if value in names:
                return eid

    return candidates[0] if len(candidates) == 1 else None


def _fallback_action_for_entity(entity: Dict[str, Any], priority: int = 1) -> Dict[str, Any] | None:
    entity_id = entity.get("entity_id")
    domain = entity.get("domain") or (entity_id or "").split(".", 1)[0]
    caps = _normalize_caps(entity)
    data: Dict[str, Any] = {}
    service = "turn_on"

    if domain == "light":
        if "brightness" in caps:
            data["brightness"] = 120
    elif domain in {"switch", "fan", "media_player"}:
        service = "turn_on"
    else:
        return None

    return {
        "entity_id": entity_id,
        "domain": domain,
        "service": service,
        "data": data,
        "rationale": "Safe fallback because the AI returned no usable action for the selected device",
        "priority": priority,
    }


def _repair_raw_scene(raw: Any, available_entities: List[Dict[str, Any]]) -> tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    entities = [_as_dict(e) for e in available_entities]
    entity_map = {e["entity_id"]: e for e in entities if e.get("entity_id")}

    if not isinstance(raw, dict):
        return raw, warnings

    repaired: Dict[str, Any] = {
        "scene_name": str(raw.get("scene_name") or raw.get("name") or "Syn Scene Draft"),
        "description": str(raw.get("description") or "Scene generated by Syn."),
        "intent": str(raw.get("intent") or raw.get("user_intent") or raw.get("description") or "Create scene"),
        "target_room": str(raw.get("target_room") or raw.get("room") or "unspecified"),
        "confidence": raw.get("confidence", 0.5),
        "warnings": _string_list(raw.get("warnings")),
        "assumptions": _string_list(raw.get("assumptions")),
        "entity_map": {},
        "actions": [],
    }
    automation = _normalize_scene_automation(raw.get("automation"), warnings)
    if automation:
        repaired["automation"] = automation

    raw_actions = raw.get("actions") or raw.get("service_calls") or raw.get("steps") or []
    if isinstance(raw_actions, dict):
        raw_actions = [raw_actions]
    if not isinstance(raw_actions, list):
        raw_actions = []

    referenced_ids: set[str] = set()
    for index, item in enumerate(raw_actions):
        if not isinstance(item, dict):
            continue
        action = dict(item)
        inferred_entity = not action.get("entity_id")
        eid = _infer_entity_id(action, entity_map)
        if not eid:
            eid = action.get("entity_id")
        if not eid:
            if action.get("domain"):
                warnings.append(f"Omitted hallucinated {action.get('domain')} action because no matching selected entity exists")
            else:
                warnings.append(f"Omitted action {index + 1} because no entity_id could be inferred")
            continue
        if eid not in entity_map and entity_map:
            warnings.append(f"Omitted hallucinated unknown entity {eid}")
            continue

        entity = entity_map.get(eid, {})
        actual_domain = entity.get("domain")
        domain = action.get("domain") or actual_domain or eid.split(".", 1)[0]
        service = action.get("service") or action.get("action") or "turn_on"
        data = action.get("data") or action.get("service_data") or {}
        if not isinstance(data, dict):
            warnings.append(f"Replaced non-object action data for {eid}")
            data = {}

        if actual_domain and domain != actual_domain:
            if inferred_entity:
                warnings.append(f"Omitted hallucinated {domain} action that did not match selected {actual_domain} entity {eid}")
                continue
            warnings.append(f"Repaired domain for {eid}: {domain} -> {actual_domain}")
            domain = actual_domain

        if service not in SERVICE_WHITELIST.get(domain, set()):
            if inferred_entity and domain in {"light", "switch", "fan", "media_player"}:
                warnings.append(f"Replaced unsupported service '{service}' for {eid} with turn_on")
                service = "turn_on"
                data = {}

        referenced_ids.add(eid)
        if inferred_entity:
            warnings.append(f"Repaired missing entity_id for {eid}")
        repaired_action = {
            "entity_id": eid,
            "domain": domain,
            "service": service,
            "data": data,
            "rationale": str(action.get("rationale") or action.get("reason") or "Generated by Syn"),
            "priority": int(action.get("priority", max(0, 100 - index))),
        }
        repaired_action.update(_normalize_action_timing(action, warnings, eid))
        repaired["actions"].append(repaired_action)

    if not repaired["actions"] and entity_map:
        for entity in entity_map.values():
            fallback = _fallback_action_for_entity(entity)
            if fallback:
                repaired["actions"].append(fallback)
                referenced_ids.add(fallback["entity_id"])
                warnings.append(f"Added safe fallback action for {fallback['entity_id']}")
                break

    raw_entity_map = raw.get("entity_map") if isinstance(raw.get("entity_map"), dict) else {}
    ids_for_map = referenced_ids or set(entity_map)
    for eid in ids_for_map:
        entity = entity_map.get(eid)
        if entity:
            repaired["entity_map"][eid] = _entity_summary(entity)
        elif isinstance(raw_entity_map.get(eid), dict):
            raw_entry = raw_entity_map[eid]
            repaired["entity_map"][eid] = {
                "entity_id": raw_entry.get("entity_id") or eid,
                "domain": raw_entry.get("domain") or eid.split(".", 1)[0],
                "capabilities": list(raw_entry.get("capabilities") or []),
            }

    try:
        repaired["confidence"] = float(repaired["confidence"])
    except (TypeError, ValueError):
        repaired["confidence"] = 0.5
    repaired["confidence"] = min(1.0, max(0.0, repaired["confidence"]))
    repaired["warnings"] = _string_list(repaired["warnings"] + warnings)
    return repaired, warnings


def _normalize_action_data(
    entity_id: str,
    domain: str,
    service: str,
    data: Dict[str, Any],
    caps: set[str],
    warnings: List[str],
) -> Dict[str, Any]:
    normalized = {key: value for key, value in dict(data or {}).items() if value is not None}

    if domain == "light":
        if "color" in normalized and "rgb_color" not in normalized:
            normalized["rgb_color"] = normalized.pop("color")
        if "color_temp" in normalized:
            color_temp = normalized["color_temp"]
            if isinstance(color_temp, int) and color_temp > 1000:
                normalized["color_temp_kelvin"] = color_temp
                normalized.pop("color_temp", None)
                warnings.append(f"Converted Kelvin color_temp to color_temp_kelvin for {entity_id}")
        allowed_keys = {"brightness", "color_temp", "color_temp_kelvin", "rgb_color", "xy_color", "effect", "transition"}
        for key in list(normalized):
            if key not in allowed_keys:
                warnings.append(f"Removed unsupported light data '{key}' for {entity_id}")
                normalized.pop(key, None)
        if "transition" in normalized:
            transition = normalized["transition"]
            if not isinstance(transition, (int, float)) or isinstance(transition, bool):
                raise ValueError(f"Invalid transition for {entity_id}: {transition}")
            transition = float(transition)
            if transition > 300 and transition <= MAX_DURATION_MS:
                transition = transition / 1000
                warnings.append(f"Converted millisecond transition to seconds for {entity_id}")
            if not (0 <= transition <= 300):
                raise ValueError(f"Invalid transition for {entity_id}: {normalized['transition']}")
            normalized["transition"] = round(float(transition), 2)
        if "brightness" in normalized:
            brightness = normalized["brightness"]
            if not isinstance(brightness, int) or not (0 <= brightness <= 255):
                raise ValueError(f"Invalid brightness for {entity_id}: {brightness}")
            if "brightness" not in caps:
                warnings.append(f"Entity {entity_id} has no brightness capability; removing brightness")
                normalized.pop("brightness", None)
        if "color_temp" in normalized and "color_temp" not in caps:
            warnings.append(f"Entity {entity_id} has no color_temp capability; removing color_temp")
            normalized.pop("color_temp", None)
        if "color_temp_kelvin" in normalized and "color_temp" not in caps:
            warnings.append(f"Entity {entity_id} has no color_temp capability; removing color_temp_kelvin")
            normalized.pop("color_temp_kelvin", None)
        if "rgb_color" in normalized:
            rgb = normalized["rgb_color"]
            if not (
                isinstance(rgb, list)
                and len(rgb) == 3
                and all(isinstance(v, int) and 0 <= v <= 255 for v in rgb)
            ):
                raise ValueError(f"Invalid rgb_color for {entity_id}: {rgb}")
            if "rgb_color" not in caps:
                warnings.append(f"Entity {entity_id} has no rgb_color capability; removing rgb_color")
                normalized.pop("rgb_color", None)
        if "effect" in normalized and "effect" not in caps:
            warnings.append(f"Entity {entity_id} has no effect capability; removing effect")
            normalized.pop("effect", None)
        if "effect" in normalized:
            normalized.pop("color_temp", None)
            normalized.pop("color_temp_kelvin", None)
            normalized.pop("rgb_color", None)
            normalized.pop("xy_color", None)
            warnings.append(f"Using effect mode only for {entity_id}; removed conflicting color data")

    elif domain == "media_player":
        allowed_keys = {"volume_level", "is_volume_muted", "source", "media_content_id", "media_content_type"}
        for key in list(normalized):
            if key not in allowed_keys:
                warnings.append(f"Removed unsupported media_player data '{key}' for {entity_id}")
                normalized.pop(key, None)
        if "volume_level" in normalized:
            volume = normalized["volume_level"]
            if not isinstance(volume, (int, float)) or not (0 <= float(volume) <= 1):
                raise ValueError(f"Invalid volume_level for {entity_id}: {volume}")
            if "volume" not in caps:
                warnings.append(f"Entity {entity_id} has no volume capability; removing volume_level")
                normalized.pop("volume_level", None)
        if service == "select_source" and "source" not in caps:
            warnings.append(f"Entity {entity_id} has no source capability; removing source action data")
            normalized.pop("source", None)
        if service == "volume_mute" and "mute" not in caps:
            warnings.append(f"Entity {entity_id} has no mute capability; removing mute action data")
            normalized.pop("is_volume_muted", None)

    elif domain == "fan":
        allowed_keys = {"percentage", "oscillating"}
        for key in list(normalized):
            if key not in allowed_keys:
                warnings.append(f"Removed unsupported fan data '{key}' for {entity_id}")
                normalized.pop(key, None)
        if "percentage" in normalized:
            percentage = normalized["percentage"]
            if not isinstance(percentage, int) or not (0 <= percentage <= 100):
                raise ValueError(f"Invalid fan percentage for {entity_id}: {percentage}")
            if "percentage" not in caps:
                warnings.append(f"Entity {entity_id} has no percentage capability; removing percentage")
                normalized.pop("percentage", None)

    elif domain == "switch":
        if normalized:
            warnings.append(f"Switch {entity_id} does not accept extra action data; removing data")
        normalized = {}

    return normalized


def _tune_action_for_scene(
    action: Dict[str, Any],
    scene: Dict[str, Any],
    entity: Dict[str, Any],
    caps: set[str],
    warnings: List[str],
) -> Dict[str, Any]:
    tuned = dict(action)
    data = dict(tuned.get("data") or {})
    entity_id = tuned.get("entity_id")
    label = _entity_label(entity)
    style = _scene_style(scene)

    if tuned.get("domain") == "light" and tuned.get("service") == "turn_on":
        if "effect" in data and not data.get("effect"):
            data.pop("effect", None)

        chosen_effect = _choose_effect(style, entity) if "effect" in caps else None
        if style == "full_brightness":
            if "brightness" in caps:
                data["brightness"] = 255
            if "color_temp" in caps:
                attrs = _light_attrs(entity)
                target_kelvin = attrs.get("max_color_temp_kelvin") or 6500
                data["color_temp_kelvin"] = _clamp_kelvin(entity, int(target_kelvin))
            for key in ("effect", "rgb_color", "xy_color", "color_temp"):
                data.pop(key, None)
            warnings.append(f"Tuned {entity_id} for full brightness with clean white light")
        elif style in MOTION_STYLES and "rgb_color" in caps and data.get("rgb_color") and _has_timing(tuned):
            data.pop("effect", None)
            data.pop("color_temp", None)
            data.pop("color_temp_kelvin", None)
            if "brightness" in caps and "brightness" not in data:
                data["brightness"] = 185 if style == "party" else 55
            warnings.append(f"Preserved timed {style} RGB phase for {entity_id}")
        elif style in MOTION_STYLES and "rgb_color" in caps and not _prefers_effect_mode(scene):
            palette = STYLE_PALETTES[style]
            data["rgb_color"] = palette[_stable_index(str(entity_id), len(palette))]
            data["transition"] = round(PHASE_DURATION_MS / 1000, 2)
            data.pop("effect", None)
            data.pop("color_temp", None)
            data.pop("color_temp_kelvin", None)
            data.pop("xy_color", None)
            if "brightness" in caps:
                data["brightness"] = 185 if style == "party" else 55
            warnings.append(f"Prepared {entity_id} for explicit {style} RGB choreography")
        elif chosen_effect and style in MOTION_STYLES:
            data["effect"] = chosen_effect
            for key in ("color_temp", "color_temp_kelvin", "rgb_color", "xy_color"):
                data.pop(key, None)
            if "brightness" in caps:
                data["brightness"] = 170 if style == "party" else 70
            warnings.append(f"Selected supported {style} effect '{chosen_effect}' for {entity_id}")
        elif style in MOTION_STYLES and "brightness" in caps:
            data["brightness"] = 120 if style == "party" else 45
            for key in ("effect", "rgb_color", "xy_color", "color_temp", "color_temp_kelvin"):
                data.pop(key, None)
            warnings.append(f"Tuned brightness-only light {entity_id} for {style}")
        elif style == "office":
            if "brightness" in caps:
                data["brightness"] = 190
            if "color_temp" in caps:
                data["color_temp_kelvin"] = _clamp_kelvin(entity, 4200)
                data.pop("color_temp", None)
            for key in ("effect", "rgb_color", "xy_color"):
                data.pop(key, None)
            warnings.append(f"Tuned {entity_id} for focused office lighting")
        elif style == "cozy":
            if "brightness" in caps:
                old_brightness = data.get("brightness")
                if old_brightness is None or (
                    isinstance(old_brightness, int)
                    and 0 <= old_brightness <= 255
                    and old_brightness > 90
                ):
                    data["brightness"] = 64
                    warnings.append(f"Tuned {entity_id} brightness for a cozy/movie/night scene")
            if "color_temp" in caps:
                data["color_temp_kelvin"] = _clamp_kelvin(entity, 2700)
                data.pop("color_temp", None)
                warnings.append(f"Added warm color temperature for {entity_id}")

        if "color_temp" in data and isinstance(data["color_temp"], int) and data["color_temp"] > 1000:
            data["color_temp_kelvin"] = _clamp_kelvin(entity, data["color_temp"])
            data.pop("color_temp", None)

        if "color_temp_kelvin" in data and isinstance(data["color_temp_kelvin"], int):
            data["color_temp_kelvin"] = _clamp_kelvin(entity, data["color_temp_kelvin"])

        effects = _effect_list(entity)
        if data.get("effect") and effects and data["effect"] not in effects:
            fallback_effect = _choose_effect(style, entity)
            if fallback_effect:
                warnings.append(f"Replaced unsupported effect '{data['effect']}' with '{fallback_effect}' for {entity_id}")
                data["effect"] = fallback_effect
            else:
                warnings.append(f"Removed unsupported effect '{data['effect']}' for {entity_id}")
                data.pop("effect", None)

    rationale = str(tuned.get("rationale") or "").strip()
    weak_rationale = (
        not rationale
        or len(rationale.split()) <= 2
        or rationale.lower().replace(" ", "_") in {str(entity_id).split(".", 1)[-1].lower(), str(entity_id).lower()}
    )
    if weak_rationale or any(word in rationale.lower() for word in ("living room", "fan", "tv", "television", "hallway")):
        tuned["rationale"] = f"Set {label} for {scene.get('scene_name') or scene.get('intent') or 'the requested scene'}"

    tuned["data"] = data
    return tuned


def _has_timing(action: Dict[str, Any]) -> bool:
    return any(action.get(field) for field in ("delay_ms", "duration_ms", "interval_ms")) or int(action.get("repeat") or 1) > 1


def _dedupe_actions(actions: List[Dict[str, Any]], warnings: List[str]) -> List[Dict[str, Any]]:
    deduped_indexes: Dict[tuple[str, str, str], int] = {}
    result: List[Dict[str, Any]] = []

    for action in actions:
        key = (action.get("entity_id"), action.get("domain"), action.get("service"))
        if _has_timing(action) or key not in deduped_indexes:
            if not _has_timing(action):
                deduped_indexes[key] = len(result)
            result.append(action)
            continue

        existing = result[deduped_indexes[key]]
        existing["data"] = {**(existing.get("data") or {}), **(action.get("data") or {})}
        existing["priority"] = max(existing.get("priority", 0), action.get("priority", 0))
        for timing_field in TIMING_FIELDS:
            if timing_field not in existing and timing_field in action:
                existing[timing_field] = action[timing_field]
            elif timing_field == "repeat" and timing_field in action:
                existing[timing_field] = max(existing.get(timing_field, 1), action[timing_field])
        if action.get("rationale") and not existing.get("rationale"):
            existing["rationale"] = action.get("rationale")
        warnings.append(f"Merged duplicate {key[1]}.{key[2]} action for {key[0]}")

    return result


def _motion_repeat_count(scene: Dict[str, Any]) -> int:
    return 6 if _wants_longer_motion(scene) else 3


def _synthesize_motion_choreography(
    actions: List[Dict[str, Any]],
    scene: Dict[str, Any],
    entity_map: Dict[str, Dict[str, Any]],
    warnings: List[str],
) -> List[Dict[str, Any]]:
    style = _scene_style(scene)
    if style not in MOTION_STYLES or _prefers_effect_mode(scene):
        return actions

    automation = scene.get("automation") if isinstance(scene.get("automation"), dict) else {}
    if any(_has_timing(action) for action in actions) or int(automation.get("repeat") or 1) > 1:
        return actions

    palette = STYLE_PALETTES[style]
    enhanced: List[Dict[str, Any]] = []
    rgb_actions = [
        action for action in actions
        if action.get("domain") == "light"
        and action.get("service") == "turn_on"
        and "rgb_color" in _normalize_caps(entity_map.get(action.get("entity_id"), {}))
    ]
    if not rgb_actions:
        return actions

    static_actions = [action for action in actions if action not in rgb_actions]
    phase_count = min(4 if _wants_longer_motion(scene) else 3, len(palette))
    base_priority = max([int(action.get("priority", 0)) for action in actions] + [0]) + (phase_count + 1) * 20
    for index, action in enumerate(static_actions):
        enhanced.append({**action, "priority": base_priority + 10 - index})

    for phase in range(phase_count):
        for light_index, action in enumerate(rgb_actions):
            entity_id = action.get("entity_id")
            entity = entity_map.get(entity_id, {})
            caps = _normalize_caps(entity)
            data = {
                key: value
                for key, value in (action.get("data") or {}).items()
                if key not in {"effect", "color_temp", "color_temp_kelvin", "xy_color", "rgb_color"}
            }
            data["rgb_color"] = palette[(_stable_index(str(entity_id), len(palette)) + phase) % len(palette)]
            data["transition"] = round(PHASE_DURATION_MS / 1000, 2)
            if "brightness" in caps:
                data["brightness"] = data.get("brightness") or (185 if style == "party" else 55)
            phase_action = {
                **action,
                "data": data,
                "rationale": f"{style.title()} color phase {phase + 1} for {_entity_label(entity)}",
                "priority": base_priority - (phase * 10) - light_index,
                "duration_ms": PHASE_DURATION_MS,
            }
            if phase > 0 and light_index == 0:
                phase_action["delay_ms"] = PHASE_DURATION_MS + PHASE_PAUSE_MS
            enhanced.append(phase_action)

    scene["automation"] = {
        "mode": "loop",
        "summary": f"Short safe {style} color choreography generated by Syn.",
        "repeat": _motion_repeat_count(scene),
        "interval_ms": PHASE_PAUSE_MS,
        "duration_ms": _motion_repeat_count(scene) * phase_count * (PHASE_DURATION_MS + PHASE_PAUSE_MS),
    }
    warnings.append(f"Generated repeating {style} RGB choreography with {phase_count} phases")
    return enhanced


def validate_and_normalize(raw: Any, available_entities: List[Dict[str, Any]]) -> ValidationResult:
    schema_path = os.path.join(os.path.dirname(__file__), "schema", "scene_schema.json")
    with open(schema_path, "r", encoding="utf-8") as fh:
        schema = json.load(fh)

    raw, repair_warnings = _repair_raw_scene(raw, available_entities)

    try:
        validate(instance=raw, schema=schema)
    except ValidationError as e:
        logger.warning("Schema validation failed: %s", e.message)
        return ValidationResult(False, errors=[str(e.message)])

    # Semantic checks
    entities = [_as_dict(e) for e in available_entities]
    entity_map = {e["entity_id"]: e for e in entities if e.get("entity_id")}
    errors = []
    warnings = list(repair_warnings)
    normalized_actions = []

    for a in raw.get("actions", []):
        eid = a.get("entity_id")
        domain = a.get("domain")
        service = SERVICE_ALIASES.get((domain, a.get("service")), a.get("service"))
        data = dict(a.get("data", {}) or {})

        if eid not in entity_map:
            errors.append(f"Unknown entity: {eid}")
            continue

        if domain != entity_map[eid].get("domain", domain):
            errors.append(f"Domain mismatch for {eid}: {domain} != {entity_map[eid].get('domain')}")
            continue

        allowed = SERVICE_WHITELIST.get(domain, set())
        if service not in allowed:
            errors.append(f"Unsupported service '{service}' for domain '{domain}'")
            continue

        caps = _normalize_caps(entity_map[eid])
        a = _tune_action_for_scene(a, raw, entity_map[eid], caps, warnings)
        data = dict(a.get("data", {}) or {})
        timing = _normalize_action_timing(a, warnings, eid)
        if domain == "light" and service == "turn_on" and timing.get("duration_ms") and data.get("transition") is None:
            data["transition"] = round(timing["duration_ms"] / 1000, 2)

        try:
            data = _normalize_action_data(
                eid,
                domain,
                service,
                data,
                caps,
                warnings,
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue

        normalized_action = {
            "entity_id": eid,
            "domain": domain,
            "service": service,
            "data": data,
            "rationale": a.get("rationale"),
            "priority": a.get("priority", 0),
        }
        normalized_action.update(timing)
        normalized_actions.append(normalized_action)

    if errors:
        return ValidationResult(False, errors=errors)

    handled_ids = {action.get("entity_id") for action in normalized_actions}
    existing_domains = {action.get("domain") for action in normalized_actions if action.get("domain")}
    next_priority = min([int(action.get("priority", 0)) for action in normalized_actions] + [0]) - 1
    for eid, entity in entity_map.items():
        if eid in handled_ids or not _should_add_missing_entity(raw, entity, existing_domains):
            continue
        fallback = _fallback_action_for_entity(entity, priority=next_priority)
        if not fallback:
            continue
        caps = _normalize_caps(entity)
        fallback = _tune_action_for_scene(fallback, raw, entity, caps, warnings)
        service = SERVICE_ALIASES.get((fallback["domain"], fallback["service"]), fallback["service"])
        try:
            data = _normalize_action_data(
                fallback["entity_id"],
                fallback["domain"],
                service,
                fallback.get("data") or {},
                caps,
                warnings,
            )
        except ValueError as exc:
            warnings.append(f"Skipped fallback for {eid}: {exc}")
            continue
        normalized_actions.append(
            {
                "entity_id": fallback["entity_id"],
                "domain": fallback["domain"],
                "service": service,
                "data": data,
                "rationale": f"Included selected {_entity_label(entity)} because the AI skipped it",
                "priority": next_priority,
            }
        )
        handled_ids.add(eid)
        existing_domains.add(fallback["domain"])
        next_priority -= 1
        warnings.append(f"Added safe action for selected entity {eid} because the AI skipped it")

    normalized = raw.copy()
    normalized_actions = _dedupe_actions(normalized_actions, warnings)
    normalized_actions = _synthesize_motion_choreography(normalized_actions, normalized, entity_map, warnings)
    normalized["actions"] = sorted(normalized_actions, key=lambda item: item.get("priority", 0), reverse=True)
    normalized["warnings"] = _string_list((normalized.get("warnings") or []) + warnings)
    return ValidationResult(True, normalized=normalized, warnings=warnings)
