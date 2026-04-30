"""Enhanced async file-based storage with audit logging."""
import aiofiles
import os
import json
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime

BASE = os.path.join(os.path.dirname(__file__), "data")
LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(BASE, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)


class SceneStorage:
    def __init__(self, base: str = BASE):
        self.base = base

    async def save_scene(self, scene: Dict[str, Any]) -> str:
        """Save scene with full metadata."""
        scene_id = f"scene-{uuid.uuid4().hex}"
        path = os.path.join(self.base, f"{scene_id}.json")
        meta = {
            "id": scene_id,
            "created": datetime.utcnow().isoformat(),
            "status": "draft",
            "scene": scene
        }
        async with aiofiles.open(path, "w", encoding="utf-8") as fh:
            await fh.write(json.dumps(meta, ensure_ascii=False, indent=2))
        return scene_id

    async def get_scene(self, scene_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve scene (return scene dict only, not metadata)."""
        path = os.path.join(self.base, f"{scene_id}.json")
        if not os.path.exists(path):
            return None
        async with aiofiles.open(path, "r", encoding="utf-8") as fh:
            data = json.loads(await fh.read())
            return data.get("scene", data)

    async def mark_committed(self, scene_id: str) -> bool:
        """Mark scene as committed."""
        path = os.path.join(self.base, f"{scene_id}.json")
        if not os.path.exists(path):
            return False
        async with aiofiles.open(path, "r", encoding="utf-8") as fh:
            data = json.loads(await fh.read())
        data["status"] = "committed"
        data["committed_at"] = datetime.utcnow().isoformat()
        async with aiofiles.open(path, "w", encoding="utf-8") as fh:
            await fh.write(json.dumps(data, ensure_ascii=False, indent=2))
        return True

    async def delete_scene(self, scene_id: str) -> bool:
        """Delete scene (draft only)."""
        path = os.path.join(self.base, f"{scene_id}.json")
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    async def list_scenes(self, skip: int = 0, limit: int = 100) -> List[Dict]:
        """List all scenes."""
        if not os.path.exists(self.base):
            return []
        files = sorted([f for f in os.listdir(self.base) if f.endswith(".json")])
        scenes = []
        for f in files[skip:skip+limit]:
            path = os.path.join(self.base, f)
            try:
                async with aiofiles.open(path, "r", encoding="utf-8") as fh:
                    data = json.loads(await fh.read())
                    scenes.append({
                        "id": data.get("id"),
                        "created": data.get("created"),
                        "status": data.get("status"),
                        "name": data.get("scene", {}).get("scene_name", "Unnamed")
                    })
            except Exception:
                pass
        return scenes


class SceneLog:
    """JSONL audit log for all scene operations."""
    def __init__(self, logs_dir: str = LOGS_DIR):
        self.logs_dir = logs_dir

    async def write_entry(self, entry: Dict[str, Any]) -> None:
        """Write one audit log entry."""
        scene_id = entry.get("scene_id", "system")
        log_file = os.path.join(self.logs_dir, f"{scene_id}.jsonl")
        entry_json = json.dumps(entry, default=str) + "\n"
        async with aiofiles.open(log_file, "a", encoding="utf-8") as fh:
            await fh.write(entry_json)

    async def get_entries(self, scene_id: str) -> List[Dict]:
        """Read all log entries for a scene."""
        log_file = os.path.join(self.logs_dir, f"{scene_id}.jsonl")
        if not os.path.exists(log_file):
            return []
        entries = []
        async with aiofiles.open(log_file, "r", encoding="utf-8") as fh:
            content = await fh.read()
            for line in content.strip().split("\n"):
                if line:
                    entries.append(json.loads(line))
        return entries
