"""Switch entities that activate/deactivate saved Syn scenes."""

from __future__ import annotations

import logging
from typing import Any

from .const import DOMAIN
from .scene import SCAN_INTERVAL, _list_scene_summaries, _request_json

try:
    from homeassistant.components.switch import SwitchEntity
    from homeassistant.exceptions import HomeAssistantError
    from homeassistant.helpers.event import async_track_time_interval
except ModuleNotFoundError:  # Allows local tests without Home Assistant installed.
    SwitchEntity = object
    HomeAssistantError = RuntimeError
    async_track_time_interval = None

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Expose each saved Syn scene as an on/off switch."""

    domain_data = hass.data.setdefault(DOMAIN, {})
    entities_by_id: dict[str, SynSceneSwitch] = domain_data.setdefault("scene_switch_entities", {})

    async def refresh_scenes(_now=None) -> None:
        try:
            summaries = await _list_scene_summaries(hass)
        except Exception as exc:
            _LOGGER.warning("Unable to refresh Syn scene switches from add-on: %s", exc)
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
                if summary.get("is_animated"):
                    entities_by_id[scene_id]._attr_is_on = bool(summary.get("running"))
                entities_by_id[scene_id].async_write_ha_state()
                continue
            entity = SynSceneSwitch(hass, summary)
            entities_by_id[scene_id] = entity
            new_entities.append(entity)

        if new_entities:
            async_add_entities(new_entities, True)

    await refresh_scenes()

    if async_track_time_interval is not None:
        remove_listener = async_track_time_interval(hass, refresh_scenes, SCAN_INTERVAL)
        entry.async_on_unload(remove_listener)


class SynSceneSwitch(SwitchEntity):
    """Switch that turns a saved Syn scene on or off."""

    _attr_icon = "mdi:creation-outline"
    _attr_has_entity_name = True

    def __init__(self, hass, summary: dict[str, Any]) -> None:
        self.hass = hass
        self.summary = summary
        self.scene_id = summary["id"]
        self._attr_unique_id = f"syn_{self.scene_id}_control"
        self._attr_name = f"{summary.get('name') or self.scene_id} control"
        self._attr_is_on = False

    @property
    def is_on(self) -> bool:
        return self._attr_is_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "target_room": self.summary.get("target_room"),
            "description": self.summary.get("description"),
            "automation": self.summary.get("automation"),
            "is_animated": self.summary.get("is_animated", False),
            "running": self.summary.get("running", False),
            "runtime": self.summary.get("runtime"),
            "haos": self.summary.get("haos"),
            "action_count": self.summary.get("action_count", 0),
            "controlled_entities": self.summary.get("controlled_entities", []),
            "source": "Syn add-on",
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        result = await _request_json(self.hass, "POST", f"/start_scene/{self.scene_id}")
        nested = result.get("result") if isinstance(result.get("result"), dict) else {}
        if result.get("ok") is False or nested.get("overall_status") == "failed":
            raise HomeAssistantError(result.get("message") or f"Syn scene {self.scene_id} failed")
        self._attr_is_on = True

    async def async_turn_off(self, **kwargs: Any) -> None:
        result = await _request_json(self.hass, "POST", f"/deactivate_scene/{self.scene_id}")
        if result.get("overall_status") == "failed":
            raise HomeAssistantError(result.get("message") or f"Syn scene {self.scene_id} failed to deactivate")
        self._attr_is_on = False
