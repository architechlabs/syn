import logging
from typing import Dict, Any, List

try:
    from homeassistant.core import HomeAssistant
except ModuleNotFoundError:  # Allows local addon tests without Home Assistant installed.
    HomeAssistant = Any

_LOGGER = logging.getLogger(__name__)


async def execute_scene(hass: HomeAssistant, scene: Dict[str, Any]) -> Dict[str, Any]:
    """Execute validated scene actions using Home Assistant services.

    Returns a result object listing applied actions and any failures.
    """
    results: List[Dict[str, Any]] = []
    errors: List[str] = []
    ordered_actions = sorted(scene.get("actions", []), key=lambda item: item.get("priority", 0), reverse=True)
    for action in ordered_actions:
        domain = action.get("domain")
        service = action.get("service")
        data = action.get("data", {})
        entity = action.get("entity_id")
        if not domain or not service or not entity:
            error = f"Invalid action missing domain/service/entity: {action}"
            errors.append(error)
            results.append({"entity": entity, "status": "error", "error": error})
            continue
        try:
            await hass.services.async_call(domain, service, {**data, "entity_id": entity}, blocking=True)
            results.append({"entity": entity, "service": f"{domain}.{service}", "status": "success"})
        except Exception as e:
            _LOGGER.exception("Failed action %s on %s", service, entity)
            errors.append(str(e))
            results.append({"entity": entity, "service": f"{domain}.{service}", "status": "error", "error": str(e)})
    return {
        "scene_name": scene.get("scene_name"),
        "actions_executed": sum(1 for result in results if result["status"] == "success"),
        "actions_failed": sum(1 for result in results if result["status"] == "error"),
        "overall_status": "success" if not errors else "partial_failure",
        "errors": errors,
        "actions": results,
        "results": results,
    }
