"""Tests for rollout_dag: blocker-derived edges, file overlap, merge, acyclicity.

The overlap / merge / acyclicity suites are ports of the equivalent tests that
guard ``agent_gtd_dispatch.rollout_planner`` — the behaviour moved, so the
coverage moves with it.
"""

import re
import uuid
from datetime import UTC, datetime

import pytest

from agent_gtd.database import encode_file_specs, encode_json_list, get_db
from agent_gtd.services.item_service import (
    dependency_pairs_sql,
    fetch_dependency_pairs,
)
from agent_gtd.services.rollout_dag import (
    _is_directory_entry,
    _paths_overlap,
    assert_acyclic,
    compute_blocker_edges,
    compute_overlap_edges,
    derive_edges,
    merge_edges,
)
from agent_gtd.sqlite_pool import _pg_to_sqlite

NOW = datetime.now(UTC).isoformat()


@pytest.fixture
async def db():
    """Return the patched test database pool."""
    return await get_db()


async def _make_user(db) -> str:
    user_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO users (id, email, hashed_password, created_at) "
        "VALUES ($1, $2, $3, $4)",
        user_id,
        f"{user_id[:8]}@test.com",
        "hashed",
        NOW,
    )
    return user_id


async def _make_project(db, user_id: str) -> str:
    project_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO projects (id, user_id, name, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5)",
        project_id,
        user_id,
        "Test Project",
        NOW,
        NOW,
    )
    return project_id


async def _make_item(
    db,
    user_id: str,
    project_id: str,
    *,
    title: str = "Test Item",
    files_to_modify: list[dict] | None = None,
) -> str:
    if files_to_modify is None:
        files_to_modify = [{"path": f"src/{uuid.uuid4().hex}.py", "change": "x"}]
    item_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO items "
        "(id, project_id, user_id, title, description, status, "
        " labels, acceptance_criteria, files_to_modify, scope_out, "
        " build_engine, commit_type, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)",
        item_id,
        project_id,
        user_id,
        title,
        "",
        "ready",
        encode_json_list([]),
        encode_json_list(["AC-1"]),
        encode_file_specs(files_to_modify),
        encode_json_list([]),
        "claude-code",
        "feat",
        NOW,
        NOW,
    )
    return item_id


async def _add_blocker(db, item_id: str, blocker_item_id: str) -> None:
    """Insert an item_dependencies row directly (bypasses the write-time checks)."""
    await db.execute(
        "INSERT INTO item_dependencies (id, item_id, blocker_item_id, created_at) "
        "VALUES ($1, $2, $3, $4)",
        str(uuid.uuid4()),
        item_id,
        blocker_item_id,
        NOW,
    )


def _pairs(edges) -> set[tuple[str, str]]:
    return {(e["from_item_id"], e["to_item_id"]) for e in edges}


# ---------------------------------------------------------------------------
# The bulk dependency query — must be valid on BOTH backends
# ---------------------------------------------------------------------------


class TestDependencyPairsSql:
    def test_restricts_both_endpoints(self) -> None:
        sql = dependency_pairs_sql(2)

        assert "item_id IN ($1, $2)" in sql
        assert "blocker_item_id IN ($3, $4)" in sql

    def test_postgres_placeholder_style(self) -> None:
        """asyncpg requires numbered $n placeholders, contiguous from $1."""
        sql = dependency_pairs_sql(3)
        found = [int(m) for m in re.findall(r"\$(\d+)", sql)]

        assert found == [1, 2, 3, 4, 5, 6]

    def test_sqlite_placeholder_expansion_matches_arg_count(self) -> None:
        """SqlitePool rewrites $n → ?; the count must still match the binds."""
        sql = dependency_pairs_sql(3)
        converted = _pg_to_sqlite(sql)

        assert "$" not in converted
        # 2 * 3 IDs are bound, so 6 '?' placeholders must survive the rewrite.
        assert converted.count("?") == 6

    async def test_executes_against_the_sqlite_pool(self, db) -> None:
        """The exact production statement runs on the SQLite backend."""
        user_id = await _make_user(db)
        project_id = await _make_project(db, user_id)
        a = await _make_item(db, user_id, project_id)
        b = await _make_item(db, user_id, project_id)
        await _add_blocker(db, b, a)

        rows = await db.fetch(dependency_pairs_sql(2), a, b, a, b)

        assert [(str(r["item_id"]), str(r["blocker_item_id"])) for r in rows] == [
            (b, a)
        ]

    async def test_empty_item_ids_short_circuits(self, db) -> None:
        assert await fetch_dependency_pairs(db, []) == []

    async def test_duplicate_ids_are_collapsed(self, db) -> None:
        user_id = await _make_user(db)
        project_id = await _make_project(db, user_id)
        a = await _make_item(db, user_id, project_id)
        b = await _make_item(db, user_id, project_id)
        await _add_blocker(db, b, a)

        assert await fetch_dependency_pairs(db, [a, b, a, b]) == [(b, a)]


