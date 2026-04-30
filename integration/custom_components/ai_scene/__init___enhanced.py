"""AI Scene Planner - Home Assistant custom integration.

Provides scene generation, preview, and execution via AI orchestration.
Handles discovery, capability mapping, and scene lifecycle management.
"""
import logging
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SCENE]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AI Scene Planner from config entry."""
    _LOGGER.info("Setting up AI Scene Planner")
    
    # Store entry data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data
    
    # Register services
    async def handle_generate_scene(call: ServiceCall) -> None:
        """Handle generate scene service call."""
        _LOGGER.info("Generate scene service called")
        _LOGGER.debug("Call data: %s", call.data)
        # Actual implementation delegates to add-on via HTTP
        # (see services.py)
    
    async def handle_preview_scene(call: ServiceCall) -> None:
        """Handle preview scene service call."""
        _LOGGER.info("Preview scene service called")
    
    async def handle_commit_scene(call: ServiceCall) -> None:
        """Handle commit scene service call."""
        _LOGGER.info("Commit scene service called")
    
    async def handle_execute_scene(call: ServiceCall) -> None:
        """Handle execute scene service call."""
        _LOGGER.info("Execute scene service called")
    
    # Register service calls
    hass.services.async_register(
        DOMAIN, "generate_scene", handle_generate_scene,
        description="Generate a scene from prompt and entities"
    )
    
    hass.services.async_register(
        DOMAIN, "preview_scene", handle_preview_scene,
        description="Preview a scene without execution"
    )
    
    hass.services.async_register(
        DOMAIN, "commit_scene", handle_commit_scene,
        description="Commit a draft scene for execution"
    )
    
    hass.services.async_register(
        DOMAIN, "execute_scene", handle_execute_scene,
        description="Execute a committed scene"
    )
    
    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    _LOGGER.info("AI Scene Planner setup complete")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading AI Scene Planner")
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if entry.entry_id in hass.data.get(DOMAIN, {}):
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    _LOGGER.info("Reloading AI Scene Planner")
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
