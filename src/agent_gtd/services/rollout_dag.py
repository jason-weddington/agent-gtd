"""Derive a rollout's dependency DAG locally, without an LLM planner.

The rollout DAG used to be produced by a remote LLM planner.  It is now
derived from data the GTD database already holds:

1. **Blocker edges** — ``item_dependencies(item_id, blocker_item_id)`` is
   isomorphic to a DAG edge: the blocker must complete before the blocked
   item, i.e. ``from_item_id = blocker_item_id``, ``to_item_id = item_id``.
   Lead agents already record these at grooming time, they are same-project
   enforced and cycle-checked at write time.
2. **File-overlap edges** — any two items whose ``files_to_modify`` paths
   overlap are serialised in caller order so two build agents never edit the
   same file concurrently.  Blockers cannot express this reliably (a lead
   would have to hand-add an edge for every overlapping pair), so the overlap
   analysis runs unconditionally.

Both sources are unioned and deduplicated, blocker edges first.  The result is
a plain ``list[{"from_item_id": ..., "to_item_id": ...}]`` — exactly the shape
every downstream consumer already expects.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import TYPE_CHECKING, Any

from agent_gtd.database import decode_file_specs
from agent_gtd.services.item_service import fetch_dependency_pairs

if TYPE_CHECKING:
    from agent_gtd.db_types import DbPool

#: A single directed dependency edge.  ``from_item_id`` must complete before
#: ``to_item_id`` may start.
Edge = dict[str, str]

#: Value written to the NOT NULL ``rollout_plans.planner_model`` column now
#: that no model is involved in producing the DAG.  It is rendered to users in
#: the rollout activity feed and by ``get-rollout-plan``.
DERIVED_PLANNER_MODEL = "derived-from-blockers"


# ---------------------------------------------------------------------------
# Blocker edges
# ---------------------------------------------------------------------------


async def compute_blocker_edges(db: DbPool, item_ids: list[str]) -> list[Edge]:
    """Derive dependency edges from the ``item_dependencies`` table.

    Only edges whose **both** endpoints are inside *item_ids* are returned.
    An edge pointing at an item outside the wave would make
    ``_build_predecessor_map`` yield a predecessor that can never become
    terminal, leaving the dependent item ``blocked`` forever and the rollout
    unable to reach ``graph_complete``.

    Edges are returned in a deterministic order derived from the caller's
    *item_ids* ordering, so the persisted plan is stable across runs.

    Args:
        db: Database connection pool.
        item_ids: Ordered item IDs that make up the wave.

    Returns:
        List of edges ``{"from_item_id": blocker, "to_item_id": blocked}``.
    """
    pairs = await fetch_dependency_pairs(db, item_ids)
    order = {item_id: index for index, item_id in enumerate(item_ids)}
    edges: list[Edge] = [
        {"from_item_id": blocker_item_id, "to_item_id": item_id}
        for item_id, blocker_item_id in pairs
    ]
    edges.sort(key=lambda e: (order[e["from_item_id"]], order[e["to_item_id"]]))
    return edges


# ---------------------------------------------------------------------------
# File-overlap edges (ported from agent_gtd_dispatch.rollout_planner)
# ---------------------------------------------------------------------------


def _is_directory_entry(path: str) -> bool:
    """Return True if path looks like a directory entry.

    Treats paths with a trailing slash, or whose last path component has no
    file-extension dot, as directory entries (e.g. ``src/foo/`` or ``src/foo``).
    """
    if path.endswith("/"):
        return True
    last_component = path.rstrip("/").rsplit("/", 1)[-1]
    return "." not in last_component


def _paths_overlap(path_a: str, path_b: str) -> bool:
    """Return True if *path_a* and *path_b* represent overlapping filesystem paths.

    Two paths overlap when they are identical (after normalising trailing
    slashes), or when one is a directory entry that is an ancestor of the
    other (e.g. ``agent-gtd-dispatch/tests/`` overlaps with
    ``agent-gtd-dispatch/tests/test_foo.py``).
    """
    norm_a = path_a.rstrip("/")
    norm_b = path_b.rstrip("/")
    if norm_a == norm_b:
        return True
    return (_is_directory_entry(path_a) and norm_b.startswith(norm_a + "/")) or (
        _is_directory_entry(path_b) and norm_a.startswith(norm_b + "/")
    )


def _item_paths(item: dict[str, Any]) -> list[str]:
    """Extract the ``files_to_modify`` paths of a raw item row.

    ``files_to_modify`` is stored as JSON text and is returned as text by
    ``item_service.get_item``, but callers holding an already-decoded item
    dict are accepted too.
    """
    files = item.get("files_to_modify") or []
    if isinstance(files, str):
        files = decode_file_specs(files or "[]")
    if not isinstance(files, list):
        return []
    return [
        str(f.get("path", "")) for f in files if isinstance(f, dict) and f.get("path")
    ]


def compute_overlap_edges(
    items: list[dict[str, Any]], item_ids: list[str]
) -> list[Edge]:
    """Compute deterministic dependency edges for items with overlapping file paths.

    For any pair of items *(earlier, later)* — in input order — whose
    ``files_to_modify`` paths overlap, adds an edge ``earlier → later`` so that
    they are always serialised.  Two build agents must never be handed the same
    file concurrently; the resulting mid-rollout merge conflict is exactly the
    failure the rollout manager has to halt on.

    Args:
        items: Item dicts (each must contain ``'id'`` and ``'files_to_modify'``).
        item_ids: Ordered list of item IDs that defines input ordering.

    Returns:
        List of edges representing deterministic overlap constraints.
    """
    id_to_paths: dict[str, list[str]] = {
        str(item.get("id", "")): _item_paths(item) for item in items
    }

    edges: list[Edge] = []
    for i, id_a in enumerate(item_ids):
        for id_b in item_ids[i + 1 :]:
            paths_a = id_to_paths.get(id_a, [])
            paths_b = id_to_paths.get(id_b, [])
            if any(_paths_overlap(pa, pb) for pa in paths_a for pb in paths_b):
                edges.append({"from_item_id": id_a, "to_item_id": id_b})
    return edges


# ---------------------------------------------------------------------------
# Merge + acyclicity
# ---------------------------------------------------------------------------


def merge_edges(blocker_edges: list[Edge], overlap_edges: list[Edge]) -> list[Edge]:
    """Union blocker edges with deterministic overlap edges, deduplicating.

    Blocker edges appear first in the result; overlap edges fill any gaps the
    lead did not record as a blocker.  Duplicate ``(from_id, to_id)`` pairs are
    silently dropped.

    Args:
        blocker_edges: Edges derived from ``item_dependencies``.
        overlap_edges: Deterministic edges from file-path overlap analysis.

    Returns:
        Merged, deduplicated list of edges.
    """
    seen: set[tuple[str, str]] = set()
    result: list[Edge] = []
    for edge in blocker_edges + overlap_edges:
        key = (edge["from_item_id"], edge["to_item_id"])
        if key not in seen:
            seen.add(key)
            result.append(edge)
    return result


def assert_acyclic(nodes: list[str], edges: list[Edge]) -> None:
    """Assert the graph defined by nodes and edges is acyclic (a valid DAG).

    Uses Kahn's topological-sort algorithm.  ``add_blocker`` already rejects
    cycles at write time, but this is a read-time backstop that catches edges
    which entered ``item_dependencies`` by any other route.  If any cycle
    exists (including self-loops), raises ValueError rather than allowing a
    broken plan to be persisted and silently blocking items forever.

    Args:
        nodes: All node IDs in the graph.
        edges: Directed edges; an edge with from_item_id=A and to_item_id=B
            means A must complete before B.

    Raises:
        ValueError: If a cyclic dependency is detected.
    """
    in_degree: dict[str, int] = dict.fromkeys(nodes, 0)
    adjacency: defaultdict[str, list[str]] = defaultdict(list)

    for edge in edges:
        adjacency[edge["from_item_id"]].append(edge["to_item_id"])
        to_id = edge["to_item_id"]
        in_degree[to_id] = in_degree.get(to_id, 0) + 1

    queue: deque[str] = deque(node for node in nodes if in_degree[node] == 0)
    processed = 0

    while queue:
        node = queue.popleft()
        processed += 1
        for successor in adjacency[node]:
            in_degree[successor] -= 1
            if in_degree[successor] == 0:
                queue.append(successor)

    if processed < len(nodes):
        raise ValueError(
            f"cyclic dependency detected in rollout plan: "
            f"{len(nodes) - processed} node(s) involved in a cycle"
        )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def derive_edges(
    db: DbPool,
    items: list[dict[str, Any]],
    item_ids: list[str],
) -> list[Edge]:
    """Derive the full edge list for a wave from blockers plus file overlap.

    Args:
        db: Database connection pool.
        items: Item rows for *item_ids* (any order).
        item_ids: Ordered item IDs that make up the wave.

    Returns:
        Merged, deduplicated, verified-acyclic edge list.

    Raises:
        ValueError: If the derived graph contains a cycle.
    """
    blocker_edges = await compute_blocker_edges(db, item_ids)
    overlap_edges = compute_overlap_edges(items, item_ids)
    edges = merge_edges(blocker_edges, overlap_edges)
    assert_acyclic(list(item_ids), edges)
    return edges