# ---------------------------------------------------------------------------
# Blocker-derived edges
# ---------------------------------------------------------------------------


class TestComputeBlockerEdges:
    async def test_no_blockers_yields_no_edges(self, db) -> None:
        user_id = await _make_user(db)
        project_id = await _make_project(db, user_id)
        ids = [await _make_item(db, user_id, project_id) for _ in range(3)]

        assert await compute_blocker_edges(db, ids) == []

    async def test_linear_chain(self, db) -> None:
        """a → b → c: two edges and exactly one item with in-degree zero."""
        user_id = await _make_user(db)
        project_id = await _make_project(db, user_id)
        a = await _make_item(db, user_id, project_id, title="a")
        b = await _make_item(db, user_id, project_id, title="b")
        c = await _make_item(db, user_id, project_id, title="c")
        await _add_blocker(db, b, a)  # b blocked by a
        await _add_blocker(db, c, b)  # c blocked by b

        edges = await compute_blocker_edges(db, [a, b, c])

        assert _pairs(edges) == {(a, b), (b, c)}
        in_degree = dict.fromkeys((a, b, c), 0)
        for edge in edges:
            in_degree[edge["to_item_id"]] += 1
        ready = [i for i, d in in_degree.items() if d == 0]
        assert ready == [a]

    async def test_diamond_in_degrees(self, db) -> None:
        """a → {b, c} → d yields in-degrees 0, 1, 1, 2."""
        user_id = await _make_user(db)
        project_id = await _make_project(db, user_id)
        a = await _make_item(db, user_id, project_id, title="a")
        b = await _make_item(db, user_id, project_id, title="b")
        c = await _make_item(db, user_id, project_id, title="c")
        d = await _make_item(db, user_id, project_id, title="d")
        await _add_blocker(db, b, a)
        await _add_blocker(db, c, a)
        await _add_blocker(db, d, b)
        await _add_blocker(db, d, c)

        edges = await compute_blocker_edges(db, [a, b, c, d])

        assert _pairs(edges) == {(a, b), (a, c), (b, d), (c, d)}
        in_degree = dict.fromkeys((a, b, c, d), 0)
        for edge in edges:
            in_degree[edge["to_item_id"]] += 1
        assert [in_degree[i] for i in (a, b, c, d)] == [0, 1, 1, 2]

    async def test_out_of_set_blocker_yields_no_edge(self, db) -> None:
        """An in-set item blocked by an OUT-of-set item produces NO edge.

        Without restricting *both* endpoints, the edge would name a node that
        is not in ``nodes``; the predecessor could never become terminal and
        the dependent item would stay blocked for the life of the rollout.
        """
        user_id = await _make_user(db)
        project_id = await _make_project(db, user_id)
        inside = await _make_item(db, user_id, project_id, title="inside")
        outside = await _make_item(db, user_id, project_id, title="outside")
        await _add_blocker(db, inside, outside)

        edges = await compute_blocker_edges(db, [inside])

        assert edges == []

    async def test_out_of_set_blocked_item_yields_no_edge(self, db) -> None:
        """The reverse direction is restricted too: blocked item outside the set."""
        user_id = await _make_user(db)
        project_id = await _make_project(db, user_id)
        inside = await _make_item(db, user_id, project_id, title="inside")
        outside = await _make_item(db, user_id, project_id, title="outside")
        await _add_blocker(db, outside, inside)

        assert await compute_blocker_edges(db, [inside]) == []

    async def test_edge_order_is_deterministic(self, db) -> None:
        """Edges come back ordered by the caller's item_ids ordering."""
        user_id = await _make_user(db)
        project_id = await _make_project(db, user_id)
        a = await _make_item(db, user_id, project_id, title="a")
        b = await _make_item(db, user_id, project_id, title="b")
        c = await _make_item(db, user_id, project_id, title="c")
        await _add_blocker(db, c, b)
        await _add_blocker(db, b, a)

        edges = await compute_blocker_edges(db, [a, b, c])

        assert [(e["from_item_id"], e["to_item_id"]) for e in edges] == [
            (a, b),
            (b, c),
        ]


