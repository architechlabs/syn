import aiofiles
import aiofiles.os
import os
import json
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List

DEFAULT_DATA_ROOT = "/data" if os.name != "nt" else os.path.dirname(__file__)
BASE = os.getenv("SYN_SCENES_PATH", os.path.join(DEFAULT_DATA_ROOT, "scenes"))
os.makedirs(BASE, exist_ok=True)


class SceneStorage:
    def __init__(self, base: str = BASE):
        self.base = base
        os.makedirs(self.base, exist_ok=True)

    async def save_scene(self, scene: Dict[str, Any]) -> str:
        sid = f"scene-{uuid.uuid4().hex}"
        path = os.path.join(self.base, f"{sid}.json")
        payload = {
            "id": sid,
            "created": datetime.utcnow().isoformat(),
            "updated": datetime.utcnow().isoformat(),
            "status": "draft",
            "scene": scene,
        }
        async with aiofiles.open(path, "w", encoding="utf-8") as fh:
            await fh.write(json.dumps(payload, ensure_ascii=False, indent=2))
        return sid

    async def get_scene(self, scene_id: str) -> Optional[Dict[str, Any]]:
        path = os.path.join(self.base, f"{scene_id}.json")
        if not os.path.exists(path):
            return None
        async with aiofiles.open(path, "r", encoding="utf-8") as fh:
            txt = await fh.read()
            payload = json.loads(txt)
            return payload.get("scene", payload)

    async def delete_scene(self, scene_id: str) -> bool:
        path = os.path.join(self.base, f"{scene_id}.json")
        if not os.path.exists(path):
            return False
        await aiofiles.os.remove(path)
        return True

    async def mark_committed(self, scene_id: str) -> bool:
        path = os.path.join(self.base, f"{scene_id}.json")
        if not os.path.exists(path):
            return False
        async with aiofiles.open(path, "r", encoding="utf-8") as fh:
            payload = json.loads(await fh.read())
        if "scene" not in payload:
            payload = {"id": scene_id, "created": None, "scene": payload}
        payload["status"] = "committed"
        payload["updated"] = datetime.utcnow().isoformat()
        payload["committed_at"] = datetime.utcnow().isoformat()
        async with aiofiles.open(path, "w", encoding="utf-8") as fh:
            await fh.write(json.dumps(payload, ensure_ascii=False, indent=2))
        return True

    async def list_scenes(self, skip: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        if not os.path.exists(self.base):
            return []
        files = sorted(
            [f for f in os.listdir(self.base) if f.endswith(".json")],
            reverse=True,
        )
        scenes = []
        for filename in files[skip : skip + limit]:
            try:
                async with aiofiles.open(os.path.join(self.base, filename), "r", encoding="utf-8") as fh:
                    payload = json.loads(await fh.read())
                scene = payload.get("scene", payload)
                actions = scene.get("actions", []) if isinstance(scene, dict) else []
                automation = scene.get("automation", {}) if isinstance(scene, dict) else {}
                automation = automation if isinstance(automation, dict) else {}
                controlled_entities = sorted(
                    {
                        action.get("entity_id")
                        for action in actions
                        if isinstance(action, dict) and action.get("entity_id")
                    }
                )
                scenes.append(
                    {
                        "id": payload.get("id", filename[:-5]),
                        "created": payload.get("created"),
                        "updated": payload.get("updated"),
                        "status": payload.get("status", "draft"),
                        "name": scene.get("scene_name", "Unnamed"),
                        "target_room": scene.get("target_room"),
                        "description": scene.get("description"),
                        "automation": automation,
                        "is_animated": automation.get("mode") in {"loop", "sequence"} or any(
                            isinstance(action, dict)
                            and any(action.get(key) for key in ("delay_ms", "duration_ms", "interval_ms"))
                            for action in actions
                        ),
                        "action_count": len(actions),
                        "controlled_entities": controlled_entities,
                    }
                )
            except Exception:
                continue
        return scenes
