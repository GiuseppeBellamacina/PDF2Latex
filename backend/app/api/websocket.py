"""WebSocket endpoint that launches a generation and streams progress."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.cancellation import CancellationToken
from app.db.database import async_session
from app.db.models import Project
from app.services.progress import manager
from app.services.runner import run_generation

ws_router = APIRouter()

# Track running generation tasks and their cancellation tokens (keyed by internal id).
active_jobs: dict[int, asyncio.Task] = {}
_cancel_tokens: dict[int, CancellationToken] = {}


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
            cancel_token = CancellationToken()
            _cancel_tokens[project_id] = cancel_token
            task = asyncio.create_task(
                run_generation(
                    project_id,
                    provider_id,
                    model,
                    role_providers,
                    cancel_token=cancel_token,
                )
            )
            # Clean up the job reference and cancel token when it finishes so
            # memory doesn't leak and the slot can be reused.
            # Capture the specific objects so a stale callback from a previous
            # generation doesn't accidentally pop the new task/token.
            _ct = cancel_token
            task.add_done_callback(
                lambda t, ct=_ct: (  # type: ignore[arg-type]
                    active_jobs.pop(project_id, None)
                    if active_jobs.get(project_id) is t
                    else None,
                    _cancel_tokens.pop(project_id, None)
                    if _cancel_tokens.get(project_id) is ct
                    else None,
                )
            )
            active_jobs[project_id] = task

        job_task = active_jobs.get(project_id)
        # Keep the socket open until the client disconnects or job is done.
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_json(), timeout=1.0)
                if msg.get("action") == "stop":
                    # Signal cancellation to the extractor thread first so it
                    # can unwind cooperatively, then cancel the async task.
                    ct = _cancel_tokens.get(project_id)
                    if ct:
                        ct.cancel()
                    if job_task and not job_task.done():
                        job_task.cancel()
                    await websocket.send_json(
                        {"stage": "stopped", "message": "Interrotto"}
                    )
                    break
            except asyncio.TimeoutError:
                if job_task and job_task.done():
                    break
            except (ValueError, json.JSONDecodeError):
                # Client sent malformed JSON — ignore and keep waiting.
                pass
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(project_id, websocket)


@ws_router.post("/projects/{project_key}/stop")
async def stop_generation(project_key: str):
    project_id = await _resolve_project_id(project_key)
    if project_id is None:
        return {"stopped": False}
    # Cancel the extractor cooperatively first, then the async task.
    ct = _cancel_tokens.get(project_id)
    if ct:
        ct.cancel()
    task = active_jobs.get(project_id)
    if task and not task.done():
        task.cancel()
        return {"stopped": True}
    return {"stopped": False}
