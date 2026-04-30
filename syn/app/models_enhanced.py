"""Enhanced models with all required scene components."""
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime


class Entity(BaseModel):
    entity_id: str
    domain: str
    capabilities: List[str] = []
    state: Dict[str, Any] = {}
    room: Optional[str] = None


class SceneAction(BaseModel):
    entity_id: str
    domain: str
    service: str
    data: Dict[str, Any] = {}
    rationale: Optional[str] = None
    priority: int = 0


class ScenePlanRequest(BaseModel):
    user_prompt: Optional[str] = None
    room_id: Optional[str] = None
    entities: List[Entity] = []
    constraints: Optional[Dict[str, Any]] = None


class ScenePlanResponse(BaseModel):
    scene_id: Optional[str] = None
    scene: Dict[str, Any] = {}
    warnings: Optional[List[str]] = []


class ExecutionActionResult(BaseModel):
    entity_id: str
    status: str
    message: Optional[str] = None
    details: Dict[str, Any] = {}


class SceneExecutionResult(BaseModel):
    scene_id: str
    timestamp: str
    actions: List[ExecutionActionResult] = []
    overall_status: str = "success"
