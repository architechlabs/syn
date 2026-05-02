"""Home Assistant scene entities backed by Syn saved drafts."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from .const import ADDON_DEFAULT_URL, DOMAIN

try:
    from homeassistant.components.scene import Scene
    from homeassistant.exceptions import HomeAssistantError
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from homeassistant.helpers.event import async_track_time_interval
except ModuleNotFoundError:  # Allows local tests without Home Assistant installed.
    Scene = object
    HomeAssistantError = RuntimeError
    async_get_clientsession = None
    async_track_time_interval = None

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)


def _addon_url(hass) -> str:
    return (hass.data.get("ai_scene_addon_url") or ADDON_DEFAULT_URL).rstrip("/")


async def _request_json(hass, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{_addon_url(hass)}{path}"
    if async_get_clientsession is not None:
        session = async_get_clientsession(hass)
        async with asyncio.timeout(25):
            async with session.request(method, url, json=payload) as response:
                response.raise_for_status()
                return await response.json()

    import httpx

    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.request(method, url, json=payload)
        response.raise_for_status()
        return response.json()


async def _list_scene_summaries(hass) -> list[dict[str, Any]]:
    data = await _request_json(hass, "GET", "/scenes")
    scenes = data.get("scenes", [])
    return scenes if isinstance(scenes, list) else []


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up Syn saved drafts as Home Assistant scene entities."""

    domain_data = hass.data.setdefault(DOMAIN, {})
    entities_by_id: dict[str, SynSavedScene] = domain_data.setdefault("scene_entities", {})

    async def refresh_scenes(_now=None) -> None:
        try:
            summaries = await _list_scene_summaries(hass)
        except Exception as exc:
            _LOGGER.warning("Unable to refresh Syn scenes from add-on: %s", exc)
            return

        active_ids = {summary.get("id") for summary in summaries if summary.get("id")}
        for scene_id in list(entities_by_id):
            if scene_id not in active_ids:
                entity = entities_by_id.pop(scene_id)
                if hasattr(entity, "async_remove"):
                    await entity.async_remove()

        new_entities = []
        for summary in summaries:
            scene_id = summary.get("id")
            if not scene_id:
                continue
            if scene_id in entities_by_id:
                entities_by_id[scene_id].summary = summary
                entities_by_id[scene_id].async_write_ha_state()
                continue
            entity = SynSavedScene(hass, summary)
            entities_by_id[scene_id] = entity
            new_entities.append(entity)

        if new_entities:
            async_add_entities(new_entities, True)

    await refresh_scenes()

    if async_track_time_interval is not None:
        remove_listener = async_track_time_interval(hass, refresh_scenes, SCAN_INTERVAL)
        entry.async_on_unload(remove_listener)


class SynSavedScene(Scene):
    """A saved Syn scene draft that can be activated like a normal HA scene."""

    _attr_icon = "mdi:creation"
    _attr_has_entity_name = True

    def __init__(self, hass, summary: dict[str, Any]) -> None:
        self.hass = hass
        self.summary = summary
        self.scene_id = summary["id"]
        self._attr_unique_id = f"syn_{self.scene_id}"
        self._attr_name = summary.get("name") or self.scene_id

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "status": self.summary.get("status"),
            "target_room": self.summary.get("target_room"),
            "description": self.summary.get("description"),
            "action_count": self.summary.get("action_count", 0),
            "controlled_entities": self.summary.get("controlled_entities", []),
            "created": self.summary.get("created"),
            "updated": self.summary.get("updated"),
            "source": "Syn add-on",
        }

    async def async_activate(self, **kwargs: Any) -> None:
        detail = await _request_json(self.hass, "GET", f"/get_scene/{self.scene_id}")
        scene = detail.get("scene", detail)
        if not isinstance(scene, dict):
            raise HomeAssistantError(f"Syn scene {self.scene_id} did not return a scene payload")

        result = await _request_json(self.hass, "POST", "/execute_scene", {"scene": scene})
        if result.get("overall_status") in {"failed", "partial_failure"}:
            raise HomeAssistantError(result.get("message") or f"Syn scene {self.scene_id} failed")

    async def async_update(self) -> None:
        try:
            summaries = await _list_scene_summaries(self.hass)
        except Exception:
            return
        for summary in summaries:
            if summary.get("id") == self.scene_id:
                self.summary = summary
                self._attr_name = summary.get("name") or self.scene_id
                return