# ---------------------------------------------------------------------------
# derive_edges — integration of both sources
# ---------------------------------------------------------------------------


class TestDeriveEdges:
    async def test_overlap_edge_without_any_blocker(self, db) -> None:
        """Two items with overlapping files_to_modify are serialised."""
        user_id = await _make_user(db)
        project_id = await _make_project(db, user_id)
        shared = [{"path": "agent_gtd/src/agent_gtd/main.py", "change": "x"}]
        a = await _make_item(db, user_id, project_id, files_to_modify=shared)
        b = await _make_item(db, user_id, project_id, files_to_modify=shared)
        items = await db.fetch(
            "SELECT * FROM items WHERE id IN ($1, $2)",
            a,
            b,
        )

        edges = await derive_edges(db, [dict(r) for r in items], [a, b])

        assert _pairs(edges) == {(a, b)}

    async def test_blocker_and_overlap_between_same_pair_dedupe(self, db) -> None:
        user_id = await _make_user(db)
        project_id = await _make_project(db, user_id)
        shared = [{"path": "agent_gtd/src/agent_gtd/main.py", "change": "x"}]
        a = await _make_item(db, user_id, project_id, files_to_modify=shared)
        b = await _make_item(db, user_id, project_id, files_to_modify=shared)
        await _add_blocker(db, b, a)
        items = await db.fetch("SELECT * FROM items WHERE id IN ($1, $2)", a, b)

        edges = await derive_edges(db, [dict(r) for r in items], [a, b])

        assert len(edges) == 1
        assert _pairs(edges) == {(a, b)}

    async def test_no_blockers_no_overlap_yields_empty(self, db) -> None:
        user_id = await _make_user(db)
        project_id = await _make_project(db, user_id)
        a = await _make_item(
            db, user_id, project_id, files_to_modify=[{"path": "a.py", "change": "x"}]
        )
        b = await _make_item(
            db, user_id, project_id, files_to_modify=[{"path": "b.py", "change": "x"}]
        )
        items = await db.fetch("SELECT * FROM items WHERE id IN ($1, $2)", a, b)

        assert await derive_edges(db, [dict(r) for r in items], [a, b]) == []

    async def test_cycle_in_item_dependencies_trips_the_assert(self, db) -> None:
        """A cycle injected straight into item_dependencies is caught at read time."""
        user_id = await _make_user(db)
        project_id = await _make_project(db, user_id)
        a = await _make_item(
            db, user_id, project_id, files_to_modify=[{"path": "a.py", "change": "x"}]
        )
        b = await _make_item(
            db, user_id, project_id, files_to_modify=[{"path": "b.py", "change": "x"}]
        )
        # add_blocker's write-time BFS would reject the second row; inserting
        # directly simulates an edge that arrived by any other route.
        await _add_blocker(db, b, a)
        await _add_blocker(db, a, b)
        items = await db.fetch("SELECT * FROM items WHERE id IN ($1, $2)", a, b)

        with pytest.raises(ValueError, match="cyclic dependency detected"):
            await derive_edges(db, [dict(r) for r in items], [a, b])


# ---------------------------------------------------------------------------
# Ported from agent-gtd-dispatch tests/test_rollout_planner.py::TestPathsOverlap
# ---------------------------------------------------------------------------


