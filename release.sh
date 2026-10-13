#!/usr/bin/env bash
# Cut a release and publish it.
#
# During development: commit freely on main, push to origin, deploy liberally.
# When you hit a meaningful boundary — a coherent batch of work worth marking
# as a checkpoint — run this script. It will:
#   1. Bump the version via python-semantic-release (if there are feat/fix
#      commits since the last tag; no-op otherwise)
#   2. Run the maintainer-local leak guard (see below), then push main + tags
#      to BOTH origin and github
#   3. Deploy to the running service
#
# The version shown in the app settings page moves at each release, so this
# doubles as a "promote to UI" step.

set -euo pipefail

guard=1
for arg in "$@"; do
  case "$arg" in
    --no-guard) guard=0 ;;
    *) echo "Unknown argument: $arg (usage: ./release.sh [--no-guard])" >&2; exit 2 ;;
  esac
done

if [ -n "$(git status --porcelain)" ]; then
  echo "error: working tree not clean — commit or stash first." >&2
  exit 1
fi

if [ "$(git rev-parse --abbrev-ref HEAD)" != "main" ]; then
  echo "error: must be on main branch." >&2
  exit 1
fi

# Leak guard: a maintainer-local scan of everything this release would publish
# to github (tracked tree, plus commits, messages and paths github lacks). It
# lives outside the repo so its denylist is never published. Fails closed when
# a github remote exists; --no-guard skips it loudly.
if git remote get-url github >/dev/null 2>&1; then
  if [ "$guard" = "0" ]; then
    echo "!!! --no-guard: release guard SKIPPED; nothing checked what github will receive. !!!" >&2
  elif [ -x ./release.guard.local.sh ]; then
    ./release.guard.local.sh || { rc=$?; echo "error: release guard failed (exit $rc); nothing released." >&2; exit 1; }
  else
    echo "error: a github remote is configured but no executable ./release.guard.local.sh exists. It is a maintainer-local scan (exit 0 clean, 1 hits, 2 could not run). Create it, or re-run with --no-guard to release without it." >&2
    exit 1
  fi
fi

uv run semantic-release version --no-push --no-vcs-release
# --follow-tags pushes only annotated tags reachable from the commits being
# pushed, so stale local tags that diverge from origin don't block the release.
git push --follow-tags origin main
git push --follow-tags github main
./deploy.sh
