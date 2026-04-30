"""AI Scene Planner integration.

This module exposes services for preview and commit, and integrates with the add-on via HTTP.
"""
import logging
from typing import Any
from .services import commit_service, execute_service, generate_service, preview_service

try:
    from homeassistant.core import HomeAssistant
except ModuleNotFoundError:  # Allows local addon tests without Home Assistant installed.
    HomeAssistant = Any

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict):
    _LOGGER.info("Setting up AI Scene Planner integration")
    # Register services
    async def _preview(call):
        await preview_service(hass, call)

    async def _commit(call):
        await commit_service(hass, call)

    async def _generate(call):
        await generate_service(hass, call)

    async def _execute(call):
        await execute_service(hass, call)

    hass.services.async_register("ai_scene", "generate_scene", _generate)
    hass.services.async_register("ai_scene", "preview", _preview)
    hass.services.async_register("ai_scene", "commit", _commit)
    hass.services.async_register("ai_scene", "execute_scene", _execute)
    return True


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    return True
