from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from .models import ScenePlanRequest, ScenePlanResponse
from .auto_select import auto_select_entities
from .prompt_builder import build_prompt
from .ai_client import AIProviderError, AIProviderTimeout, call_ai_model
from .ha_client import discovery_status as get_discovery_status
from .ha_client import execute_scene_actions
from .ha_client import load_ha_api_settings
from .ha_client import list_areas, list_entities
from .native_export import export_scene_to_home_assistant, remove_scene_from_home_assistant
from .validator import validate_and_normalize
from .storage import SceneStorage
from .storage import BASE as SCENES_PATH
from .runtime import SceneRuntimeManager
from .logger import get_logger
from .settings import load_ai_settings, mask_secret
from .version_sync import (
    DEFAULT_HA_CONFIG_PATH,
    ensure_integration_installed,
    resolve_ha_config_path,
    sync_integration_manifest,
)
from .ui import INDEX_HTML

logger = get_logger("addon.main")
app = FastAPI(title="AI Scene Planner")
storage = SceneStorage()
runtime = SceneRuntimeManager(logger)


async def _with_discovered_entities(request: ScenePlanRequest) -> ScenePlanRequest:
    if request.entities:
        return request
    if not request.auto_select:
        return request
    discovered = await list_entities(request.room_id)
    selected = auto_select_entities(
        discovered,
        prompt=request.user_prompt,
        room_id=request.room_id,
    )
    constraints = dict(request.constraints or {})
    constraints["auto_selected"] = True
    constraints["auto_selected_count"] = len(selected)
    constraints["available_entity_count"] = len(discovered)
    logger.info(
        "Auto-selected %d of %d discovered entities for prompt '%s'",
        len(selected),
        len(discovered),
        (request.user_prompt or "")[:80],
    )
    return request.model_copy(update={"entities": selected, "constraints": constraints})


def _require_entities(request: ScenePlanRequest) -> None:
    if request.entities:
        return
    raise HTTPException(
        status_code=400,
        detail={
            "message": "No controllable entities were selected or discovered.",
            "fix": "Refresh entities, clear the room filter, or assign devices to an Area in Home Assistant.",
        },
    )


def _ai_error_response(exc: Exception) -> HTTPException:
    if isinstance(exc, AIProviderTimeout):
        return HTTPException(status_code=504, detail=str(exc))
    if isinstance(exc, AIProviderError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=502, detail="AI provider failed to return a usable scene")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index():
    """Serve the add-on web UI at the ingress root."""
    return INDEX_HTML


@app.get("/config_status")
async def config_status():
    settings = load_ai_settings()
    ha_settings = load_ha_api_settings()
    return {
        "api_key_configured": settings.has_api_key,
        "api_key": mask_secret(settings.api_key),
        "base_url": settings.base_url,
        "model": settings.model,
        "provider_preset": settings.provider_preset,
        "enable_thinking": settings.enable_thinking,
        "temperature": settings.temperature,
        "request_timeout": settings.request_timeout,
        "max_tokens": settings.max_tokens,
        "fallback_on_error": settings.fallback_on_error,
        "options_path": str(settings.options_path),
        "storage": {
            "draft_scene_path": SCENES_PATH,
        },
        "home_assistant": {
            "api_url": ha_settings.base_url,
            "token_configured": ha_settings.configured,
            "token_source": ha_settings.source,
            "token": ha_settings.masked_token,
        },
    }


@app.get("/areas")
async def areas():
    return {"areas": await list_areas()}


@app.get("/entities")
async def entities(room_id: str | None = None):
    discovered = await list_entities(room_id)
    return {"entities": discovered, "count": len(discovered)}


@app.get("/discovery_status")
async def discovery_status():
    return await get_discovery_status()


