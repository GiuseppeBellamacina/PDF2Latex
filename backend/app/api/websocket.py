"""WebSocket endpoint that launches a generation and streams progress."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.progress import manager
from app.services.runner import run_generation

ws_router = APIRouter()

# Track running generation tasks so they can be cancelled.
active_jobs: dict[int, asyncio.Task] = {}


@ws_router.websocket("/ws/generate/{project_id}")
async def generate_ws(websocket: WebSocket, project_id: int):
    await manager.connect(project_id, websocket)
    try:
        # First message from client must contain provider_id (and optional model).
        config = await websocket.receive_json()
        provider_id = int(config["provider_id"])
        model = config.get("model")

        if project_id not in active_jobs or active_jobs[project_id].done():
            task = asyncio.create_task(run_generation(project_id, provider_id, model))
            active_jobs[project_id] = task

        # Keep the socket open until the client disconnects or job is done.
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_json(), timeout=1.0)
                if msg.get("action") == "stop":
                    task = active_jobs.get(project_id)
                    if task and not task.done():
                        task.cancel()
                    await websocket.send_json({"stage": "stopped", "message": "Interrotto"})
                    break
            except asyncio.TimeoutError:
                task = active_jobs.get(project_id)
                if task and task.done():
                    break
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(project_id, websocket)


@ws_router.post("/projects/{project_id}/stop")
async def stop_generation(project_id: int):
    task = active_jobs.get(project_id)
    if task and not task.done():
        task.cancel()
        return {"stopped": True}
    return {"stopped": False}
