from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from .models import ScenePlanRequest, ScenePlanResponse
from .prompt_builder import build_prompt
from .ai_client import call_ai_model
from .validator import validate_and_normalize
from .storage import SceneStorage
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


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index():
    """Serve the add-on web UI at the ingress root."""
    return INDEX_HTML


@app.get("/config_status")
async def config_status():
    settings = load_ai_settings()
    return {
        "api_key_configured": settings.has_api_key,
        "api_key": mask_secret(settings.api_key),
        "model": settings.model,
        "temperature": settings.temperature,
        "options_path": str(settings.options_path),
    }


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
        "AI settings loaded from %s: api_key=%s model=%s temperature=%s",
        settings.options_path,
        mask_secret(settings.api_key),
        settings.model,
        settings.temperature,
    )


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
