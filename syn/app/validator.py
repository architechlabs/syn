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


def _entity_summary(entity: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "entity_id": entity.get("entity_id"),
        "domain": entity.get("domain"),
        "capabilities": sorted(_normalize_caps(entity)),
    }


def _entity_label(entity: Dict[str, Any]) -> str:
    return str(
        entity.get("name")
        or (entity.get("state") or {}).get("attributes", {}).get("friendly_name")
        or entity.get("entity_id")
        or "selected device"
    )


def _is_dim_scene(scene: Dict[str, Any]) -> bool:
    text = " ".join(
        str(scene.get(key) or "")
        for key in ("scene_name", "description", "intent", "target_room")
    ).lower()
    return any(word in text for word in ("movie", "cinema", "cozy", "cosy", "night", "relax", "dim", "sleep"))


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
        repaired["actions"].append(
            {
                "entity_id": eid,
                "domain": domain,
                "service": service,
                "data": data,
                "rationale": str(action.get("rationale") or action.get("reason") or "Generated by Syn"),
                "priority": int(action.get("priority", max(0, 100 - index))),
            }
        )

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

    if tuned.get("domain") == "light" and tuned.get("service") == "turn_on" and _is_dim_scene(scene):
        if "brightness" in caps:
            old_brightness = data.get("brightness")
            if old_brightness is None or (
                isinstance(old_brightness, int)
                and 0 <= old_brightness <= 255
                and old_brightness > 90
            ):
                data["brightness"] = 64
                warnings.append(f"Tuned {entity_id} brightness for a cozy/movie/night scene")
        if "color_temp" in caps and "color_temp" not in data:
            data["color_temp"] = 370
            warnings.append(f"Added warm color temperature for {entity_id}")

    rationale = str(tuned.get("rationale") or "").strip()
    if not rationale or any(word in rationale.lower() for word in ("living room", "fan", "tv", "television", "hallway")):
        tuned["rationale"] = f"Set {label} for {scene.get('scene_name') or scene.get('intent') or 'the requested scene'}"

    tuned["data"] = data
    return tuned


def _dedupe_actions(actions: List[Dict[str, Any]], warnings: List[str]) -> List[Dict[str, Any]]:
    deduped: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    ordered_keys: List[tuple[str, str, str]] = []

    for action in actions:
        key = (action.get("entity_id"), action.get("domain"), action.get("service"))
        if key not in deduped:
            deduped[key] = action
            ordered_keys.append(key)
            continue

        existing = deduped[key]
        existing["data"] = {**(existing.get("data") or {}), **(action.get("data") or {})}
        existing["priority"] = max(existing.get("priority", 0), action.get("priority", 0))
        if action.get("rationale") and not existing.get("rationale"):
            existing["rationale"] = action.get("rationale")
        warnings.append(f"Merged duplicate {key[1]}.{key[2]} action for {key[0]}")

    return [deduped[key] for key in ordered_keys]


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
    normalized_actions = _dedupe_actions(normalized_actions, warnings)
    normalized["actions"] = sorted(normalized_actions, key=lambda item: item.get("priority", 0), reverse=True)
    normalized["warnings"] = _string_list((normalized.get("warnings") or []) + warnings)
    return ValidationResult(True, normalized=normalized, warnings=warnings)
