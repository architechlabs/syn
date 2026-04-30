"""Scene execution engine - applies validated scene actions via HA services."""
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import logging
from typing import Dict, Any, List, Tuple

_LOGGER = logging.getLogger(__name__)


class SceneExecutor:
    """Executes validated scene plans against Home Assistant entities."""
    
    def __init__(self, hass: HomeAssistant):
        self.hass = hass
    
    async def execute_scene(self, scene: Dict[str, Any]) -> Dict[str, Any]:
        """Execute all actions in a validated scene.
        
        Returns execution report with per-action status.
        """
        results = {
            "scene_name": scene.get("scene_name", "Unknown"),
            "actions_executed": 0,
            "actions_failed": 0,
            "actions": [],
            "errors": []
        }
        
        for idx, action in enumerate(scene.get("actions", [])):
            entity_id = action.get("entity_id")
            domain = action.get("domain")
            service = action.get("service")
            data = action.get("data", {})
            
            # Prepare service call
            service_data = {**data, "entity_id": entity_id}
            
            try:
                _LOGGER.debug("Executing action %d: %s.%s on %s with %s",
                            idx, domain, service, entity_id, service_data)
                
                # Call HA service
                await self.hass.services.async_call(
                    domain,
                    service,
                    service_data,
                    blocking=True
                )
                
                results["actions_executed"] += 1
                results["actions"].append({
                    "entity_id": entity_id,
                    "service": f"{domain}.{service}",
                    "status": "success",
                    "data": service_data
                })
                _LOGGER.info("Action executed: %s.%s on %s", domain, service, entity_id)
            
            except HomeAssistantError as e:
                results["actions_failed"] += 1
                error_msg = f"HA error on {entity_id}: {str(e)}"
                results["errors"].append(error_msg)
                results["actions"].append({
                    "entity_id": entity_id,
                    "service": f"{domain}.{service}",
                    "status": "error",
                    "error": error_msg
                })
                _LOGGER.error(error_msg)
            
            except Exception as e:
                results["actions_failed"] += 1
                error_msg = f"Unexpected error on {entity_id}: {str(e)}"
                results["errors"].append(error_msg)
                results["actions"].append({
                    "entity_id": entity_id,
                    "service": f"{domain}.{service}",
                    "status": "error",
                    "error": error_msg
                })
                _LOGGER.exception(error_msg)
        
        results["overall_status"] = "success" if results["actions_failed"] == 0 else "partial_failure"
        _LOGGER.info("Scene execution complete: %s/%s actions succeeded",
                    results["actions_executed"],
                    results["actions_executed"] + results["actions_failed"])
        
        return results
    
    async def preview_scene(self, scene: Dict[str, Any]) -> Dict[str, Any]:
        """Generate preview of what actions would do (without execution)."""
        preview = {
            "scene_name": scene.get("scene_name"),
            "actions": [],
            "warnings": []
        }
        
        for action in scene.get("actions", []):
            entity_id = action.get("entity_id")
            state = self.hass.states.get(entity_id)
            
            if not state:
                preview["warnings"].append(f"Entity {entity_id} not found in Home Assistant")
                continue
            
            domain = action.get("domain")
            service = action.get("service")
            data = action.get("data", {})
            
            preview["actions"].append({
                "entity_id": entity_id,
                "domain": domain,
                "service": service,
                "current_state": state.state,
                "requested_data": data,
                "rationale": action.get("rationale", "")
            })
        
        return preview


async def rollback_scene(hass: HomeAssistant, previous_states: Dict[str, str]) -> Dict[str, Any]:
    """Rollback entities to previous states.
    
    Args:
        hass: Home Assistant instance
        previous_states: Dict mapping entity_id to previous state
    
    Returns:
        Rollback result report
    """
    results = {"rolled_back": 0, "failed": 0, "errors": []}
    
    for entity_id, prev_state in previous_states.items():
        try:
            domain = entity_id.split(".")[0]
            # For lights: turn on/off based on prev_state
            if domain == "light":
                service = "turn_on" if prev_state == "on" else "turn_off"
                await hass.services.async_call(domain, service, {"entity_id": entity_id})
                results["rolled_back"] += 1
                _LOGGER.info("Rolled back %s to %s", entity_id, prev_state)
            # Add similar logic for other domains as needed
        except Exception as e:
            results["failed"] += 1
            error = f"Rollback failed for {entity_id}: {str(e)}"
            results["errors"].append(error)
            _LOGGER.error(error)
    
    return results
