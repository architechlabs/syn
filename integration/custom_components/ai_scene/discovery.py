from typing import List, Dict, Any, Optional

from .capability_registry import DOMAIN_CAPABILITIES


def extract_capabilities(domain: str, state_obj) -> List[str]:
    """Infer AI-safe capabilities from Home Assistant state attributes."""
    attrs = dict(getattr(state_obj, "attributes", {}) or {})
    caps = {"on_off"} if domain in DOMAIN_CAPABILITIES else set()

    if domain == "light":
        supported = attrs.get("supported_color_modes") or []
        if "brightness" in attrs or "brightness" in supported:
            caps.add("brightness")
        if "color_temp" in attrs or "color_temp" in supported or "min_color_temp_kelvin" in attrs:
            caps.add("color_temp")
        if "rgb_color" in attrs or "hs" in supported or "rgb" in supported:
            caps.add("rgb_color")
        if "xy_color" in attrs or "xy" in supported:
            caps.add("xy_color")
        if attrs.get("effect_list"):
            caps.add("effect")
        if "transition" in attrs:
            caps.add("transition")
    elif domain == "media_player":
        if "volume_level" in attrs:
            caps.add("volume")
        if "is_volume_muted" in attrs:
            caps.add("mute")
        if attrs.get("source_list"):
            caps.add("source")
        caps.add("media_control")
    elif domain == "fan":
        if "percentage" in attrs or attrs.get("percentage_step"):
            caps.add("percentage")
        if "oscillating" in attrs:
            caps.add("oscillate")
        if "direction" in attrs:
            caps.add("direction")

    return sorted(caps)


async def discover_room_entities(hass, room_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return entities with capabilities and current state for a room."""
    entities = []
    all_states = hass.states.async_all()
    if isinstance(all_states, dict):
        states = all_states.values()
    else:
        states = all_states

    for state in states:
        entity_id = getattr(state, "entity_id", None)
        if not entity_id or "." not in entity_id:
            continue
        domain = entity_id.split(".", 1)[0]
        if domain not in DOMAIN_CAPABILITIES:
            continue

        attrs = dict(getattr(state, "attributes", {}) or {})
        area_id = attrs.get("area_id") or attrs.get("room")
        if room_id and area_id and area_id != room_id:
            continue

        entities.append(
            {
                "entity_id": entity_id,
                "domain": domain,
                "capabilities": extract_capabilities(domain, state),
                "state": {
                    "value": getattr(state, "state", "unknown"),
                    "attributes": attrs,
                },
                "room": area_id or room_id,
            }
        )
    return entities
