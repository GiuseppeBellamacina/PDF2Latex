"""Tests for the PATCH /projects/{key} endpoint — verify that research_mode=false
and web_tool_ids=null are correctly persisted to the database.

Uses FastAPI's TestClient with an in-memory SQLite database.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.database import async_session
from app.db.models import Project, ProjectStatus


@pytest.fixture
async def test_project():
    """Create a project with research_mode=True, web_tool_ids=[1] in the DB."""
    async with async_session() as session:
        project = Project(
            name="Test PATCH Project",
            language="italian",
            research_mode=True,
            web_tool_ids=[1],
            research_max_queries=5,
            status=ProjectStatus.uploaded,
            total_sources=1,
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)
        key = project.public_id
        pid = project.id
    yield key, pid
    # Cleanup
    async with async_session() as session:
        project = await session.get(Project, pid)
        if project:
            await session.delete(project)
            await session.commit()


@pytest.mark.asyncio
async def test_patch_research_mode_false_disables_research(test_project):
    """PATCH research_mode=false actually sets it to False in the DB."""
    from app.main import app

    project_key, project_id = test_project

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Verify initial state.
        async with async_session() as session:
            project = await session.get(Project, project_id)
            assert project.research_mode is True
            assert project.web_tool_ids == [1]
            assert project.research_max_queries == 5

        # 2. PATCH: disable research mode and clear web_tool_ids.
        resp = await client.patch(
            f"/api/projects/{project_key}",
            json={"research_mode": False, "web_tool_ids": None},
        )
        assert resp.status_code == 200, resp.text

        # 3. Verify changes persisted.
        async with async_session() as session:
            project = await session.get(Project, project_id)
            assert project.research_mode is False, (
                f"Expected research_mode=False, got {project.research_mode}"
            )
            assert project.web_tool_ids is None, (
                f"Expected web_tool_ids=None, got {project.web_tool_ids}"
            )
            # research_max_queries should remain unchanged (not in payload).
            assert project.research_max_queries == 5


@pytest.mark.asyncio
async def test_patch_research_mode_true_enables_research(test_project):
    """PATCH research_mode=true enables it even when project was created without it."""
    from app.main import app

    project_key, project_id = test_project

    # First disable research mode.
    async with async_session() as session:
        project = await session.get(Project, project_id)
        project.research_mode = False
        project.web_tool_ids = None
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            f"/api/projects/{project_key}",
            json={"research_mode": True, "web_tool_ids": None},
        )
        assert resp.status_code == 200, resp.text

        async with async_session() as session:
            project = await session.get(Project, project_id)
            assert project.research_mode is True
            assert project.web_tool_ids is None


@pytest.mark.asyncio
async def test_patch_omits_field_preserves_original(test_project):
    """Fields not in the payload are left unchanged (PATCH semantics)."""
    from app.main import app

    project_key, project_id = test_project

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            f"/api/projects/{project_key}",
            json={"name": "Renamed Only"},
        )
        assert resp.status_code == 200, resp.text

        async with async_session() as session:
            project = await session.get(Project, project_id)
            assert project.name == "Renamed Only"
            # These should be untouched.
            assert project.research_mode is True
            assert project.web_tool_ids == [1]
            assert project.research_max_queries == 5


@pytest.mark.asyncio
async def test_patch_research_max_queries_null_clears_limit(test_project):
    """PATCH research_max_queries=null clears the query limit (matching frontend behavior).

    The frontend sends ``null`` when the user leaves the field empty or enters 0.
    The DB should store NULL for unlimited queries.
    """
    from app.main import app

    project_key, project_id = test_project

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            f"/api/projects/{project_key}",
            json={"research_max_queries": None},
        )
        assert resp.status_code == 200, resp.text

        async with async_session() as session:
            project = await session.get(Project, project_id)
            assert project.research_max_queries is None, (
                f"Expected NULL, got {project.research_max_queries}"
            )


@pytest.mark.asyncio
async def test_patch_nullable_fields_set_to_null(test_project):
    """PATCH nullable string fields like ocr_lang and structure_hint can be cleared."""
    from app.main import app

    project_key, project_id = test_project

    # Set some values first.
    async with async_session() as session:
        project = await session.get(Project, project_id)
        project.ocr_lang = "ita+eng"
        project.structure_hint = "Include chapter on ethics"
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            f"/api/projects/{project_key}",
            json={"ocr_lang": None, "structure_hint": None},
        )
        assert resp.status_code == 200, resp.text

        async with async_session() as session:
            project = await session.get(Project, project_id)
            assert project.ocr_lang is None, (
                f"Expected ocr_lang=NULL, got {project.ocr_lang!r}"
            )
            assert project.structure_hint is None, (
                f"Expected structure_hint=NULL, got {project.structure_hint!r}"
            )


@pytest.mark.asyncio
async def test_patch_research_mode_true_with_invalid_web_tool_rejected(
    test_project,
):
    """When research_mode=True, an invalid web_tool_ids should be rejected."""
    from app.main import app

    project_key, project_id = test_project

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 999 does not exist as a WebToolConfig.
        resp = await client.patch(
            f"/api/projects/{project_key}",
            json={"research_mode": True, "web_tool_ids": [999]},
        )
        assert resp.status_code == 404, resp.text
        assert "non trovato" in resp.text

        # Verify DB was not modified.
        async with async_session() as session:
            project = await session.get(Project, project_id)
            assert project.research_mode is True  # unchanged from fixture
            assert project.web_tool_ids == [1]  # unchanged from fixture


@pytest.mark.asyncio
async def test_patch_research_mode_false_no_web_tool_validation(test_project):
    """When research_mode=False, an invalid web_tool_ids is accepted (no validation)."""
    from app.main import app

    project_key, project_id = test_project

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            f"/api/projects/{project_key}",
            json={"research_mode": False, "web_tool_ids": [999]},
        )
        # Should succeed because research_mode is off → no web tool validation.
        assert resp.status_code == 200, resp.text

        async with async_session() as session:
            project = await session.get(Project, project_id)
            assert project.research_mode is False
            assert project.web_tool_ids == [999]  # accepted because research is off
