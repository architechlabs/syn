from pydantic import BaseModel
from typing import List, Dict, Any, Optional


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
    constraints: Dict[str, Any] = {}


class ScenePlanResponse(BaseModel):
    scene_id: Optional[str]
    scene: Dict[str, Any] = {}
    warnings: List[str] = []

    @classmethod
    def from_dict(cls, d: Dict[str, Any]):
        return cls(scene_id=d.get("scene_id"), scene=d.get("scene"), warnings=d.get("warnings", []))


class ErrorResponse(BaseModel):
    errors: List[str] = []
    warnings: List[str] = []
