from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from .models import ScenePlanRequest, ScenePlanResponse
from .prompt_builder import build_prompt
from .ai_client import call_ai_model
from .validator import validate_and_normalize
from .storage import SceneStorage
from .logger import get_logger
from .version_sync import ensure_integration_installed, sync_integration_manifest
import os
from pathlib import Path

logger = get_logger("addon.main")
app = FastAPI(title="AI Scene Planner")
storage = SceneStorage()


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
        ha_config_path = os.getenv("HA_CONFIG_PATH") or os.getenv("HOME_ASSISTANT_CONFIG")
        if ha_config_path:
            install = ensure_integration_installed(Path(ha_config_path))
            logger.info("Integration installed/updated at %s", install.target_path)
    except FileNotFoundError:
        logger.debug("Version sync skipped because add-on or integration files are unavailable")


@app.post("/generate_scene", response_model=ScenePlanResponse)
async def generate_scene(request: ScenePlanRequest):
    """Generate a scene plan from prompt + entities."""
    prompt = build_prompt(request)
    logger.info("Building prompt for scene generation")
    try:
        raw = await call_ai_model(prompt)
    except Exception as exc:
        logger.exception("AI call failed")
        raise HTTPException(status_code=502, detail="AI provider failed to return a usable scene") from exc

    logger.debug("Raw AI response captured")
    validated = validate_and_normalize(raw, request.entities)
    if not validated.is_valid:
        logger.warning("Validation failed: %s", validated.errors)
        return JSONResponse(status_code=400, content={"errors": validated.errors, "warnings": validated.warnings})

    scene = validated.normalized
    # persist draft
    scene_id = await storage.save_scene(scene)
    logger.info("Scene draft saved: %s", scene_id)
    return ScenePlanResponse.from_dict({"scene": scene, "scene_id": scene_id, "warnings": validated.warnings})


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


@app.get("/scenes")
async def list_scenes(skip: int = 0, limit: int = 100):
    return {"scenes": await storage.list_scenes(skip=skip, limit=limit)}


@app.post("/preview_scene")
async def preview_scene(request: ScenePlanRequest):
    """Generate and validate a scene but do not persist; used for UI previews."""
    prompt = build_prompt(request)
    logger.info("Building prompt for preview")
    try:
        raw = await call_ai_model(prompt)
    except Exception as exc:
        logger.exception("AI preview call failed")
        raise HTTPException(status_code=502, detail="AI provider failed to return a usable scene") from exc
    validated = validate_and_normalize(raw, request.entities)
    if not validated.is_valid:
        logger.warning("Validation failed on preview: %s", validated.errors)
        return JSONResponse(status_code=400, content={"errors": validated.errors, "warnings": validated.warnings})
    return JSONResponse(status_code=200, content={"scene": validated.normalized, "warnings": validated.warnings})
