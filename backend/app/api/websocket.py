"""WebSocket endpoint that launches a generation and streams progress."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.db.database import async_session
from app.db.models import Project
from app.services.progress import manager
from app.services.runner import run_generation

ws_router = APIRouter()

# Track running generation tasks so they can be cancelled (keyed by internal id).
active_jobs: dict[int, asyncio.Task] = {}


async def _resolve_project_id(public_id: str) -> int | None:
    """Map an opaque public project id to the internal integer id."""
    async with async_session() as session:
        row = await session.execute(
            select(Project.id).where(Project.public_id == public_id)
        )
        return row.scalar_one_or_none()


@ws_router.websocket("/ws/generate/{project_key}")
async def generate_ws(websocket: WebSocket, project_key: str):
    project_id = await _resolve_project_id(project_key)
    if project_id is None:
        await websocket.close(code=4004)
        return

    await manager.connect(project_id, websocket)
    try:
        # First message from client must contain provider_id (and optional model).
        config = await websocket.receive_json()
        provider_id = int(config["provider_id"])
        model = config.get("model")
        role_providers = config.get("role_providers")

        if project_id not in active_jobs or active_jobs[project_id].done():
            task = asyncio.create_task(
                run_generation(project_id, provider_id, model, role_providers)
            )
            active_jobs[project_id] = task

        # Keep the socket open until the client disconnects or job is done.
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_json(), timeout=1.0)
                if msg.get("action") == "stop":
                    task = active_jobs.get(project_id)
                    if task and not task.done():
                        task.cancel()
                    await websocket.send_json(
                        {"stage": "stopped", "message": "Interrotto"}
                    )
                    break
            except asyncio.TimeoutError:
                task = active_jobs.get(project_id)
                if task and task.done():
                    break
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(project_id, websocket)


@ws_router.post("/projects/{project_key}/stop")
async def stop_generation(project_key: str):
    project_id = await _resolve_project_id(project_key)
    if project_id is None:
        return {"stopped": False}
    task = active_jobs.get(project_id)
    if task and not task.done():
        task.cancel()
        return {"stopped": True}
    return {"stopped": False}
