"""Background runtime for saved Syn animated scenes."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime
from typing import Any

from .ha_client import MAX_INTERVAL_MS, execute_scene_actions, restore_scene_snapshot, snapshot_scene_entities


def _utcnow() -> str:
    return datetime.utcnow().isoformat()


def _automation(scene: dict[str, Any]) -> dict[str, Any]:
    automation = scene.get("automation") if isinstance(scene.get("automation"), dict) else {}
    return automation if isinstance(automation, dict) else {}


def is_loop_scene(scene: dict[str, Any]) -> bool:
    automation = _automation(scene)
    return str(automation.get("mode") or "").lower() == "loop"


def _loop_interval_seconds(scene: dict[str, Any]) -> float:
    automation = _automation(scene)
    try:
        interval_ms = int(automation.get("interval_ms") or 750)
    except (TypeError, ValueError):
        interval_ms = 750
    interval_ms = max(250, min(MAX_INTERVAL_MS, interval_ms))
    return interval_ms / 1000


def _one_runtime_cycle(scene: dict[str, Any]) -> dict[str, Any]:
    cycle = deepcopy(scene)
    automation = dict(cycle.get("automation") or {})
    automation["mode"] = "sequence"
    automation["repeat"] = 1
    cycle["automation"] = automation
    return cycle


def _summarize_result(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    summary = {
        key: result.get(key)
        for key in ("overall_status", "message", "actions_executed", "actions_failed")
        if key in result
    }
    actions = result.get("actions")
    if isinstance(actions, list):
        summary["action_count"] = len(actions)
    return summary or None


class SceneRuntimeManager:
    """Owns long-running scene loops so HA switch off can stop them cleanly."""

    def __init__(self, logger=None) -> None:
        self._logger = logger
        self._tasks: dict[str, asyncio.Task] = {}
        self._stops: dict[str, asyncio.Event] = {}
        self._states: dict[str, dict[str, Any]] = {}

    def _state(self, scene_id: str) -> dict[str, Any]:
        return self._states.setdefault(
            scene_id,
            {
                "scene_id": scene_id,
                "running": False,
                "iterations": 0,
                "last_result": None,
                "last_error": None,
            },
        )

    def is_running(self, scene_id: str) -> bool:
        task = self._tasks.get(scene_id)
        return bool(task and not task.done())

    def status(self, scene_id: str | None = None) -> dict[str, Any]:
        if scene_id:
            state = dict(self._state(scene_id))
            state["running"] = self.is_running(scene_id)
            if "restore_snapshot" in state:
                state["restore_snapshot_available"] = bool((state.get("restore_snapshot") or {}).get("states"))
                state.pop("restore_snapshot", None)
            state["last_result"] = _summarize_result(state.get("last_result"))
            state["last_restore_result"] = _summarize_result(state.get("last_restore_result"))
            return state
        return {
            "running": sorted(scene_id for scene_id in self._states if self.is_running(scene_id)),
            "scenes": {scene_id: self.status(scene_id) for scene_id in self._states},
        }

    def enrich_summary(self, summary: dict[str, Any]) -> dict[str, Any]:
        scene_id = summary.get("id")
        if not scene_id:
            return summary
        runtime = self.status(scene_id)
        return {
            **summary,
            "running": runtime.get("running", False),
            "runtime": runtime,
        }

    def enrich_summaries(self, summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.enrich_summary(summary) for summary in summaries]

    async def start(self, scene_id: str, scene: dict[str, Any]) -> dict[str, Any]:
        if is_loop_scene(scene) and self.is_running(scene_id):
            return {
                "ok": True,
                "running": True,
                "already_running": True,
                "scene_id": scene_id,
                "status": self.status(scene_id),
            }

        snapshot = await snapshot_scene_entities(scene)
        if not is_loop_scene(scene):
            result = await execute_scene_actions(scene)
            state = self._state(scene_id)
            state.update(
                {
                    "running": False,
                    "mode": "one_shot",
                    "scene_name": scene.get("scene_name"),
                    "restore_snapshot": snapshot if snapshot.get("ok") else None,
                    "restore_snapshot_message": snapshot.get("message"),
                    "last_result": result,
                    "last_error": None if result.get("overall_status") != "failed" else result.get("message"),
                    "updated_at": _utcnow(),
                }
            )
            return {
                "ok": result.get("overall_status") != "failed",
                "running": False,
                "scene_id": scene_id,
                "mode": "one_shot",
                "result": result,
                "restore_snapshot_available": bool(snapshot.get("ok")),
            }

        stop_event = asyncio.Event()
        state = self._state(scene_id)
        state.update(
            {
                "running": True,
                "mode": "loop",
                "scene_name": scene.get("scene_name"),
                "started_at": _utcnow(),
                "updated_at": _utcnow(),
                "stopped_at": None,
                "iterations": 0,
                "last_error": None,
                "restore_snapshot": snapshot if snapshot.get("ok") else None,
                "restore_snapshot_message": snapshot.get("message"),
            }
        )
        task = asyncio.create_task(self._run_loop(scene_id, scene, stop_event), name=f"syn-loop-{scene_id}")
        self._tasks[scene_id] = task
        self._stops[scene_id] = stop_event
        return {
            "ok": True,
            "running": True,
            "scene_id": scene_id,
            "mode": "loop",
            "message": "Syn scene loop started.",
            "restore_snapshot_available": bool(snapshot.get("ok")),
            "status": self.status(scene_id),
        }

    async def _restore(self, scene_id: str) -> dict[str, Any]:
        state = self._state(scene_id)
        result = await restore_scene_snapshot(state.get("restore_snapshot"))
        state["last_restore_result"] = _summarize_result(result)
        if result.get("overall_status") in {"success", "skipped"}:
            state["restore_snapshot"] = None
        state["updated_at"] = _utcnow()
        return result

    async def stop(self, scene_id: str, *, restore: bool = False) -> dict[str, Any]:
        task = self._tasks.get(scene_id)
        stop_event = self._stops.get(scene_id)
        if not task or task.done():
            state = self._state(scene_id)
            state["running"] = False
            restore_result = await self._restore(scene_id) if restore else None
            return {
                "ok": True,
                "running": False,
                "scene_id": scene_id,
                "message": "Syn scene loop was not running.",
                "restore_result": restore_result,
                "status": self.status(scene_id),
            }

        if stop_event:
            stop_event.set()
        try:
            await asyncio.wait_for(task, timeout=5)
        except asyncio.TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        restore_result = await self._restore(scene_id) if restore else None
        return {
            "ok": True,
            "running": False,
            "scene_id": scene_id,
            "message": "Syn scene loop stopped.",
            "restore_result": restore_result,
            "status": self.status(scene_id),
        }

    async def stop_all(self, *, restore: bool = False) -> None:
        await asyncio.gather(
            *(self.stop(scene_id, restore=restore) for scene_id in list(self._tasks)),
            return_exceptions=True,
        )

    async def _run_loop(self, scene_id: str, scene: dict[str, Any], stop_event: asyncio.Event) -> None:
        state = self._state(scene_id)
        consecutive_failures = 0
        try:
            while not stop_event.is_set():
                state["iterations"] = int(state.get("iterations") or 0) + 1
                state["updated_at"] = _utcnow()
                result = await execute_scene_actions(_one_runtime_cycle(scene), sequence_repeat_override=1)
                state["last_result"] = result
                state["updated_at"] = _utcnow()
                if result.get("overall_status") == "failed":
                    consecutive_failures += 1
                    state["last_error"] = result.get("message") or "Scene loop cycle failed"
                    if self._logger:
                        self._logger.warning(
                            "Syn scene loop %s failed cycle %s: %s",
                            scene_id,
                            state["iterations"],
                            state["last_error"],
                        )
                    if consecutive_failures >= 3:
                        state["last_error"] = "Stopped after 3 consecutive failed loop cycles."
                        break
                else:
                    consecutive_failures = 0
                    state["last_error"] = None

                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=_loop_interval_seconds(scene))
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state["last_error"] = f"{exc.__class__.__name__}: {exc}"
            if self._logger:
                self._logger.exception("Syn scene loop %s crashed", scene_id)
        finally:
            state["running"] = False
            state["stopped_at"] = _utcnow()
            state["updated_at"] = _utcnow()
            self._stops.pop(scene_id, None)
            self._tasks.pop(scene_id, None)
