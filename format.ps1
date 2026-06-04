# Format & lint helper for the backend.
Push-Location $PSScriptRoot/backend
uv run ruff check --fix app
uv run ruff format app
Pop-Location
