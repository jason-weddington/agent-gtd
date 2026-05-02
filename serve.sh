#!/usr/bin/env bash
# Production entry point: uvicorn only. Frontend is served as static
# files by nginx from frontend/dist/ — see docs/deploy.md.
set -e
exec uv run uvicorn agent_gtd.main:app --host 127.0.0.1 --port 8000
