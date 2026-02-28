#!/usr/bin/env bash
set -e

trap 'kill 0' EXIT

uv run uvicorn agent_gtd.main:app --reload --port 8000 &
npm --prefix frontend run dev &

wait
