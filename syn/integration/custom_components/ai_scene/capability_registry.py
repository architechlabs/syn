"""Registry mapping HA domains/services to capabilities and supported actions."""
from typing import Dict, List

DOMAIN_CAPABILITIES: Dict[str, List[str]] = {
    "light": ["on_off", "brightness", "color_temp", "rgb_color", "xy_color", "effect", "transition"],
    "switch": ["on_off"],
    "fan": ["on_off", "percentage", "oscillate", "direction"],
    "media_player": ["on_off", "volume", "source", "mute", "media_control"],
}

SERVICE_WHITELIST = {
    "light": ["turn_on", "turn_off", "toggle"],
    "switch": ["turn_on", "turn_off", "toggle"],
    "fan": ["turn_on", "turn_off", "set_percentage", "oscillate"],
    "media_player": ["turn_on", "turn_off", "volume_set", "volume_mute", "select_source", "media_play", "media_pause"],
}
