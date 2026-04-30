from jsonschema import validate
from jsonschema.exceptions import ValidationError
from typing import Any, Dict, List
import json
import os
import logging

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


def _as_dict(value: Any) -> Dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value or {}


def _normalize_caps(entity: Dict[str, Any]) -> set[str]:
    caps = set(entity.get("capabilities", []) or [])
    attrs = (entity.get("state") or {}).get("attributes", {}) or {}
    if entity.get("domain") in {"light", "switch", "fan", "media_player"}:
        caps.add("on_off")
    if "brightness" in attrs:
        caps.add("brightness")
    if "color_temp" in attrs or "min_color_temp" in attrs:
        caps.add("color_temp")
    if "rgb_color" in attrs or "xy_color" in attrs:
        caps.add("rgb_color")
    if "volume_level" in attrs:
        caps.add("volume")
    if "source_list" in attrs:
        caps.add("source")
    if "is_volume_muted" in attrs:
        caps.add("mute")
    return {CAPABILITY_ALIASES.get(cap, cap) for cap in caps}


def _normalize_action_data(
    entity_id: str,
    domain: str,
    service: str,
    data: Dict[str, Any],
    caps: set[str],
    warnings: List[str],
) -> Dict[str, Any]:
    normalized = dict(data or {})

    if domain == "light":
        if "color" in normalized and "rgb_color" not in normalized:
            normalized["rgb_color"] = normalized.pop("color")
        allowed_keys = {"brightness", "color_temp", "rgb_color", "xy_color", "effect", "transition"}
        for key in list(normalized):
            if key not in allowed_keys:
                warnings.append(f"Removed unsupported light data '{key}' for {entity_id}")
                normalized.pop(key, None)
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


def validate_and_normalize(raw: Any, available_entities: List[Dict[str, Any]]) -> ValidationResult:
    schema_path = os.path.join(os.path.dirname(__file__), "schema", "scene_schema.json")
    with open(schema_path, "r", encoding="utf-8") as fh:
        schema = json.load(fh)

    try:
        validate(instance=raw, schema=schema)
    except ValidationError as e:
        logger.warning("Schema validation failed: %s", e.message)
        return ValidationResult(False, errors=[str(e.message)])

    # Semantic checks
    entities = [_as_dict(e) for e in available_entities]
    entity_map = {e["entity_id"]: e for e in entities if e.get("entity_id")}
    errors = []
    warnings = []
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

        try:
            data = _normalize_action_data(
                eid,
                domain,
                service,
                data,
                _normalize_caps(entity_map[eid]),
                warnings,
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue

        normalized_actions.append({
            "entity_id": eid,
            "domain": domain,
            "service": service,
            "data": data,
            "rationale": a.get("rationale"),
            "priority": a.get("priority", 0),
        })

    if errors:
        return ValidationResult(False, errors=errors)

    normalized = raw.copy()
    normalized["actions"] = sorted(normalized_actions, key=lambda item: item.get("priority", 0), reverse=True)
    normalized["warnings"] = list(dict.fromkeys((normalized.get("warnings") or []) + warnings))
    return ValidationResult(True, normalized=normalized, warnings=warnings)
