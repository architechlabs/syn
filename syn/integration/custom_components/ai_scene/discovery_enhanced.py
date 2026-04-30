"""Discovery and capability mapping for Home Assistant entities."""
from typing import List, Dict, Any, Optional
import logging

_LOGGER = logging.getLogger(__name__)

# Map HA domains to their capabilities
DOMAIN_CAPABILITIES = {
    "light": ["on_off", "brightness", "color_temp", "rgb_color", "xy_color", "effect", "transition"],
    "switch": ["on_off"],
    "fan": ["on_off", "speed", "percentage", "oscillate", "direction"],
    "media_player": ["on_off", "volume", "mute", "source", "app_id"],
    "climate": ["target_temp", "mode", "preset"],
}

# Map services to domains
SERVICE_TO_DOMAIN = {
    "turn_on": ["light", "switch", "fan", "media_player", "climate"],
    "turn_off": ["light", "switch", "fan", "media_player"],
    "toggle": ["light", "switch"],
    "set_brightness": ["light"],
    "set_color_temp": ["light"],
    "set_color": ["light"],
    "set_effect": ["light"],
    "volume_set": ["media_player"],
    "mute": ["media_player"],
    "select_source": ["media_player"],
}

# Whitelisted services per domain
WHITELISTED_SERVICES = {
    "light": {"turn_on", "turn_off", "toggle", "set_brightness", "set_color_temp", "set_color"},
    "switch": {"turn_on", "turn_off", "toggle"},
    "fan": {"turn_on", "turn_off", "set_speed"},
    "media_player": {"turn_on", "turn_off", "volume_set", "mute", "select_source"},
}


async def discover_room_entities(hass, room_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Discover entities in a room with full capability metadata.
    
    Args:
        hass: Home Assistant instance
        room_id: Room ID to filter by (optional, returns all if None)
    
    Returns:
        List of entity dicts with capabilities and state.
    """
    entities = []
    
    # Get area registry to map room_id to area
    area_registry = hass.data.get("area_registry")
    device_registry = hass.data.get("device_registry")
    entity_registry = hass.data.get("entity_registry")
    
    for entity_id, state_obj in hass.states.async_all(domain=None):
        domain, _ = entity_id.split(".")
        if domain not in DOMAIN_CAPABILITIES:
            continue
        
        # Get entity metadata
        ent_reg = entity_registry.get(entity_id) if entity_registry else None
        device_id = ent_reg.device_id if ent_reg else None
        
        # Check if entity matches room filter
        if room_id and device_id and device_registry:
            device = device_registry.devices.get(device_id)
            if not device or device.area_id != room_id:
                continue
        
        # Extract capabilities from entity attributes
        caps = extract_capabilities(domain, state_obj)
        
        entities.append({
            "entity_id": entity_id,
            "domain": domain,
            "capabilities": caps,
            "state": {
                "value": state_obj.state,
                "attributes": dict(state_obj.attributes) if state_obj.attributes else {}
            },
            "room": room_id or "unknown"
        })
    
    _LOGGER.debug("Discovered %d entities in room %s", len(entities), room_id or "all")
    return entities


def extract_capabilities(domain: str, state_obj) -> List[str]:
    """Extract capabilities from entity state and attributes."""
    caps = []
    
    if domain == "light":
        attrs = state_obj.attributes or {}
        if "brightness" in attrs or state_obj.state in ["on", "off"]:
            caps.append("on_off")
        if "brightness" in attrs:
            caps.append("brightness")
        if "color_temp" in attrs or "min_color_temp" in attrs:
            caps.append("color_temp")
        if "color" in attrs or "xy_color" in attrs:
            caps.append("rgb_color")
        if "effect_list" in attrs:
            caps.append("effect")
    
    elif domain == "media_player":
        attrs = state_obj.attributes or {}
        caps.append("on_off")
        if "volume_level" in attrs:
            caps.append("volume")
        if "mute" in attrs or "is_volume_muted" in attrs:
            caps.append("mute")
        if "source_list" in attrs:
            caps.append("source")
    
    elif domain == "fan":
        attrs = state_obj.attributes or {}
        caps.append("on_off")
        if "speed" in attrs or "speed_list" in attrs:
            caps.append("speed")
        if "percentage" in attrs:
            caps.append("percentage")
    
    elif domain == "switch":
        caps.append("on_off")
    
    elif domain == "climate":
        attrs = state_obj.attributes or {}
        if "temperature" in attrs:
            caps.append("target_temp")
        if "hvac_modes" in attrs:
            caps.append("mode")
    
    return caps


def validate_service_for_domain(domain: str, service: str) -> bool:
    """Check if service is whitelisted for domain."""
    allowed = WHITELISTED_SERVICES.get(domain, set())
    return service in allowed


def get_default_capability_value(domain: str, capability: str, current_state: Dict) -> Any:
    """Get safe default value for a capability."""
    defaults = {
        "on_off": {"value": "on"},
        "brightness": {"min": 0, "max": 255, "default": 128},
        "color_temp": {"min": 2000, "max": 6500, "default": 4000},
        "rgb_color": {"default": [255, 255, 255]},
        "volume": {"min": 0, "max": 1.0, "default": 0.5},
    }
    return defaults.get(capability, {})
