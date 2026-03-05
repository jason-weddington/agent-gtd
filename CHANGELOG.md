# CHANGELOG

<!-- version list -->

## v1.14.0 (2026-03-05)

### Features

- Replace project review accordion with carousel and quick-add
  ([`212ba6f`](https://github.com/home/jason/git/agent_gtd/commit/212ba6fd78459ae16a528655a7283addd1696120))


## v1.13.0 (2026-03-04)

### Features

- Add Enter-to-submit on all create/edit dialogs
  ([`891d04a`](https://github.com/home/jason/git/agent_gtd/commit/891d04ab07379cfb73d7e42e91db0b021ee41c61))


## v1.12.0 (2026-03-04)

### Features

- Add Cmd+1-7 keyboard shortcuts for sidebar navigation
  ([`c9bf49c`](https://github.com/home/jason/git/agent_gtd/commit/c9bf49cd44f38a121b9b62323ba6485e8679aada))


## v1.11.3 (2026-03-04)

### Bug Fixes

- Wrap long item titles in review rows instead of truncating
  ([`1d22d47`](https://github.com/home/jason/git/agent_gtd/commit/1d22d47fdf09a8d52ec19ce479a0ca7fbfb7f9d7))


## v1.11.2 (2026-03-04)

### Bug Fixes

- Prevent long item titles from overflowing review layout
  ([`3b1bfa4`](https://github.com/home/jason/git/agent_gtd/commit/3b1bfa47d261d9c20b9ceb645fd29c5869601f84))


## v1.11.1 (2026-03-04)

### Bug Fixes

- Improve inbox processor navigation and action layout
  ([`9ca3298`](https://github.com/home/jason/git/agent_gtd/commit/9ca3298835b2056a8935ab3f88ee97fc36b6e162))


## v1.11.0 (2026-03-04)

### Chores

- Re-enable DB tests on push now that SQLite backend is fast
  ([`8d588f8`](https://github.com/home/jason/git/agent_gtd/commit/8d588f88e03906957995fd28736b8beae65140b3))

### Features

- Redesign weekly review as step-by-step wizard
  ([`62c39a6`](https://github.com/home/jason/git/agent_gtd/commit/62c39a6b759a03168ce89e610ee79219e488df22))


## v1.10.0 (2026-03-03)

### Chores

- Skip DB tests on push, add SKIP_DB_TESTS=1 env flag
  ([`4b08423`](https://github.com/home/jason/git/agent_gtd/commit/4b08423787aa3cfa3b93de2da24648c2e270761c))

### Features

- In-memory SQLite test backend for fast offline testing
  ([`7aff243`](https://github.com/home/jason/git/agent_gtd/commit/7aff2432c2e7ffa30fedcc5601985b5fd5c348d3))


## v1.9.2 (2026-03-03)

### Bug Fixes

- Inbox project-less items, quick capture focus, delete dialog sizing, header casing
  ([`79a71e4`](https://github.com/home/jason/git/agent_gtd/commit/79a71e435a900614f2ed49521e875d1ccb7d4ca6))

### Chores

- Add "check the KB first" guidance to CLAUDE.md
  ([`f060f54`](https://github.com/home/jason/git/agent_gtd/commit/f060f54de990e4d4905370bd1a106e2bf9e84381))

- Add deployment info to CLAUDE.md
  ([`f2d22cb`](https://github.com/home/jason/git/agent_gtd/commit/f2d22cb1d346dfe411bce92f5473414679d09e68))

- Delete roadmap, add Agent GTD dogfooding mandate to CLAUDE.md
  ([`59ac1ce`](https://github.com/home/jason/git/agent_gtd/commit/59ac1ce9afd4d148a9f21a544d9df95fb385abbb))


## v1.9.1 (2026-03-03)

### Bug Fixes

- QuickCapture Tab, NoteEditor min-height, global Esc hotkey
  ([`c05e407`](https://github.com/home/jason/git/agent_gtd/commit/c05e407d23fb1003ba843b321c4501c31cdd9d6b))


## v1.9.0 (2026-03-02)

### Features

- Add nginx + systemd deployment configs
  ([`2595f04`](https://github.com/home/jason/git/agent_gtd/commit/2595f046460863a0a844eb7d8f0407e230b9dbd8))


## v1.8.1 (2026-03-02)

### Bug Fixes

- Start.sh signal handling for clean systemd shutdown
  ([`d8b6878`](https://github.com/home/jason/git/agent_gtd/commit/d8b68782796e42f98d844734979de5fd994ee0c0))

### Chores

- Remove .mcp.json from tracking (contains credentials)
  ([`be49728`](https://github.com/home/jason/git/agent_gtd/commit/be49728612dafa7932fb6edc384f8c695178142e))


## v1.8.0 (2026-03-02)

### Features

- Add weekly review page with guided three-section flow
  ([`6a3e230`](https://github.com/home/jason/git/agent_gtd/commit/6a3e2301214b878871c98e5203c7b6d264136c7c))


## v1.7.0 (2026-03-02)

### Features

- Add inbox processor for sequential card-based triage
  ([`9182f0e`](https://github.com/home/jason/git/agent_gtd/commit/9182f0e6a9f62c54a959709e86dce7c161cd0acf))


## v1.6.0 (2026-03-01)

### Chores

- Lower coverage threshold to 93% for SSE streaming
  ([`32ce732`](https://github.com/home/jason/git/agent_gtd/commit/32ce73219c97833e37716e455875436a236bf9fd))

### Features

- Add global quick capture overlay and kanban board
  ([`1de8754`](https://github.com/home/jason/git/agent_gtd/commit/1de87543523f46609ac8f3e7571cf466028de64e))


## v1.5.0 (2026-03-01)

### Documentation

- Update roadmap for post-Phase 4 partial status
  ([`f644928`](https://github.com/home/jason/git/agent_gtd/commit/f644928e3413cfa8a8f7a6b164dcfaaacdb7ee25))

### Features

- Add real-time SSE sync for browser updates
  ([`77203ca`](https://github.com/home/jason/git/agent_gtd/commit/77203ca07027f60d41afcbfdfa988aa0deaeb3c0))


## v1.4.1 (2026-03-01)

### Bug Fixes

- Prevent semantic-release from auto-pushing on version bump
  ([`d151f4d`](https://github.com/home/jason/git/agent_gtd/commit/d151f4d229e97d3e0c5eeca4e358f545da44c191))


## v1.4.0 (2026-03-01)

### Documentation

- Update roadmap and domain for post-migration status
  ([`3011b47`](https://github.com/home/jason/git/agent_gtd/commit/3011b475555f3906a7f1eef25f6e78024d5f0a76))

### Features

- Add GTD list views (Next Actions, Waiting For, Someday/Maybe)
  ([`3205195`](https://github.com/home/jason/git/agent_gtd/commit/3205195311369ff2bf170d383d3b72483f0f9b12))


## v1.3.1 (2026-02-28)

### Bug Fixes

- Source .env in pre-push coverage hook for DATABASE_URL
  ([`d2b5813`](https://github.com/home/jason/git/agent_gtd/commit/d2b5813ede57af26f7ea924ad4947f06efd8b591))


## v1.3.0 (2026-02-28)

### Features

- Migrate from SQLite to PostgreSQL
  ([`8488a86`](https://github.com/home/jason/git/agent_gtd/commit/8488a86a7457d1c917870ea8a10558e71f07c788))


## v1.2.0 (2026-02-28)

### Features

- Wire up MCP server for Claude Code dogfooding
  ([`abc65a0`](https://github.com/home/jason/git/agent_gtd/commit/abc65a08d7826777f357905ca3520860a91e87d1))


## v1.1.0 (2026-02-28)

### Chores

- Enforce conventional commits only on main branch
  ([`8073b0a`](https://github.com/home/jason/git/agent_gtd/commit/8073b0a6add4edaec66c961be1ece7d393ec6b56))

### Features

- Add MCP server with service layer and optimistic locking
  ([`83902f0`](https://github.com/home/jason/git/agent_gtd/commit/83902f0663a266025c0ad334f51fcbc006428354))


## v1.0.0 (2026-02-28)

- Initial Release