@app.on_event("startup")
async def sync_versions_on_startup() -> None:
    """Keep the integration manifest aligned with the add-on version."""

    try:
        result = sync_integration_manifest()
        if result.updated:
            logger.info(
                "Synchronized integration manifest version to %s",
                result.integration_version,
            )
    except FileNotFoundError as exc:
        logger.warning("Version sync skipped because %s is unavailable", exc)

    ha_config_path = resolve_ha_config_path()
    try:
        install = ensure_integration_installed(ha_config_path)
        logger.info("Integration installed/updated at %s", install.target_path)
    except FileNotFoundError as exc:
        if ha_config_path == DEFAULT_HA_CONFIG_PATH and not ha_config_path.exists():
            logger.warning(
                "Integration install skipped because Home Assistant config path %s is unavailable",
                ha_config_path,
            )
        else:
            logger.error("Integration install failed because %s is unavailable", exc)
    except Exception:
        logger.exception("Integration install failed")

    settings = load_ai_settings()
    logger.info(
        "AI settings loaded from %s: api_key=%s model=%s preset=%s thinking=%s temperature=%s timeout=%ss max_tokens=%s",
        settings.options_path,
        mask_secret(settings.api_key),
        settings.model,
        settings.provider_preset,
        settings.enable_thinking,
        settings.temperature,
        settings.request_timeout,
        settings.max_tokens,
    )


@app.on_event("shutdown")
async def stop_runtime_on_shutdown() -> None:
    await runtime.stop_all()


@app.post("/generate_scene", response_model=ScenePlanResponse)
async def generate_scene(request: ScenePlanRequest):
    """Generate a scene plan from prompt + entities."""
    request = await _with_discovered_entities(request)
    _require_entities(request)
    prompt = build_prompt(request)
    logger.info("Building prompt for scene generation with %d entities", len(request.entities))
    try:
        raw = await call_ai_model(prompt)
    except Exception as exc:
        logger.warning("AI call failed: %s", exc)
        raise _ai_error_response(exc) from exc

    logger.debug("Raw AI response captured")
    validated = validate_and_normalize(raw, request.entities)
    if not validated.is_valid:
        logger.warning("Validation failed: %s", validated.errors)
        return JSONResponse(status_code=400, content={"errors": validated.errors, "warnings": validated.warnings})

    scene = validated.normalized
    # persist draft
    scene_id = await storage.save_scene(scene)
    export = await export_scene_to_home_assistant(scene_id, scene, logger=logger)
    if export.get("ok"):
        await storage.update_scene(scene_id, scene)
    else:
        validated.warnings.append(export.get("message", "Native Home Assistant export failed."))
    logger.info("Scene draft saved: %s at %s", scene_id, SCENES_PATH)
    return ScenePlanResponse.from_dict(
        {"scene": scene, "scene_id": scene_id, "warnings": validated.warnings, "export": export}
    )


@app.get("/get_scene/{scene_id}")
async def get_scene(scene_id: str):
    data = await storage.get_scene(scene_id)
    if not data:
        raise HTTPException(status_code=404, detail="scene not found")
    return data


@app.post("/commit_scene/{scene_id}")
async def commit_scene(scene_id: str):
    scene = await storage.get_scene(scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail="scene not found")
    # For production, commit would notify integration or perform necessary handoff.
    committed = await storage.mark_committed(scene_id)
    if not committed:
        raise HTTPException(status_code=404, detail="scene not found")
    return {"status": "committed", "scene_id": scene_id}


@app.post("/export_scene/{scene_id}")
async def export_scene(scene_id: str):
    scene = await storage.get_scene(scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail="scene not found")
    export = await export_scene_to_home_assistant(scene_id, scene, logger=logger)
    if export.get("ok"):
        await storage.update_scene(scene_id, scene)
    return export


@app.post("/execute_scene")
async def execute_scene(payload: dict):
    scene = payload.get("scene") if isinstance(payload, dict) else None
    if not isinstance(scene, dict):
        raise HTTPException(status_code=400, detail="scene object is required")
    return await execute_scene_actions(scene)