class TestPathsOverlap:
    def test_identical_paths_overlap(self) -> None:
        assert _paths_overlap("src/foo.py", "src/foo.py") is True

    def test_different_paths_do_not_overlap(self) -> None:
        assert _paths_overlap("src/foo.py", "src/bar.py") is False

    def test_trailing_slash_directory_overlaps_nested_file(self) -> None:
        assert (
            _paths_overlap(
                "agent-gtd-dispatch/tests/", "agent-gtd-dispatch/tests/test_foo.py"
            )
            is True
        )
        assert (
            _paths_overlap(
                "agent-gtd-dispatch/tests/test_foo.py", "agent-gtd-dispatch/tests/"
            )
            is True
        )

    def test_no_extension_directory_overlaps_nested_file(self) -> None:
        assert (
            _paths_overlap(
                "agent-gtd-dispatch/tests", "agent-gtd-dispatch/tests/test_foo.py"
            )
            is True
        )
        assert (
            _paths_overlap(
                "agent-gtd-dispatch/tests/test_foo.py", "agent-gtd-dispatch/tests"
            )
            is True
        )

    def test_directory_does_not_overlap_sibling_file(self) -> None:
        # src/foo is a dir; src/foobar.py is NOT beneath it
        assert _paths_overlap("src/foo", "src/foobar.py") is False

    def test_file_with_extension_not_treated_as_directory(self) -> None:
        # setup-dispatch-host.sh has an extension → not a directory
        assert (
            _paths_overlap(
                "agent-gtd-dispatch/setup-dispatch-host.sh",
                "agent-gtd-dispatch/setup-dispatch-host.sh/extra",
            )
            is False
        )

    def test_normalized_trailing_slash_matches(self) -> None:
        # "src/foo/" vs "src/foo" — same after normalisation
        assert _paths_overlap("src/foo/", "src/foo/") is True
        assert _paths_overlap("src/foo/", "src/foo") is True

    def test_is_directory_entry(self) -> None:
        assert _is_directory_entry("src/foo/") is True
        assert _is_directory_entry("src/foo") is True
        assert _is_directory_entry("src/foo.py") is False


# ---------------------------------------------------------------------------
# Ported: TestComputeOverlapEdges
# ---------------------------------------------------------------------------


class TestComputeOverlapEdges:
    def test_two_items_same_exact_path(self) -> None:
        items = [
            {
                "id": "a",
                "files_to_modify": [
                    {"path": "agent-gtd-dispatch/setup.sh", "change": "add line"}
                ],
            },
            {
                "id": "b",
                "files_to_modify": [
                    {"path": "agent-gtd-dispatch/setup.sh", "change": "remove line"}
                ],
            },
        ]
        edges = compute_overlap_edges(items, ["a", "b"])

        assert len(edges) == 1
        assert edges[0]["from_item_id"] == "a"
        assert edges[0]["to_item_id"] == "b"

    def test_no_shared_paths_no_edges(self) -> None:
        items = [
            {"id": "a", "files_to_modify": [{"path": "src/foo.py", "change": "x"}]},
            {"id": "b", "files_to_modify": [{"path": "src/bar.py", "change": "y"}]},
        ]

        assert compute_overlap_edges(items, ["a", "b"]) == []

    def test_three_items_same_file_yields_chain(self) -> None:
        """Regression: three items sharing the same file must be fully serialised."""
        items = [
            {
                "id": i,
                "files_to_modify": [{"path": "agent_gtd/README.md", "change": i}],
            }
            for i in ("a", "b", "c")
        ]
        edges = compute_overlap_edges(items, ["a", "b", "c"])

        edge_pairs = _pairs(edges)
        # All three pairs must be present so the items are totally ordered
        assert ("a", "b") in edge_pairs
        assert ("a", "c") in edge_pairs
        assert ("b", "c") in edge_pairs

    def test_four_items_same_file_fully_serialised(self) -> None:
        """Regression for AL2023-feedback wave: four items editing same shell script."""
        path = "agent-gtd-dispatch/setup-dispatch-host.sh"
        items = [
            {"id": str(i), "files_to_modify": [{"path": path, "change": ""}]}
            for i in range(4)
        ]
        edges = compute_overlap_edges(items, [str(i) for i in range(4)])

        edge_pairs = _pairs(edges)
        for i in range(4):
            for j in range(i + 1, 4):
                assert (str(i), str(j)) in edge_pairs, f"Missing edge {i}→{j}"

    def test_directory_overlap_with_nested_file(self) -> None:
        items = [
            {
                "id": "a",
                "files_to_modify": [
                    {"path": "agent-gtd-dispatch/tests/", "change": "dir"}
                ],
            },
            {
                "id": "b",
                "files_to_modify": [
                    {"path": "agent-gtd-dispatch/tests/test_foo.py", "change": "file"}
                ],
            },
        ]
        edges = compute_overlap_edges(items, ["a", "b"])

        assert len(edges) == 1
        assert edges[0]["from_item_id"] == "a"
        assert edges[0]["to_item_id"] == "b"

    def test_preserves_input_order_for_edge_direction(self) -> None:
        items = [
            {"id": "b", "files_to_modify": [{"path": "shared.py", "change": ""}]},
            {"id": "a", "files_to_modify": [{"path": "shared.py", "change": ""}]},
        ]
        # b comes before a in item_ids, so edge should be b→a
        edges = compute_overlap_edges(items, ["b", "a"])

        assert len(edges) == 1
        assert edges[0]["from_item_id"] == "b"
        assert edges[0]["to_item_id"] == "a"

    def test_empty_files_to_modify_no_edges(self) -> None:
        items = [
            {"id": "a", "files_to_modify": []},
            {"id": "b", "files_to_modify": []},
        ]

        assert compute_overlap_edges(items, ["a", "b"]) == []

    def test_json_encoded_files_to_modify_is_decoded(self) -> None:
        """Raw item rows carry files_to_modify as JSON text, not a list."""
        items = [
            {
                "id": "a",
                "files_to_modify": encode_file_specs(
                    [{"path": "shared.py", "change": ""}]
                ),
            },
            {
                "id": "b",
                "files_to_modify": encode_file_specs(
                    [{"path": "shared.py", "change": ""}]
                ),
            },
        ]

        assert _pairs(compute_overlap_edges(items, ["a", "b"])) == {("a", "b")}

    def test_null_files_to_modify_no_edges(self) -> None:
        items = [
            {"id": "a", "files_to_modify": None},
            {"id": "b", "files_to_modify": None},
        ]

        assert compute_overlap_edges(items, ["a", "b"]) == []

    def test_non_list_files_to_modify_no_edges(self) -> None:
        items = [
            {"id": "a", "files_to_modify": {"path": "shared.py"}},
            {"id": "b", "files_to_modify": {"path": "shared.py"}},
        ]

        assert compute_overlap_edges(items, ["a", "b"]) == []


