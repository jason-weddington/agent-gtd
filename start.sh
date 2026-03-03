#!/usr/bin/env bash
set -e

cleanup() {
  kill -- -$$ 2>/dev/null
  wait
}
trap cleanup INT TERM EXIT

uv run uvicorn agent_gtd.main:app --reload --port 8000 &
npm --prefix frontend run dev &

wait
