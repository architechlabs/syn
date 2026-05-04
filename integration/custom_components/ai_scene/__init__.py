"""AI Scene Planner integration.

This module exposes services for preview and commit, and integrates with the add-on via HTTP.
"""
import logging
from typing import Any
from .services import (
    commit_service,
    deactivate_scene_service,
    execute_service,
    generate_service,
    preview_service,
    start_scene_service,
    stop_scene_service,
)
from .const import ADDON_DEFAULT_URL, DOMAIN, PLATFORMS

try:
    from homeassistant.core import HomeAssistant
except ModuleNotFoundError:  # Allows local addon tests without Home Assistant installed.
    HomeAssistant = Any

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict):
    _LOGGER.info("Setting up AI Scene Planner integration")
    hass.data.setdefault(DOMAIN, {})
    if hass.data[DOMAIN].get("services_registered"):
        return True
    # Register services
    async def _preview(call):
        await preview_service(hass, call)

    async def _commit(call):
        await commit_service(hass, call)

    async def _generate(call):
        await generate_service(hass, call)

    async def _execute(call):
        await execute_service(hass, call)

    async def _start_scene(call):
        await start_scene_service(hass, call)

    async def _stop_scene(call):
        await stop_scene_service(hass, call)

    async def _deactivate_scene(call):
        await deactivate_scene_service(hass, call)

    hass.services.async_register("ai_scene", "generate_scene", _generate)
    hass.services.async_register("ai_scene", "preview", _preview)
    hass.services.async_register("ai_scene", "commit", _commit)
    hass.services.async_register("ai_scene", "execute_scene", _execute)
    hass.services.async_register("ai_scene", "start_scene", _start_scene)
    hass.services.async_register("ai_scene", "stop_scene", _stop_scene)
    hass.services.async_register("ai_scene", "deactivate_scene", _deactivate_scene)
    hass.data[DOMAIN]["services_registered"] = True
    return True


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    """Set up AI Scene Planner from the UI."""

    hass.data.setdefault(DOMAIN, {})
    hass.data["ai_scene_addon_url"] = entry.data.get("addon_url") or ADDON_DEFAULT_URL
    await async_setup(hass, {})
    if hasattr(hass.config_entries, "async_forward_entry_setups"):
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    else:
        for platform in PLATFORMS:
            hass.async_create_task(hass.config_entries.async_forward_entry_setup(entry, platform))
    return True


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    if hasattr(hass.config_entries, "async_unload_platforms"):
        return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return True
