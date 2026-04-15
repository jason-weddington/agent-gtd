# CHANGELOG

<!-- version list -->

## v1.40.0 (2026-04-15)

### Chores

- Add deploy.sh to gitignore
  ([`eb714c9`](https://github.com/jason-weddington/agent-gtd/commit/eb714c9b353bcecdaf244e95b6f4a27f004d5c90))

### Features

- **mcp**: Add delete_item tool
  ([`10c354b`](https://github.com/jason-weddington/agent-gtd/commit/10c354b689b130be188490f66eafd1b650144d1e))


## v1.39.0 (2026-04-15)

### Features

- **frontend**: Show short item ID with copy-to-clipboard in card and detail views
  ([`c14f63d`](https://github.com/jason-weddington/agent-gtd/commit/c14f63d370f234c81fff4eb6467260d5e0f177b8))


## v1.38.7 (2026-04-15)

### Bug Fixes

- **frontend**: Remove misleading "tab for options" hint from quick capture
  ([`a6f1e36`](https://github.com/jason-weddington/agent-gtd/commit/a6f1e3601f17601f8cf5ebc471f67e98211ab7c7))


## v1.38.6 (2026-04-15)

### Bug Fixes

- **frontend**: Truncate long project descriptions in list view
  ([`5d68eea`](https://github.com/jason-weddington/agent-gtd/commit/5d68eea85bdfdab18df05b87d7a6a6bb064a1357))


## v1.38.5 (2026-04-15)

### Bug Fixes

- Route dispatch MCP tools through _backend abstraction
  ([`6c191d0`](https://github.com/jason-weddington/agent-gtd/commit/6c191d0a482dbcf6ad926ef9fc3d0fb05fd43dce))


## v1.38.4 (2026-04-15)

### Bug Fixes

- Hide login tool when API key is set, remove switch_project
  ([`c74b276`](https://github.com/jason-weddington/agent-gtd/commit/c74b2766e76afc1fe662a2b15bf44753833a3e48))


## v1.38.3 (2026-04-14)

### Bug Fixes

- Cap description height in item detail drawer
  ([`5b099f7`](https://github.com/jason-weddington/agent-gtd/commit/5b099f78f2fbadd6faa82c22bb794479ab041a89))


## v1.38.2 (2026-04-14)

### Bug Fixes

- Add HttpBackend comment CRUD tests
  ([`2c4a4f7`](https://github.com/jason-weddington/agent-gtd/commit/2c4a4f743ba22541b6ac7e75e15efbf0cca09277))

### Documentation

- Add MIT license
  ([`6dfbfd9`](https://github.com/jason-weddington/agent-gtd/commit/6dfbfd928cd720fe2da0c068a6d34c285274a0e9))


## v1.38.1 (2026-04-14)

### Bug Fixes

- Preflight health check before dispatch
  ([`83ef8fc`](https://github.com/jason-weddington/agent-gtd/commit/83ef8fcbc18903411e76ac23ded05436d1b638e8))

### Chores

- Bump default max_turns from 20 to 50
  ([`eca75ac`](https://github.com/jason-weddington/agent-gtd/commit/eca75ace13ef5f0493a294cac2cb9bea7bc05168))

### Refactoring

- Centralize max_turns default in dispatch_worker
  ([`32f8733`](https://github.com/jason-weddington/agent-gtd/commit/32f87339b318f9c271f57d3bf306b0dc28ff1f98))


## v1.38.0 (2026-04-07)

### Features

- Complete send-to-claude dispatch UI and MCP tools
  ([`c7dec36`](https://github.com/jason-weddington/agent-gtd/commit/c7dec3645bcc932db246fb5559fd7c9865e17235))


## v1.37.0 (2026-04-07)

### Features

- Add dispatch worker for headless Claude Code agents (Phase 2B)
  ([`e949c6f`](https://github.com/jason-weddington/agent-gtd/commit/e949c6f5ae0438429e43eb08509801316f0660b8))


## v1.36.0 (2026-04-07)

### Features

- Add dispatch run tracking (Phase 2A)
  ([`897b594`](https://github.com/jason-weddington/agent-gtd/commit/897b59455a0013b5fa549899c7bffd09febf73f2))


## v1.35.0 (2026-04-07)

### Features

- Add kb_project_ref field to projects for KB-aware dispatch
  ([`131356e`](https://github.com/jason-weddington/agent-gtd/commit/131356e15b9050a72ed6526022d7e1a6e54fa196))


## v1.34.5 (2026-04-06)

### Bug Fixes

- Install pre-commit hooks in dispatch workspace after clone
  ([`6208a84`](https://github.com/jason-weddington/agent-gtd/commit/6208a844120a2bcc8312c1800c4bc6bf36ced3fe))


## v1.34.4 (2026-04-06)

### Bug Fixes

- Correct KB env vars in dispatch script
  ([`3f6ad49`](https://github.com/jason-weddington/agent-gtd/commit/3f6ad496ca44ce6bcf0e9420c6c9479d0358f345))


## v1.34.3 (2026-04-06)

### Bug Fixes

- Dispatch script env vars, branch name, and CLI flag
  ([`408f418`](https://github.com/jason-weddington/agent-gtd/commit/408f418bca6c7e2528ee5e671a7093d6525b269f))


## v1.34.2 (2026-04-06)

### Bug Fixes

- Use temporary drawer to avoid covering page controls
  ([`df4e905`](https://github.com/jason-weddington/agent-gtd/commit/df4e9054c8699830b0aee8f25eb7cc04eabed837))


## v1.34.1 (2026-04-06)

### Bug Fixes

- Offset detail drawer below app header
  ([`11daa73`](https://github.com/jason-weddington/agent-gtd/commit/11daa735ad1169d725f55de3981bfc20e05742a3))


## v1.34.0 (2026-04-06)

### Chores

- Configure semantic-release remote for GitHub changelog links
  ([`ded0f5f`](https://github.com/jason-weddington/agent-gtd/commit/ded0f5f4ca7350b4643fbedd2def60dfee309f37))

### Features

- Add git_origin field and dispatch script (send-to-claude phase 1)
  ([`a2a5f7f`](https://github.com/jason-weddington/agent-gtd/commit/a2a5f7f39bd289b83dcf5193e852e2bae6c820ef))


## v1.33.1 (2026-04-06)

### Bug Fixes

- Restore test coverage above 92% threshold
  ([`e860b89`](https://github.com/home/jason/git/agent_gtd/commit/e860b8994b5e41f58e35f65d04d8b5944b45aef7))


## v1.33.0 (2026-04-06)

### Bug Fixes

- Patch SSE auth tests to monkeypatch local mode
  ([`ee5a878`](https://github.com/home/jason/git/agent_gtd/commit/ee5a87810bc5d11649b5df779d3a6bf4df497c84))

- Prevent Escape from exiting Safari fullscreen globally
  ([`d39dce8`](https://github.com/home/jason/git/agent_gtd/commit/d39dce860eac96a1529fc8b438e3b8b253fc7bdb))

### Features

- Add item detail drawer with comment thread
  ([`4938430`](https://github.com/home/jason/git/agent_gtd/commit/49384307db5f4f44604161efa8dbc9fe8961468d))


## v1.32.0 (2026-04-05)

### Features

- Add comments for items and projects
  ([`178736a`](https://github.com/home/jason/git/agent_gtd/commit/178736af6a625f909827ef63f1d24c75653734fc))


## v1.31.0 (2026-03-24)

### Features

- Complete projects from list + default project items to next_action
  ([`60861a5`](https://github.com/home/jason/git/agent_gtd/commit/60861a5bae9a0fddf9df6180aec556ec0aa1b943))


## v1.30.0 (2026-03-23)

### Bug Fixes

- Always register login tool in non-local mode and isolate MCP tests
  ([`5042375`](https://github.com/home/jason/git/agent_gtd/commit/50423759e7868042da40cefab133020f45af5584))

- Use system trust store for HttpBackend SSL verification
  ([`6d2773c`](https://github.com/home/jason/git/agent_gtd/commit/6d2773ce22614ce20411a2a1f5a4011d04fa17bc))

- Use truststore for OS-native SSL cert verification
  ([`a96d78c`](https://github.com/home/jason/git/agent_gtd/commit/a96d78c43223373bcc568fc14208e6c0ddcefe15))

### Features

- Refresh project view after QuickCapture
  ([`77cb3f1`](https://github.com/home/jason/git/agent_gtd/commit/77cb3f19579bc57f27d5560171622a8ee811e6ed))


## v1.29.0 (2026-03-22)

### Chores

- Remove redundant test_switch_project_without_login
  ([`14c0d1d`](https://github.com/home/jason/git/agent_gtd/commit/14c0d1db8363bec2f46bdc25d58ab50b61b0d180))

### Features

- MCP HTTP backend — remote mode calls FastAPI API instead of DB
  ([`4d4decd`](https://github.com/home/jason/git/agent_gtd/commit/4d4decde295bb13b906a7b1c483c0dbeb9b314c5))


## v1.28.2 (2026-03-22)

### Bug Fixes

- Clear _ENV_API_KEY in test_switch_project_without_login too
  ([`416b572`](https://github.com/home/jason/git/agent_gtd/commit/416b572d4b02143d8e87ac90a06036b8348c4182))


## v1.28.1 (2026-03-22)

### Bug Fixes

- Clear _ENV_API_KEY in test_tool_without_login to avoid auto-login
  ([`fc47ace`](https://github.com/home/jason/git/agent_gtd/commit/fc47ace95bcbec725ff85d454912f639d33f8aaf))


## v1.28.0 (2026-03-22)

### Documentation

- Update README with API key auth setup instructions
  ([`205ebb6`](https://github.com/home/jason/git/agent_gtd/commit/205ebb6df96943f92506ff1cee6ef0b3a2ba171c))

### Features

- Add complete button and hide-completed toggle in project list view
  ([`1777505`](https://github.com/home/jason/git/agent_gtd/commit/1777505f6cc9b58b673a5e520df633c7e4ea500c))


## v1.27.0 (2026-03-20)

### Features

- API key auth with MCP auto-login
  ([`ece6857`](https://github.com/home/jason/git/agent_gtd/commit/ece6857fdd9856a53031c296d43ab2fa369c529e))


## v1.26.0 (2026-03-19)

### Features

- Cmd/Ctrl+Enter saves and closes dialogs from textareas
  ([`db76d2a`](https://github.com/home/jason/git/agent_gtd/commit/db76d2a0335be2ec8380f03fc61d00d8c21b21a6))


## v1.25.0 (2026-03-19)

### Features

- Context-aware quick capture from project views
  ([`7fad585`](https://github.com/home/jason/git/agent_gtd/commit/7fad585548f3ddfbdc8e22975b4fa79e38cb99ba))


## v1.24.0 (2026-03-19)

### Features

- Add search to GTD list views and fix quick capture focus
  ([`e8f881b`](https://github.com/home/jason/git/agent_gtd/commit/e8f881b8b80610982bdb15ccb47c56871d76a89a))


## v1.23.2 (2026-03-18)

### Bug Fixes

- Simplify light theme to match photoqueue — only set primary, secondary, background
  ([`724f1cc`](https://github.com/home/jason/git/agent_gtd/commit/724f1cc34f2f9ce2c6f403e281039c54f4431b17))


## v1.23.1 (2026-03-18)

### Bug Fixes

- Prevent Escape key from exiting browser fullscreen when dialogs are open
  ([`cf863b4`](https://github.com/home/jason/git/agent_gtd/commit/cf863b455df4250fa7daafab7516fd02b40bf63b))


## v1.23.0 (2026-03-17)

### Features

- Improve projects page with search, list view, and light mode theme
  ([`aeb90d9`](https://github.com/home/jason/git/agent_gtd/commit/aeb90d91bfd22ce69f490cc4127562fe5d929593))


## v1.22.0 (2026-03-13)

### Features

- Simplify item statuses and align labels with kanban columns
  ([`d42fc40`](https://github.com/home/jason/git/agent_gtd/commit/d42fc406f0d6e802bd9425421188c2c1da6eb9ae))


## v1.21.4 (2026-03-13)

### Bug Fixes

- Remove transitionend handler that hid kanban cards on drag start
  ([`8e42b1f`](https://github.com/home/jason/git/agent_gtd/commit/8e42b1ff41b9bfe483bac7c9a20a0b309be03a07))


## v1.21.3 (2026-03-13)

### Bug Fixes

- Preserve reviewed project count across step navigation
  ([`94ac32c`](https://github.com/home/jason/git/agent_gtd/commit/94ac32c8470296ea22a33359f7e22f068b216ffb))


## v1.21.2 (2026-03-13)

### Bug Fixes

- Move project prev link next to mark reviewed button
  ([`72b77d8`](https://github.com/home/jason/git/agent_gtd/commit/72b77d8e41a97914b5cb8945d3ac5c4976be1cde))


## v1.21.1 (2026-03-13)

### Bug Fixes

- Weekly review UX improvements
  ([`2c9114e`](https://github.com/home/jason/git/agent_gtd/commit/2c9114e7cbb863b83e5fdbfec2a98472bddf685f))


## v1.21.0 (2026-03-13)

### Chores

- Add agent-gtd-mcp console entry point
  ([`22871b5`](https://github.com/home/jason/git/agent_gtd/commit/22871b583dad6732840269ac3c6d6f6c0e426685))

### Features

- Remove project-scoped registration in single-user mode
  ([`57cd253`](https://github.com/home/jason/git/agent_gtd/commit/57cd2535adae908b4fac9bb46db5727181dab16f))


## v1.20.12 (2026-03-10)

### Bug Fixes

- Force tests to always use in-memory SQLite
  ([`6094118`](https://github.com/home/jason/git/agent_gtd/commit/60941187fa31fed8dab33b8cfe1104237822728e))

### Documentation

- Add README with quick start, MCP setup, and dev commands
  ([`f896e6c`](https://github.com/home/jason/git/agent_gtd/commit/f896e6c2cf3a59b54dd6fd566ec106673f5fbf2e))


## v1.20.11 (2026-03-07)

### Bug Fixes

- Use data attribute + !important CSS to prevent React from undoing hide
  ([`2b358f1`](https://github.com/home/jason/git/agent_gtd/commit/2b358f11aa45b72c20072b80b910a6baf98e739b))


## v1.20.10 (2026-03-07)

### Bug Fixes

- Use capture-phase transitionend listener to prevent kanban pop-back
  ([`83107a2`](https://github.com/home/jason/git/agent_gtd/commit/83107a27643c9fcec66959060d0e53baf7c14b09))


## v1.20.9 (2026-03-07)

### Bug Fixes

- Hide kanban card at render time to eliminate Safari drag pop-back
  ([`3826f48`](https://github.com/home/jason/git/agent_gtd/commit/3826f48f97e7d9602405df0013e67ed2ed36af7c))


## v1.20.8 (2026-03-07)

### Bug Fixes

- Add React.memo and GPU compositing to KanbanCard for Safari drag stability
  ([`14b2a94`](https://github.com/home/jason/git/agent_gtd/commit/14b2a94c920a55890dd05ce17d62b8dc65ca30bd))


## v1.20.7 (2026-03-07)

### Bug Fixes

- Imperatively hide source element on drop to prevent Safari pop-back
  ([`20cd40c`](https://github.com/home/jason/git/agent_gtd/commit/20cd40cbcd619bb93d9981f8041e9b36e8555a4b))


## v1.20.6 (2026-03-07)

### Bug Fixes

- Make kanban drop animation near-instant to prevent Safari pop-back
  ([`ec6841c`](https://github.com/home/jason/git/agent_gtd/commit/ec6841c87129f356e34060d031971def17a8c116))


## v1.20.5 (2026-03-07)

### Bug Fixes

- Use flushSync to eliminate kanban card pop-back on drop
  ([`0be4290`](https://github.com/home/jason/git/agent_gtd/commit/0be42908342b5495746f73886bb3053bc05e9bfe))


## v1.20.4 (2026-03-07)

### Bug Fixes

- Eliminate kanban card pop-back with optimistic state update
  ([`0d4757f`](https://github.com/home/jason/git/agent_gtd/commit/0d4757f68aff11978c26dc8729dc5a0614c9ad96))


## v1.20.3 (2026-03-07)

### Bug Fixes

- Replace @dnd-kit/react with @hello-pangea/dnd for reliable kanban drag
  ([`7d72ee1`](https://github.com/home/jason/git/agent_gtd/commit/7d72ee116e3489bf8104a7d7c3407faf03454077))


## v1.20.2 (2026-03-07)

### Bug Fixes

- Kanban drag visual glitch and crash on repeated drags
  ([`93488f0`](https://github.com/home/jason/git/agent_gtd/commit/93488f038fe694249e79bffde93880ccb2467ac4))


## v1.20.1 (2026-03-07)

### Bug Fixes

- Kanban cross-column drag-and-drop
  ([`37aa924`](https://github.com/home/jason/git/agent_gtd/commit/37aa9243026c6ec7bddd5f011df2431dd21a282c))


## v1.20.0 (2026-03-07)

### Features

- Improve project views — icon buttons, kanban columns, clickable cards
  ([`5779c73`](https://github.com/home/jason/git/agent_gtd/commit/5779c732ecbb3d7a9cb4bdce66c4d28f9b59a86f))


## v1.19.0 (2026-03-07)

### Features

- Show app version on settings page
  ([`bb24248`](https://github.com/home/jason/git/agent_gtd/commit/bb242483821358bfb9bc4aa69de20861d65fed66))


## v1.18.0 (2026-03-06)

### Features

- Pin weekly review stepper and nav buttons while content scrolls
  ([`a46f4b6`](https://github.com/home/jason/git/agent_gtd/commit/a46f4b63e8aa728d402ad43bc551a988580dd0b6))


## v1.17.1 (2026-03-06)

### Bug Fixes

- Truncate PostgreSQL test DB at setup to handle stale data from crashed runs
  ([`8c192f4`](https://github.com/home/jason/git/agent_gtd/commit/8c192f4485e325e2f8b507ba180d57168f3b0f0a))


## v1.17.0 (2026-03-06)

### Features

- Improve weekly review navigation UX
  ([`9c4790e`](https://github.com/home/jason/git/agent_gtd/commit/9c4790ebe655f7d8f40b1083288b3c62d66fd56d))


## v1.16.0 (2026-03-06)

### Features

- SQLite fallback + local single-user mode
  ([`81fa4e3`](https://github.com/home/jason/git/agent_gtd/commit/81fa4e398e48b4c3c6d42fe15f0e8815374af3c6))


## v1.15.0 (2026-03-05)

### Features

- Add project_name to MCP tool responses
  ([`5566f7b`](https://github.com/home/jason/git/agent_gtd/commit/5566f7bb05399c18f6c90063c7302f877748e242))


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