@app.post("/start_scene/{scene_id}")
async def start_scene(scene_id: str):
    scene = await storage.get_scene(scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail="scene not found")
    result = await runtime.start(scene_id, scene)
    if not result.get("ok", True):
        return JSONResponse(status_code=502, content=result)
    return result


@app.post("/stop_scene/{scene_id}")
async def stop_scene(scene_id: str):
    return await runtime.stop(scene_id, restore=True)


@app.get("/scene_status/{scene_id}")
async def scene_status(scene_id: str):
    return runtime.status(scene_id)


@app.get("/runtime_status")
async def runtime_status():
    return runtime.status()


def _deactivation_plan(scene: dict) -> dict:
    off_actions = []
    seen = set()
    for action in scene.get("actions", []) or []:
        entity_id = action.get("entity_id")
        domain = action.get("domain")
        if not entity_id or not domain or entity_id in seen:
            continue
        if domain not in {"light", "switch", "fan", "media_player"}:
            continue
        seen.add(entity_id)
        off_actions.append(
            {
                "entity_id": entity_id,
                "domain": domain,
                "service": "turn_off",
                "data": {},
                "rationale": "Deactivate Syn scene controlled device",
                "priority": action.get("priority", 0),
            }
        )
    return {
        "scene_name": f"Deactivate {scene.get('scene_name', 'Syn Scene')}",
        "description": "Turn off devices controlled by this Syn scene.",
        "intent": "Deactivate scene",
        "target_room": scene.get("target_room", "unspecified"),
        "actions": off_actions,
        "confidence": 1,
        "warnings": [],
        "assumptions": ["Only devices controlled by the saved Syn scene are turned off."],
        "entity_map": scene.get("entity_map", {}),
    }


@app.post("/deactivate_scene/{scene_id}")
async def deactivate_scene(scene_id: str):
    scene = await storage.get_scene(scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail="scene not found")
    stopped = await runtime.stop(scene_id, restore=True)
    runtime_info = {key: value for key, value in stopped.items() if key != "restore_result"}
    restore_result = stopped.get("restore_result") if isinstance(stopped, dict) else None
    if isinstance(restore_result, dict) and restore_result.get("overall_status") != "skipped":
        return {**restore_result, "runtime": runtime_info}
    return {
        "overall_status": "skipped",
        "message": "No pre-scene snapshot exists for this saved scene, so Syn left devices unchanged instead of turning them off.",
        "actions": [],
        "actions_executed": 0,
        "actions_failed": 0,
        "runtime": runtime_info,
        "fallback_plan": _deactivation_plan(scene),
    }


@app.get("/scenes")
async def list_scenes(skip: int = 0, limit: int = 100):
    scenes = await storage.list_scenes(skip=skip, limit=limit)
    return {"scenes": runtime.enrich_summaries(scenes)}


@app.delete("/scenes/{scene_id}")
async def delete_scene(scene_id: str):
    stopped = await runtime.stop(scene_id, restore=True)
    native = await remove_scene_from_home_assistant(scene_id, logger=logger)
    deleted = await storage.delete_scene(scene_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="scene not found")
    return {"ok": True, "scene_id": scene_id, "message": "Scene deleted", "runtime": stopped, "native": native}


@app.post("/preview_scene")
async def preview_scene(request: ScenePlanRequest):
    """Generate and validate a scene but do not persist; used for UI previews."""
    request = await _with_discovered_entities(request)
    _require_entities(request)
    prompt = build_prompt(request)
    logger.info("Building prompt for preview with %d entities", len(request.entities))
    try:
        raw = await call_ai_model(prompt)
    except Exception as exc:
        logger.warning("AI preview call failed: %s", exc)
        raise _ai_error_response(exc) from exc
    validated = validate_and_normalize(raw, request.entities)
    if not validated.is_valid:
        logger.warning("Validation failed on preview: %s", validated.errors)
        return JSONResponse(status_code=400, content={"errors": validated.errors, "warnings": validated.warnings})
    return JSONResponse(status_code=200, content={"scene": validated.normalized, "warnings": validated.warnings})