# ---------------------------------------------------------------------------
# Ported: TestMergeEdges
# ---------------------------------------------------------------------------


class TestMergeEdges:
    def test_disjoint_edges_combined(self) -> None:
        blocker = [{"from_item_id": "a", "to_item_id": "b"}]
        overlap = [{"from_item_id": "b", "to_item_id": "c"}]

        assert len(merge_edges(blocker, overlap)) == 2

    def test_duplicate_edges_deduplicated(self) -> None:
        blocker = [{"from_item_id": "a", "to_item_id": "b"}]
        overlap = [{"from_item_id": "a", "to_item_id": "b"}]

        assert len(merge_edges(blocker, overlap)) == 1

    def test_blocker_edge_preserved_first(self) -> None:
        blocker = [{"from_item_id": "a", "to_item_id": "b"}]

        assert merge_edges(blocker, [])[0]["from_item_id"] == "a"

    def test_empty_inputs(self) -> None:
        assert merge_edges([], []) == []


# ---------------------------------------------------------------------------
# Ported: acyclicity backstop
# ---------------------------------------------------------------------------


class TestAssertAcyclic:
    def test_empty_graph_is_acyclic(self) -> None:
        assert_acyclic([], [])

    def test_linear_chain_is_acyclic(self) -> None:
        assert_acyclic(
            ["a", "b", "c"],
            [
                {"from_item_id": "a", "to_item_id": "b"},
                {"from_item_id": "b", "to_item_id": "c"},
            ],
        )

    def test_two_node_cycle_raises(self) -> None:
        with pytest.raises(ValueError, match=r"2 node\(s\) involved in a cycle"):
            assert_acyclic(
                ["a", "b"],
                [
                    {"from_item_id": "a", "to_item_id": "b"},
                    {"from_item_id": "b", "to_item_id": "a"},
                ],
            )

    def test_self_loop_raises(self) -> None:
        with pytest.raises(ValueError, match=r"1 node\(s\) involved in a cycle"):
            assert_acyclic(["a"], [{"from_item_id": "a", "to_item_id": "a"}])

    def test_cycle_message_names_only_cyclic_nodes(self) -> None:
        with pytest.raises(ValueError, match=r"2 node\(s\) involved in a cycle"):
            assert_acyclic(
                ["a", "b", "c"],
                [
                    {"from_item_id": "b", "to_item_id": "c"},
                    {"from_item_id": "c", "to_item_id": "b"},
                ],
            )
