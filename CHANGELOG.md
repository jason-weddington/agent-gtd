# CHANGELOG

<!-- version list -->

## v1.99.0 (2026-08-10)

### Features

- Audit-log project sharing via project_member_added/removed events
  ([`60d893d`](https://github.com/jason-weddington/agent-gtd/commit/60d893d2f5cd733fc5b79a0be625e5ab0094c083))


## v1.98.0 (2026-07-14)

### Features

- Accept build_engine on MCP add_item (thread through mcp_backend)
  ([`0daf587`](https://github.com/jason-weddington/agent-gtd/commit/0daf587b083532b0653fa4e3e3c0e0535db10cf3))

- Discriminate dispatch-router /info fetch-failure reasons
  ([`fd9bd9e`](https://github.com/jason-weddington/agent-gtd/commit/fd9bd9efd4a4d47f4a5e6b3cf93fd8e6dcc4bb2f))

### Testing

- Cover all _classify_info_failure branches
  ([`1b3180a`](https://github.com/jason-weddington/agent-gtd/commit/1b3180af5cb5f735616c31323807c983e1ddadcc))


## v1.97.0 (2026-07-11)

### Bug Fixes

- Honor project_id/status and reject unknown keys in add-item --from-json
  ([`450ff34`](https://github.com/jason-weddington/agent-gtd/commit/450ff34eb379b3f2fba79334963119f69da1c235))

- LocalBackend returns parsed lists for ac/files/scope_out (match HttpBackend)
  ([`3c695ac`](https://github.com/jason-weddington/agent-gtd/commit/3c695ac3f4725c84b11f503f9d7d678d6db26634))

- Log-not-swallow the migration replay suppress (keep broad for SQLite safety)
  ([`742ad1c`](https://github.com/jason-weddington/agent-gtd/commit/742ad1c6e5999a8bb8d7bd5992b0b90e2b226067))

- Narrow broad except in _http_post_create_item error parsing
  ([`52a2c23`](https://github.com/jason-weddington/agent-gtd/commit/52a2c23c43c96e9eb0b2b207c3026f606fad885f))

### Features

- Add talos-* build engines to the roster (enum + MCP literal + producer contract test)
  ([`604a66b`](https://github.com/jason-weddington/agent-gtd/commit/604a66b753e02f5757f4c47f55dea00243a400c8))

- Explicit dispatch engine selection — Sonnet default, manage pinned to Opus, no silent base default
  ([`bd01ff8`](https://github.com/jason-weddington/agent-gtd/commit/bd01ff869679fde28a2b3b3b4bd3268bdfb04bdd))

- Register claude-code-glm build engine (glm-5.2 via Ollama Cloud)
  ([`372931c`](https://github.com/jason-weddington/agent-gtd/commit/372931cad7594028cc1aeda6544d4659c0c86d2e))

- Surface the executing dispatch host on run rows (Runs API + UI)
  ([`a1cfd7a`](https://github.com/jason-weddington/agent-gtd/commit/a1cfd7acc8504de42f99900ea316326180ead26f))

### Refactoring

- Import DispatchMode from the protocol package (dedup local copy)
  ([`ce319b1`](https://github.com/jason-weddington/agent-gtd/commit/ce319b18845d4ae53a9e37f4a0c6d41e6512395b))

### Testing

- AST-walk guard against broad exception-swallowing (suppress(Exception) / blind except)
  ([`284886b`](https://github.com/jason-weddington/agent-gtd/commit/284886be81f1f49cd067829de75b4af0cc149a3f))

- Derive project owner-guard test from _DISPATCH_ONLY_FIELDS
  ([`f4dde98`](https://github.com/jason-weddington/agent-gtd/commit/f4dde989d37c00c224a9ce74c3d1e5f56577af27))

- Guard the --from-json payload-command family against silent key drops
  ([`3fd270d`](https://github.com/jason-weddington/agent-gtd/commit/3fd270de1baf5e67bb9e5bd33f40b86fec6442bd))


## v1.96.0 (2026-07-09)

### Features

- Add first-class gate_command field to GTD projects
  ([`e988f18`](https://github.com/jason-weddington/agent-gtd/commit/e988f1822030b4eef596ddfd4d5e29f553682a25))


## v1.95.0 (2026-07-08)

### Chores

- Bump agent-gtd-dispatch-protocol to ad949476 (RunResponse.engine_actual)
  ([`2966934`](https://github.com/jason-weddington/agent-gtd/commit/296693478b1568b270e92a18e6bfe5d914dbf845))

### Features

- Forward per-run user JWT as dispatch callback token (Phase 2 of 2)
  ([`230a0ed`](https://github.com/jason-weddington/agent-gtd/commit/230a0ed6ad1b929177bb47d43d1fda17247c780b))

### Testing

- Add three LocalBackend list_items compaction test twins
  ([`c7118e0`](https://github.com/jason-weddington/agent-gtd/commit/c7118e0ad4509cd6811ad5150122925797a15f99))


## v1.94.0 (2026-07-07)

### Chores

- Ratchet coverage fail_under to 97.1 after CLI parity wave
  ([`d27c6bd`](https://github.com/jason-weddington/agent-gtd/commit/d27c6bde833bd61637a8862715413a290f1a85f5))

- **test**: Cap vitest worker pool to 4 (prevent dispatch-build OOM)
  ([`b5413ae`](https://github.com/jason-weddington/agent-gtd/commit/b5413ae166c3fa80ff7093f3592efd39e1828645))

### Documentation

- Note agent-gtd-dev is a workspace project spanning both repos
  ([`4f8ef76`](https://github.com/jason-weddington/agent-gtd/commit/4f8ef76c5cc789c1a916c0fbbb902a0e9cdb6b5c))

### Features

- **176502fa**: Persist engine_actual on claude_runs and surface via API
  ([`39a2d4c`](https://github.com/jason-weddington/agent-gtd/commit/39a2d4c40b6aaa0203fe75a5f99cfbc162fa563b))

- **3901ad2c**: CLI update-item --from-json forwards all 12 fields and errors on unknown keys
  ([`8af02b8`](https://github.com/jason-weddington/agent-gtd/commit/8af02b8cb285277eb327bdb2df190384dd9d37a9))

- **5a3f1cfd**: Surface project_repo_mode on item read paths
  ([`1da2975`](https://github.com/jason-weddington/agent-gtd/commit/1da2975e714c1b1cca3323e849686f4199607501))

- **5f9552d7**: Engine_actual truthful end-to-end (agent_gtd fallback drop + tests)
  ([`dda5a1b`](https://github.com/jason-weddington/agent-gtd/commit/dda5a1b9c8c2a42f1a5e8906928c7e4e23a071c7))

- **7831bf28**: MCP list_items compact-by-default with detail flag
  ([`9621468`](https://github.com/jason-weddington/agent-gtd/commit/9621468bab4762d655dc9051299be6a4a95d1117))

- **a067aa59**: Add first-class --wait flag to run-status / rollout-status
  ([`f8d2852`](https://github.com/jason-weddington/agent-gtd/commit/f8d2852342fda7fdbb8935f953ac40216e5f3ca7))

- **cli**: Dispatch + run commands (parity 5/8)
  ([`7c64f78`](https://github.com/jason-weddington/agent-gtd/commit/7c64f781231a721700b299ba89a05891acefa347))

- **cli**: Item lifecycle + blocker commands (parity 2/8)
  ([`b573d34`](https://github.com/jason-weddington/agent-gtd/commit/b573d347af8e18c01da178008e3a129437327496))

- **cli**: MCP-to-CLI parity test + docs (parity 8/8)
  ([`44f0102`](https://github.com/jason-weddington/agent-gtd/commit/44f010255cab1ebd283e1ca8330435606e3b2ee9))

- **cli**: Note + comment commands (parity 3/8)
  ([`a3490ec`](https://github.com/jason-weddington/agent-gtd/commit/a3490ecf1891c669a87107878a371d3c3edd6a78))

- **cli**: Per-resource subcommand registration convention + shared helpers
  ([`6e71aae`](https://github.com/jason-weddington/agent-gtd/commit/6e71aae881fa825f28fd62ec390057beb6bd335e))

- **cli**: Project + sharing commands (parity 4/8)
  ([`a5c909a`](https://github.com/jason-weddington/agent-gtd/commit/a5c909aaf493f8e541da04ccbcdf7ae01b14b416))

- **cli**: Rollout control commands (parity 7/8)
  ([`e5c83f3`](https://github.com/jason-weddington/agent-gtd/commit/e5c83f3d9f3b67292f5dc57db2f33ad8f59add64))

- **cli**: Rollout planning commands (parity 6/8)
  ([`748b4f5`](https://github.com/jason-weddington/agent-gtd/commit/748b4f52a11e6ba0bfc3b013566ff8c1cf3b9f7c))

- **e5475f54**: CLI parity follow-up: dispatch-item --rollout-id flag + local-mode enqueue note
  ([`b7cc759`](https://github.com/jason-weddington/agent-gtd/commit/b7cc75986929ef43607b1a1a9128e1ce16546276))

### Refactoring

- **01bca9e8**: CLI parity follow-up: rollout_control.py uses shared backend_session()
  ([`3cf832f`](https://github.com/jason-weddington/agent-gtd/commit/3cf832f579839ca39f6944b4d44c30fe882ca5a2))


## v1.93.0 (2026-06-15)

### Bug Fixes

- **db874804**: Schema FK forward-reference breaking fresh PostgreSQL bootstrap
  ([`b55b228`](https://github.com/jason-weddington/agent-gtd/commit/b55b2284bff2b13a94e4a88df74f5eaa1cc5befc))

### Documentation

- Document externally-authenticated Claude Code; correct dispatch-protocol source
  ([`3717170`](https://github.com/jason-weddington/agent-gtd/commit/3717170e26662a37f28a63870e3a5de6f76f981d))

- START-HERE gains the Bedrock planner option for corporate environments
  ([`93fbac8`](https://github.com/jason-weddington/agent-gtd/commit/93fbac8ca3c48bb97d1578ccbd17175aeb41c41d))

- START-HERE.md — single entry point for agent onboarding
  ([`4258b3d`](https://github.com/jason-weddington/agent-gtd/commit/4258b3d11dae539a6e83b7959bb46b1ba643b084))

- **33220e1e**: README lifecycle diagram uses real enum values
  ([`d5da717`](https://github.com/jason-weddington/agent-gtd/commit/d5da7174e1b885c9a55aab75a5f423315d0025aa))

- **6a0566ea**: AL2023/RHEL PostgreSQL first-run + pg_hba auth note
  ([`8f67840`](https://github.com/jason-weddington/agent-gtd/commit/8f67840bcd040995a1a4bbca999dad737a656734))

- **713b1ca7**: Deploy.md AL2023/RHEL distro gaps + 5432 port contention
  ([`ad3d022`](https://github.com/jason-weddington/agent-gtd/commit/ad3d022c7f8945f946a651fa63c22e5675438356))

- **e8fda58a**: MCP setup README — agent-gtd-mcp not on PyPI; co-located server note
  ([`1e07d10`](https://github.com/jason-weddington/agent-gtd/commit/1e07d10d25c3ba83c299ececaf12f7208d8b1141))

### Features

- **d81261c1**: Add a PostgreSQL schema-bootstrap test (close the SQLite-only test gap)
  ([`0a0b75c`](https://github.com/jason-weddington/agent-gtd/commit/0a0b75cbc3018e659cd44e3000a2343b419a0198))


## v1.92.1 (2026-06-12)

### Bug Fixes

- Coerce dispatch mode str to DispatchMode for the typed protocol
  ([`75bbf21`](https://github.com/jason-weddington/agent-gtd/commit/75bbf21792610411c0acb3cd7890b05b84a86db5))


## v1.92.0 (2026-06-12)

### Chores

- Add .kb_project + correct stale release docs
  ([`5c447ef`](https://github.com/jason-weddington/agent-gtd/commit/5c447ef7a28b09583bfb87dfa61c7ed1b9de0ac1))

- Pin agent-gtd-dispatch-protocol to public GitHub over https
  ([`eb86861`](https://github.com/jason-weddington/agent-gtd/commit/eb8686107f1207dd3932a279b0c7b395707e551b))

### Documentation

- Drop ubuntu-pi-01 from dispatch host list
  ([`c00a04c`](https://github.com/jason-weddington/agent-gtd/commit/c00a04c9a209ec12220d18f60dacbc09325a79a9))

- Setup-audit fixes — verified against current code (workflow wf_8865dd55)
  ([`51514e9`](https://github.com/jason-weddington/agent-gtd/commit/51514e96739639670a2398826c8fc8cf8a238c3c))

- **71643696**: Overhaul setup.md — working PG16 recipe, no false claims
  ([`1982479`](https://github.com/jason-weddington/agent-gtd/commit/1982479101db9cae55ff72080ad42b1d22ac9f50))

- **f9416e62**: Document protocol-dependency override for non-homelab machines
  ([`417754c`](https://github.com/jason-weddington/agent-gtd/commit/417754cddeb58c26203a538a3c519a24d7581912))

### Features

- **339b907d**: Workspace projects: [Monorepo|Workspace] toggle + repo list editor
  ([`7c2c6d2`](https://github.com/jason-weddington/agent-gtd/commit/7c2c6d21d02497d19ea1aa096b178b5c8d7eab22))

- **3e4b4991**: Workspace projects: GTD-side dispatch-path validation + contract
  ([`6eb9617`](https://github.com/jason-weddington/agent-gtd/commit/6eb9617fb013f0358826f7659b78f358fae8e4b0))

- **96a31c5d**: Enable rollouts for workspace projects
  ([`1eef6e4`](https://github.com/jason-weddington/agent-gtd/commit/1eef6e4a661d3a907afbc943aac3ff085f7b89c9))

- **9a4002b9**: Pre-seed workspace repo list from git origin on monorepo->workspace toggle
  ([`b1e24a9`](https://github.com/jason-weddington/agent-gtd/commit/b1e24a9b15e65cc2c181c5c2da8bd0b510772889))

- **c55ccdc3**: Workspace projects: backend schema, models, validation + REST/MCP exposure
  ([`6921083`](https://github.com/jason-weddington/agent-gtd/commit/69210836448d5e52e2839e8a5dd704d4860d50c6))

### Testing

- Guard ProjectDetail render-loop fix with pruneSelectedLabels helper
  ([`2e6f393`](https://github.com/jason-weddington/agent-gtd/commit/2e6f393f80cdc73cc2cfb3914100ee3ceadcfc8d))


## v1.91.0 (2026-06-08)

### Bug Fixes

- Stop ProjectDetail render loop that blocked navigation
  ([`16f0703`](https://github.com/jason-weddington/agent-gtd/commit/16f07033ca4a4def4b0c827171f212b8134296f7))

- **3de89070**: Fix 2 pre-existing failures in frontend settings.test.tsx
  ([`d8c2426`](https://github.com/jason-weddington/agent-gtd/commit/d8c242694d2f58590ad837e015d9801500709bda))

- **aec3ee1f**: Guard against stranded MUI inert/aria-hidden that kills sidebar nav
  ([`e71414d`](https://github.com/jason-weddington/agent-gtd/commit/e71414da332d10432889b445aa30f3a20bfdb27a))

### Chores

- Revert useInertGuard nav-recovery guard (e71414d)
  ([`9b06b75`](https://github.com/jason-weddington/agent-gtd/commit/9b06b75f9d85e0a3bde8ffabe4483bb53eef0777))

### Features

- **156043e5**: Add list_dispatch_hosts MCP tool
  ([`cda872b`](https://github.com/jason-weddington/agent-gtd/commit/cda872bfbdc5252a39a6dab70760c32870ad285f))

- **691da122**: CLI file/stdin structured item writes (update-item/add-item --from-json)
  ([`8aee19e`](https://github.com/jason-weddington/agent-gtd/commit/8aee19ef226446e19e29e8def1cedc462f4712b8))


## v1.90.1 (2026-06-01)

### Bug Fixes

- **36c1b775**: Disable body scroll-lock on right-side drawers to restore nav
  ([`80acc9d`](https://github.com/jason-weddington/agent-gtd/commit/80acc9dfb1465d0c0f1f1a4d026ea99cfbcbe6dc))


## v1.90.0 (2026-05-31)

### Bug Fixes

- **506b3f1f**: Parenthesize Sonnet and Haiku build-engine labels
  ([`470a766`](https://github.com/jason-weddington/agent-gtd/commit/470a7660629f71f17f34f3004d63f8bf2d734622))

- **c5616469**: Exclude rollout-locked items from kanban "Select for Rollout"
  ([`2a47070`](https://github.com/jason-weddington/agent-gtd/commit/2a470704c5125f6501af15e8dc803da2f1b39865))

### Chores

- **cfb68e2d**: Enable @typescript-eslint/no-use-before-define
  ([`c2e3c28`](https://github.com/jason-weddington/agent-gtd/commit/c2e3c28aad232aa134183e11318108d0f6707161))

### Features

- **0aecc298**: Expose server-derived inFlightBuildRuns on rollout reads
  ([`6399758`](https://github.com/jason-weddington/agent-gtd/commit/6399758772aad89e41531b5240540d426c86b461))


## v1.89.0 (2026-05-30)

### Bug Fixes

- **6b905566**: Attribution regression: shared-project dispatches by non-owners show "human"
  ([`0b887ee`](https://github.com/jason-weddington/agent-gtd/commit/0b887eec85862f59a00dd43f2d7f0a7f114312a6))

- **85741022**: Project list item count
  ([`9e7b13c`](https://github.com/jason-weddington/agent-gtd/commit/9e7b13c4fbbbfbf1d4ee5017eb1548c8464624d2))

- **comments**: Don't echo user.email in REST route fallback for created_by
  ([`dd27f2b`](https://github.com/jason-weddington/agent-gtd/commit/dd27f2b8284e01a9b8549e3e0224d550ce224974))

### Documentation

- Bootstrap docs/ scaffold from claude_workflow_example templates
  ([`038cf0a`](https://github.com/jason-weddington/agent-gtd/commit/038cf0a40e5672e1ccf620385ef6922d37544331))

- Clarify dispatch host env model and MCP provisioning
  ([`839d89b`](https://github.com/jason-weddington/agent-gtd/commit/839d89b05c3a06ceaa4852af643b191382c9cfaf))

- Record GTD project id and fix MCP config location in CLAUDE.md
  ([`e764ec0`](https://github.com/jason-weddington/agent-gtd/commit/e764ec01dfc8cc4af72172565f8b659efb0036ff))

### Features

- **087f519f**: Add "Assign to me" button to list and board views
  ([`3ccf71a`](https://github.com/jason-weddington/agent-gtd/commit/3ccf71a5c571210e643236f1741b3572adf7c566))

- **33ed64c7**: Build engine dropdown matches full BuildEngine enum
  ([`dfcb551`](https://github.com/jason-weddington/agent-gtd/commit/dfcb5511ddee0654a15d14043b10bddc99d902fe))

- **50f0e9f2**: Rollout Activity Drawer Width
  ([`24a252a`](https://github.com/jason-weddington/agent-gtd/commit/24a252ac5723c2a0904ef4b889cf4c839958dd9e))

- **64e76439**: Return full UUIDs in board_state tool responses
  ([`0a7210c`](https://github.com/jason-weddington/agent-gtd/commit/0a7210c1542a5da117242973e5576d540a3a3e5c))

- **6c333bbd**: Settings - manager and worker timeout field headings
  ([`5c429f6`](https://github.com/jason-weddington/agent-gtd/commit/5c429f6ee8164279cac36aa4c4769c23e5ab3ef9))

- **73c26224**: Starting rollouts from web UI
  ([`abc20be`](https://github.com/jason-weddington/agent-gtd/commit/abc20beaa52614b98c1cd1cc56f01f0c77308802))

- **9125f6c3**: Task drawer - project list drop down
  ([`9b59bbf`](https://github.com/jason-weddington/agent-gtd/commit/9b59bbfe065a014745db0ce53fd98b4ffb67b6f5))

- **aaab9503**: Relabel claude-code build engine as Opus
  ([`3f7eaa5`](https://github.com/jason-weddington/agent-gtd/commit/3f7eaa5a6e7ed4728cf71db211e5abd719aeeb1b))

- **assignments**: Wire task assignments into the UI
  ([`79e2512`](https://github.com/jason-weddington/agent-gtd/commit/79e2512e3f9f82ddbdf51e9fca4b3c6c41355288))

- **c9100e7e**: List View - Filtering by Tag
  ([`8314165`](https://github.com/jason-weddington/agent-gtd/commit/8314165e79d166cf7c1008e70d547704310bf661))

- **dc54e1ea**: Comment attribution - human
  ([`83ed070`](https://github.com/jason-weddington/agent-gtd/commit/83ed0701c1bd9ab6757f96d00f88dd80b5117d50))

- **eaef216e**: Dispatch in saved projects
  ([`6ca92d3`](https://github.com/jason-weddington/agent-gtd/commit/6ca92d374137a6ec2a9148906456d9eee65244d5))

- **faa926be**: Tag filter pills respect 'My tasks' filter
  ([`97befe9`](https://github.com/jason-weddington/agent-gtd/commit/97befe972ff5bde4a8d5a78795139015f1ae3130))

- **rollouts**: Add dismiss X button to RolloutStrip for halted rollouts
  ([`f5c2f26`](https://github.com/jason-weddington/agent-gtd/commit/f5c2f26f81c744cba0f8aaeab9387373d9e6db49))


## v1.88.0 (2026-05-21)

### Bug Fixes

- Restore claude-code-sonnet + claude-code-haiku to BuildEngine enum
  ([`9e77251`](https://github.com/jason-weddington/agent-gtd/commit/9e772518e0546c0ec515d9389bc45c9aa6f63f47))

- **18cb685b**: MCP update_item calls intermittently came back with empty parameters
  ([`6cce249`](https://github.com/jason-weddington/agent-gtd/commit/6cce249b29d738a86ff20280d08f623be28a62c6))

- **2914d998**: Agent-gtd companion to 865b0e4e — engine rename default + settings migration
  ([`aebb2ba`](https://github.com/jason-weddington/agent-gtd/commit/aebb2ba44071c000a6332c6971061e3dd5e32bb8))

- **852b15a0**: Resolve rollout state-machine deadlock blocking manager-mode
  ([`d0a1994`](https://github.com/jason-weddington/agent-gtd/commit/d0a19947c1dc1284f85e2e3e333b6e36984f29dc))

- **dispatch**: Skip placeholder status flip for manage-mode dispatches
  ([`eced99d`](https://github.com/jason-weddington/agent-gtd/commit/eced99d16a80a35e1d2c71d1522a0416b8009135))

- **dispatch_worker**: Stale 'claude' fallback default — should be 'claude-code'
  ([`24c2943`](https://github.com/jason-weddington/agent-gtd/commit/24c29439ba103a044fccc6b4dad388e826f42e1f))

- **f08b63a4**: Fold Out of Scope into Files to Modify accordion
  ([`f2a82ed`](https://github.com/jason-weddington/agent-gtd/commit/f2a82ed7c0eac7fae82a9d6b42f3b02fcea75c15))

- **lint**: Shorten conftest fixture docstring to fix E501
  ([`c113adb`](https://github.com/jason-weddington/agent-gtd/commit/c113adbdc00a5170c9e734c2ad9cc29f878d6629))

- **models**: Drop legacy 'claude' value from BuildEngine enum
  ([`725de93`](https://github.com/jason-weddington/agent-gtd/commit/725de93bb2af37a486868df2a5f8613e261b433f))

- **rollout**: Wire dispatch_rollout end-to-end for manage runs
  ([`46a1b51`](https://github.com/jason-weddington/agent-gtd/commit/46a1b510aaafb6f55f1d7801bac92b1f73bc823b))

- **router**: Drop /info TTL cache, poll fresh on every dispatch
  ([`d463afa`](https://github.com/jason-weddington/agent-gtd/commit/d463afad89f879e66a337074f79ad99c081652e3))

- **settings**: Coding Agent dropdown uses 'claude-code' engine value
  ([`e5dfc0d`](https://github.com/jason-weddington/agent-gtd/commit/e5dfc0de53ac7463fd39bbcaf0474b8b20c716cb))

- **test**: Mock probe_dispatch_host in test_capabilities_divergent_versions
  ([`13715ac`](https://github.com/jason-weddington/agent-gtd/commit/13715acd4f97fc65230a77c71dce07fea946ceb8))

- **wave**: Link build dispatches to wave plan and validate state preconditions
  ([`164f391`](https://github.com/jason-weddington/agent-gtd/commit/164f3912cbe8ada9c83c221a0b3b5fbc9b9abe86))

### Chores

- Lower coverage threshold to 95.0 after 64975539 merge
  ([`aabe348`](https://github.com/jason-weddington/agent-gtd/commit/aabe34814c2b6ff3638b83c8d5441cea9cc2885c))

- Lower coverage threshold to 95.5 after 1042a4e1 merge
  ([`9a77ee4`](https://github.com/jason-weddington/agent-gtd/commit/9a77ee4e8ff40ed35381a0c4687cbb73fa25679d))

- **ci**: Redirect coverage hook output to file to fix BlockingIOError
  ([`6e9f74d`](https://github.com/jason-weddington/agent-gtd/commit/6e9f74d8869d7f3c33d8bc47e27d4f1d24933fce))

- **cov**: Add _fetch_host_info and _gather_host_info exception-path tests
  ([`92078f3`](https://github.com/jason-weddington/agent-gtd/commit/92078f3ec43ea902bdd0dcc0088d1b65f2fdf4dd))

- **coverage**: Lower fail_under to 94.4 to match actual coverage
  ([`7d738ed`](https://github.com/jason-weddington/agent-gtd/commit/7d738edae6a33f48e9a6e0e469c0f798da6b114f))

- **coverage**: Ratchet fail_under 94.4 → 94.1 to match actual
  ([`00ee2ba`](https://github.com/jason-weddington/agent-gtd/commit/00ee2ba43ecb2ee82c95e55745693bb96b2d8c1a))

- **lint**: Fix E501 line-too-long in test files
  ([`1620477`](https://github.com/jason-weddington/agent-gtd/commit/1620477d74952c6042da0c75c296ce906e677062))

- **lint**: Shorten docstrings to satisfy E501 + drop extraneous f-string
  ([`9f08e12`](https://github.com/jason-weddington/agent-gtd/commit/9f08e125fdcb5c9aac3ade0ed2688714f6eb57bd))

### Documentation

- **72703793**: Agent-gtd-dispatch-protocol git dep pins to specific SHA in uv.lock — should always
  track latest main
  ([`9eace2c`](https://github.com/jason-weddington/agent-gtd/commit/9eace2c03983962b2d7faa5f1db958e56f647cfb))

- **claude.md**: Prominent Setup section reminding agents to install pre-commit hooks
  ([`6941db6`](https://github.com/jason-weddington/agent-gtd/commit/6941db62c9df7e3bf58add8c752c389d34c833a9))

### Features

- **01d82bcc**: SSE events in reconciliation paths + guard poll-loop on unknown status
  ([`ab78d91`](https://github.com/jason-weddington/agent-gtd/commit/ab78d911dcff55d8e03d74f3f9ff747e328f7a6c))

- **02532f93**: Rollout status bar 'Open details' CTA is a no-op (relic of activity-drawer refactor)
  ([`665061c`](https://github.com/jason-weddington/agent-gtd/commit/665061cdd587eb21945a38983147ca20603caa44))

- **06666ced**: Active-rollout strip below the project header
  ([`a67a6b4`](https://github.com/jason-weddington/agent-gtd/commit/a67a6b427622ad0c7f77995e608584571a61b77e))

- **1042a4e1**: Cross-service cancel propagation: forward cancel_run from gtd to dispatch
  ([`16cbae7`](https://github.com/jason-weddington/agent-gtd/commit/16cbae7a0fda58f0e0af96d9cf2e6f06aa960828))

- **170fcc39**: Supervise fire-and-forget asyncio.create_task calls
  ([`197992f`](https://github.com/jason-weddington/agent-gtd/commit/197992f885caac0b464169c0dd43ed50b3466030))

- **1a8be458**: Coverage for _check_dispatch_service preflight path
  ([`2098cf0`](https://github.com/jason-weddington/agent-gtd/commit/2098cf0c956e004bb72943c49d5e015352b76d16))

- **1ab2f12a**: Separate manager + worker dispatch timeouts (manager defaults to 4h)
  ([`0310877`](https://github.com/jason-weddington/agent-gtd/commit/03108775661f9c5ee0f30ddb6c0b80148c1cc2eb))

- **1f651995**: Active runs number chip is not distinct in light mode
  ([`00e5647`](https://github.com/jason-weddington/agent-gtd/commit/00e564731a2faba5377ff2e486cab18c0452cad8))

- **204392e5**: Replace remaining get_dispatch_config callers with multi-host router
  ([`43293a7`](https://github.com/jason-weddington/agent-gtd/commit/43293a7a691052f684455292fd143e0e450bdf1c))

- **230a6204**: Surface build_engine value in the UI (currently invisible)
  ([`7294645`](https://github.com/jason-weddington/agent-gtd/commit/7294645cbe5d46700d61f8170f198a14ee6e256e))

- **26df3f26**: Task drawer - add an accordion to Acceptance Criteria and Files to Modify sections
  ([`e399633`](https://github.com/jason-weddington/agent-gtd/commit/e399633e10a53a517b191f48fc5043f0da533cc8))

- **2eb001fd**: Dispatch service doesn't enforce max_concurrent_runs at /dispatch (queues over cap)
  ([`b3b1668`](https://github.com/jason-weddington/agent-gtd/commit/b3b1668d594c4232e6b3bf0651ffaa99ca85abb3))

- **34c0231a**: Structured fields for item legality (replace prose-shape matching)
  ([`afa376b`](https://github.com/jason-weddington/agent-gtd/commit/afa376b0fba7add7b81835266158ef91acbab7ba))

- **38c19ee1**: Expand ALLOWED_BUILD_ENGINES to include claude-code-sonnet and claude-code-haiku
  ([`aec3f15`](https://github.com/jason-weddington/agent-gtd/commit/aec3f15b73c7d4e429c7bcfec46e8854a2adbe84))

- **3ff164f2**: Activity drawer (right-side, collapsible) + remove EVENTS/ACTIVITY tabs
  ([`b09410a`](https://github.com/jason-weddington/agent-gtd/commit/b09410a2620156adec6b7083ed7b93cfc7c7adc8))

- **418a7576**: SMOKE-7: Fix broken "Abort wave" UI button
  ([`1029d63`](https://github.com/jason-weddington/agent-gtd/commit/1029d6377b32480341f117ed4c59b1b93fa33747))

- **459fb7c0**: Add dispatch_host_id targeting to dispatch_item (MCP + REST + UI)
  ([`218fd85`](https://github.com/jason-weddington/agent-gtd/commit/218fd85bbbd196d0f2cee182dc7f08d36a4f8efa))

- **462e98b0**: MCP update_item supports project_id (move between projects)
  ([`3dde286`](https://github.com/jason-weddington/agent-gtd/commit/3dde286923a98dd5046401df5eafdc967b6cce5d))

- **46ad731a**: Tighten enum validation: Pydantic Literal types + consistent allowlists across
  layers
  ([`f3777a0`](https://github.com/jason-weddington/agent-gtd/commit/f3777a08baa58f861bb1add01aecd086e5ad3f8b))

- **4acac9d3**: Stale halted rollouts keep showing warning banner after all items shipped
  ([`7772ca6`](https://github.com/jason-weddington/agent-gtd/commit/7772ca63116a3c361823771800d7a1ce2450c60a))

- **4ec333a3**: Activity drawer 'Item' column always renders as null/em-dash even when event has
  currentItemId
  ([`e68e42e`](https://github.com/jason-weddington/agent-gtd/commit/e68e42e5cc2fd2c742caa0f241d2c36039494dab))

- **4ef39441**: Cross-repo contract test in CI: verify gtd dispatch payload validates against
  dispatch schema
  ([`408ad6b`](https://github.com/jason-weddington/agent-gtd/commit/408ad6bd5cad6336125da0c1397b5c66d5896edf))

- **57453ef1**: Multi-host dispatch capacity router (agent_gtd side)
  ([`09970c5`](https://github.com/jason-weddington/agent-gtd/commit/09970c59cee0a2cb9ae9dd25f843d2596394e4c7))

- **64975539**: Consume the shared dispatch protocol package in agent_gtd
  ([`10555c0`](https://github.com/jason-weddington/agent-gtd/commit/10555c05fcfe5e59bb334199a4fc798a9e93fc90))

- **6b511788**: Settings: dispatch service version hides cluster divergence (first-responder wins)
  ([`36d96f2`](https://github.com/jason-weddington/agent-gtd/commit/36d96f2ce40097b801ffdeaebe7bcb1180de3774))

- **733b4a6d**: Active runs indicator: mode-accurate badges, semantic titles, parent/child grouping
  ([`3e7f5dd`](https://github.com/jason-weddington/agent-gtd/commit/3e7f5ddbc23397663467dd1e06237dbdd97361aa))

- **73892a38**: Settings pane: surface separate worker + manager timeout fields
  ([`cad39b8`](https://github.com/jason-weddington/agent-gtd/commit/cad39b89f0cd52c899f8c3b2f22d034601acf0d4))

- **9a3fe51b**: Plan-mode dispatch agent comments attributed to "human" instead of
  claude-plan-<run_id>
  ([`3a57db1`](https://github.com/jason-weddington/agent-gtd/commit/3a57db1bb09afd8c6aac1164707eeb8fdfaf859f))

- **9a96f3ec**: Add build_engine field on items (per-task engine selection)
  ([`e5b8cd2`](https://github.com/jason-weddington/agent-gtd/commit/e5b8cd2b577de3c2b7e3fd20793b410193de9160))

- **a5352c4f**: SMOKE-4: Add description_preview field to ProjectResponse
  ([`534d7d8`](https://github.com/jason-weddington/agent-gtd/commit/534d7d8b452796b1179366d980611dea2fc5f144))

- **ace8fa14**: Coverage for rollout_routes uncovered paths
  ([`9b4ddfb`](https://github.com/jason-weddington/agent-gtd/commit/9b4ddfb275b71d20220c358c6579e87137a4ae15))

- **b0fac213**: Task drawer - increase width
  ([`36b3c4c`](https://github.com/jason-weddington/agent-gtd/commit/36b3c4c4067fe78fa812ebe26b3e5ce01de20b3d))

- **c3d0d4cc**: Rollout lifecycle events emitted + activity feed scopes to rollout
  ([`093a52d`](https://github.com/jason-weddington/agent-gtd/commit/093a52d9e466a694da19736fba70a30b53a4ca09))

- **d5f81cc4**: MCP read tools for rollouts so the lead agent can see live rollout state
  ([`99b74c0`](https://github.com/jason-weddington/agent-gtd/commit/99b74c0571853230cd437e92e85265602f24c3b2))

- **d97a5a4e**: Best-effort event-publish wrapper that surfaces failure rate
  ([`36e1bcf`](https://github.com/jason-weddington/agent-gtd/commit/36e1bcf7f3320f8a17b880062c29544fcc43ad0d))

- **dce77e22**: Invalidate capabilities cache on host CRUD (60s stale window)
  ([`330519e`](https://github.com/jason-weddington/agent-gtd/commit/330519e839601d9fb13b5ef82deb42582ffe43d9))

- **de04555b**: Boot migration: rewrite legacy app_settings engine value to new enum
  ([`0d11d53`](https://github.com/jason-weddington/agent-gtd/commit/0d11d53bc3cfe33935aa9cef0539fcac78d96b0f))

- **de0faf2a**: Activity drawer needs an X close button (only closable by clicking outside,
  impossible on mobile)
  ([`94c14a7`](https://github.com/jason-weddington/agent-gtd/commit/94c14a7edc5de3481bef0428cc10ec159eb8e3f6))

- **e41a425a**: Coverage: test SSE event stream paths
  ([`d856493`](https://github.com/jason-weddington/agent-gtd/commit/d856493712a21b52d86afd6ab2e6a8092ddba289))

- **efca5b81**: Agent-gtd rollout-status CLI + event-driven rollout completion pattern
  ([`33bd5c9`](https://github.com/jason-weddington/agent-gtd/commit/33bd5c9b7d1e9dfe0d1a6a18040d41ed29fdb2a5))

- **f33df59b**: Remove dead prose-shape parsers and realign docstrings to structured-fields legality
  ([`17b839c`](https://github.com/jason-weddington/agent-gtd/commit/17b839c4ecc18ee108b40c55d6f509c87454fcfa))

- **f361e692**: Add Host form: validate URL + probe /info before save
  ([`36c1ccc`](https://github.com/jason-weddington/agent-gtd/commit/36c1ccc16d5a3f5a02e3aa0a3df994a1d2a7179f))

- **f8f073a3**: Runs/rollouts-level failure feed surface
  ([`9b63c5f`](https://github.com/jason-weddington/agent-gtd/commit/9b63c5fbc29448d2f3db3ae177819f80ccdbce95))

- **observability**: Distinct created_by per agent role (claude-build/manage/lead/plan)
  ([`cc55e2a`](https://github.com/jason-weddington/agent-gtd/commit/cc55e2a31b859abe7f59e4bfbbd4636587be325c))

- **observability**: Manager state heartbeat (semantic state, not liveness)
  ([`249f3a9`](https://github.com/jason-weddington/agent-gtd/commit/249f3a9729982fd326df958d984f8fea22db7644))

- **observability**: Per-wave Activity tab — unified historical event log
  ([`c06a6dd`](https://github.com/jason-weddington/agent-gtd/commit/c06a6dd89e3c7bb880fbcf9c94a69241bb7e89c0))

- **project-detail**: Show truncated project ID before copy icon
  ([`1d778d8`](https://github.com/jason-weddington/agent-gtd/commit/1d778d818f16c946a988c29c5c038494bb9ccf58))

- **projects**: Populate description_preview in project_service list/get (SMOKE-5)
  ([`18963b2`](https://github.com/jason-weddington/agent-gtd/commit/18963b2b0178530850f877c8539309f006cc1425))

- **rollout**: Auto-recovery infrastructure — new endpoints + halt_rollout accepts pending
  ([`d51af1b`](https://github.com/jason-weddington/agent-gtd/commit/d51af1b427e505d612addb21791ee919306554c6))

- **ui**: Render description preview under project names on Projects list (SMOKE-6)
  ([`a02aa75`](https://github.com/jason-weddington/agent-gtd/commit/a02aa75ee2b936ddaf1bc16682832536c69737bf))

- **wave**: Add start_wave service + MCP tool to flip pending → running
  ([`30a51cd`](https://github.com/jason-weddington/agent-gtd/commit/30a51cd931f9f0b102b3e65f0adffdcaae3c345d))

- **wave**: Complete_in_wave cascades item status + signals graph_complete in response
  ([`61eea90`](https://github.com/jason-weddington/agent-gtd/commit/61eea906012e8ec180b3e1da2ece6ab79176c9ff))

- **wave**: Wire cancel_wave into McpBackend protocol + MCP tool
  ([`851ea3d`](https://github.com/jason-weddington/agent-gtd/commit/851ea3d5fdc327ac7a21045897c5f7db1ef39cda))

### Refactoring

- **rollout**: Rename wave_run → rollout across the stack + drop placeholder requirement
  ([`141e80b`](https://github.com/jason-weddington/agent-gtd/commit/141e80bcc3bf02feb903fa1f183047c4a9133131))

- **wave-manager**: Fully rip out the reaper + ping_wave (net -1159 lines)
  ([`f54d323`](https://github.com/jason-weddington/agent-gtd/commit/f54d3237a2e52d599b16937e6715bb169126a7a2))

### Testing

- Add HTTP route coverage for list_rollouts, get_rollout_plan, get_rollout endpoints
  ([`c862a54`](https://github.com/jason-weddington/agent-gtd/commit/c862a54c520b33a876def38ccce39cd979b699f9))

- Cover event-publish exception suppression in note + comment services
  ([`28fa6cb`](https://github.com/jason-weddington/agent-gtd/commit/28fa6cba5e00a6411f05fda2180d86321d6d3e0a))


## v1.87.0 (2026-05-12)

### Features

- **projects**: Add total_items count to project responses (SMOKE-1 + SMOKE-2)
  ([`f128288`](https://github.com/jason-weddington/agent-gtd/commit/f1282880eba794fd9c528583d0ce6e934d6119d3))

- **ui**: Show item count next to project names (SMOKE-3)
  ([`03e9755`](https://github.com/jason-weddington/agent-gtd/commit/03e9755a7f8d8ad21d8eb4b77b9e8325e5d6bbf8))

- **wave-manager**: Add advance/complete/halt/replan + wave_routes
  ([`257c1e7`](https://github.com/jason-weddington/agent-gtd/commit/257c1e79799bc06f1ca7761577f05f5f255f7038))

- **wave-manager**: Add plan_wave MCP tool with legality contract
  ([`6fce9fc`](https://github.com/jason-weddington/agent-gtd/commit/6fce9fce9fae130c1bb36f7446d708668bcb4426))

- **wave-manager**: Add reaper background job + ping_wave heartbeat
  ([`089eb0b`](https://github.com/jason-weddington/agent-gtd/commit/089eb0bce21516b0e2f89e703d95f8359df746be))

- **wave-manager**: Add schema for autonomous wave runs
  ([`a672954`](https://github.com/jason-weddington/agent-gtd/commit/a6729542703db7fff52ca7cd32e427e02fc7e8b7))

- **wave-manager**: Dispatch_item supports wave_run_id + mode=manage launch
  ([`2eb8ea9`](https://github.com/jason-weddington/agent-gtd/commit/2eb8ea9b70098ebd33f10bc9d7d1340206618dc2))

- **wave-manager**: Expose plan_wave via REST so HttpBackend works
  ([`8c63c5c`](https://github.com/jason-weddington/agent-gtd/commit/8c63c5c9595c4da2915495693999318d1e770fde))

- **wave-manager**: Frontend banner + apt-style event feed + halt card
  ([`ae30905`](https://github.com/jason-weddington/agent-gtd/commit/ae30905baca8ba7247e92727619f36c1321688fb))

- **wave-manager**: SSE wave_events fan-out to project members
  ([`280a18a`](https://github.com/jason-weddington/agent-gtd/commit/280a18ade76c5d63788b8a56b3189ba955ba72ca))

- **wave-manager**: Wave-scoped item lock + dispatch endpoint guard
  ([`473e45b`](https://github.com/jason-weddington/agent-gtd/commit/473e45becfe7f42779056d0afc17e32e9a3ac3a3))


## v1.86.0 (2026-05-09)

### Features

- **ui**: Cmd+Shift+Enter fires Save and Plan; surface in shortcut overlay
  ([`266bf4c`](https://github.com/jason-weddington/agent-gtd/commit/266bf4ca2ffff9e854b9cf90cd7b63295e9c9467))


## v1.85.0 (2026-05-09)

### Features

- **runs**: Active runs indicator and SSE deliver shared-project runs
  ([`ea52f03`](https://github.com/jason-weddington/agent-gtd/commit/ea52f039d9be7730e301dbac6383d9c86b315626))

- **runs**: Show all dispatch activity in shared project Activity tabs
  ([`70a49b3`](https://github.com/jason-weddington/agent-gtd/commit/70a49b3b90f0e416557acbc30118101ea2208f9e))

- **ui**: Add Save and Plan button to new-item dialog
  ([`39d5c6e`](https://github.com/jason-weddington/agent-gtd/commit/39d5c6e0e7db7c7773ce34396ab3e6bcf0c8e3f4))


## v1.84.1 (2026-05-08)

### Bug Fixes

- **ui**: Show dispatch service version, not misleading engine label
  ([`54ae6a2`](https://github.com/jason-weddington/agent-gtd/commit/54ae6a2e6cbc2383c70c2869e3b0b3adf44a7714))

### Documentation

- Add project board screenshot to README
  ([`70a941b`](https://github.com/jason-weddington/agent-gtd/commit/70a941ba811d0367694b9e11079412812d482e37))


## v1.84.0 (2026-05-06)

### Features

- **mcp**: Expose project dispatch config in add_project / update_project
  ([`0ec3cd9`](https://github.com/jason-weddington/agent-gtd/commit/0ec3cd94000a79b38a29eebaf5d07e8f3bbc140e))

- **ui**: Copy-project-ID icon next to project description
  ([`4331b0c`](https://github.com/jason-weddington/agent-gtd/commit/4331b0c5da0ef493c27dbca7df5389340f9a2e90))


## v1.83.0 (2026-05-04)

### Features

- **dispatch**: Dispatch config follows project owner on shared projects
  ([`fa87983`](https://github.com/jason-weddington/agent-gtd/commit/fa8798367e9c65f7f589aa6594ddab84325810f6))


## v1.82.0 (2026-05-04)

### Documentation

- **deploy**: Generalize runbook to be environment-agnostic
  ([`65c2605`](https://github.com/jason-weddington/agent-gtd/commit/65c2605619b5fa980b3d345e9ef27fc2af9a12f6))

- **readme**: Document agent-gtd CLI install + shared env vars
  ([`6758673`](https://github.com/jason-weddington/agent-gtd/commit/6758673a6b6c8ab20526f69693bdf18aba302a3b))

### Features

- Enforce blockers on active transition and dispatch
  ([`97aca6d`](https://github.com/jason-weddington/agent-gtd/commit/97aca6df48dec0e49d91558f97058d9a23f952ad))

- Replace agent override TextFields with Autocomplete dropdowns in New Project modal
  ([`dccaf89`](https://github.com/jason-weddington/agent-gtd/commit/dccaf8968dae5415503a040d37fd238050789152))

- **projects**: Hide completed projects by default with Show completed toggle
  ([`57638ed`](https://github.com/jason-weddington/agent-gtd/commit/57638ed37ed648323d837598b1193256744d475f))

### Refactoring

- **frontend**: Extract ProjectEditDialog as shared component
  ([`67c0f39`](https://github.com/jason-weddington/agent-gtd/commit/67c0f39f522a314b6b27f3a7a853d0c26e166a9b))


## v1.81.0 (2026-05-02)

### Bug Fixes

- Enable vite build by handling react-transition-group via Rollup CJS plugin
  ([`fe1177b`](https://github.com/jason-weddington/agent-gtd/commit/fe1177bd4966dbdd186ea99ca50d61ff55696060))

### Documentation

- **deploy**: Note /home/jason chmod o+x for nginx traversal
  ([`5cc4cb1`](https://github.com/jason-weddington/agent-gtd/commit/5cc4cb1ae9d510320c61c34070a44128608754ec))

### Features

- Serve frontend from prod build, add serve.sh + deploy runbook
  ([`6b006c2`](https://github.com/jason-weddington/agent-gtd/commit/6b006c267f9395bce0dc3420b4ecd2f838c47938))


## v1.80.0 (2026-05-02)

### Bug Fixes

- **frontend**: /login refresh loop from globally-mounted ItemDetailDrawer
  ([`234b57c`](https://github.com/jason-weddington/agent-gtd/commit/234b57cc52fa0583af8743680e33b9adac3b5976))

### Features

- Render markdown in project comments tab
  ([`812766a`](https://github.com/jason-weddington/agent-gtd/commit/812766a06fe0301a37179abb805d059bb8bf6061))

- Render markdown in task drawer and item dialog
  ([`06d4b56`](https://github.com/jason-weddington/agent-gtd/commit/06d4b5600986992c48b877ffd2db9f6f08eed832))

- **active-runs**: Open item drawer in place from runs dropdown
  ([`9d593fc`](https://github.com/jason-weddington/agent-gtd/commit/9d593fc357aa5a57c2dce1472a5665f88a3dcb07))


## v1.79.0 (2026-05-01)

### Bug Fixes

- Release.sh — use --follow-tags to avoid stale-tag push failures
  ([`644de75`](https://github.com/jason-weddington/agent-gtd/commit/644de75f12c158cbf7c8b7c712e8a209a6c12397))

- **frontend**: Kanban drag-and-drop — refresh before clearing optimistic
  ([`0fa9b2e`](https://github.com/jason-weddington/agent-gtd/commit/0fa9b2e30d79e695ef031226032efa74686366b0))

- **ui**: Make project detail tabs horizontally scrollable on mobile
  ([`3119532`](https://github.com/jason-weddington/agent-gtd/commit/31195325f9f0b9892547e594a0b1597d972ec249))

### Chores

- Apply ruff-format to admin/auth files
  ([`819f792`](https://github.com/jason-weddington/agent-gtd/commit/819f7920b926136fdaf3d012c56817b48007cdbb))

### Features

- Configurable dispatch timeout (global default + per-project override)
  ([`a154ec9`](https://github.com/jason-weddington/agent-gtd/commit/a154ec91b00d83ff88b62a0eab4e1040850bd66a))

- Mode-specific plan and build dispatch agents
  ([`ed78092`](https://github.com/jason-weddington/agent-gtd/commit/ed7809251fc26bd67405bd9f5061657572906592))

- Replace default agent with plan/build dropdowns, drop legacy field
  ([`d288aa5`](https://github.com/jason-weddington/agent-gtd/commit/d288aa5441a69dfd3b9cb5140b48082e67d3fc5f))

- **frontend**: Persist New Item dialog draft to localStorage
  ([`55e29bb`](https://github.com/jason-weddington/agent-gtd/commit/55e29bbc15d22e81eac62a17eb9e01d1e09a9d70))

- **ui**: Optimistic item creation in ProjectDetail
  ([`7387c64`](https://github.com/jason-weddington/agent-gtd/commit/7387c646e28ce9f6d15b06f6b9889e38345e60ea))

- **ui**: Show Plan/Build mode chip on dispatch run rows
  ([`5ce45eb`](https://github.com/jason-weddington/agent-gtd/commit/5ce45eb393dd04c8c1e10008dceca7c558722c31))

### Testing

- Cover plan/build agent settings + dispatch engine validation paths
  ([`b6a07e9`](https://github.com/jason-weddington/agent-gtd/commit/b6a07e9b419b0725656e56484e468f69f5a22ec5))


## v1.78.0 (2026-04-29)

### Bug Fixes

- **admin**: Use AGENT_GTD_PUBLIC_URL for invite + reset link base
  ([`77c7a7d`](https://github.com/jason-weddington/agent-gtd/commit/77c7a7d8d05865b3ad032f285172bc1ed621d280))

### Documentation

- Add advanced autonomous operations section to README
  ([`6072332`](https://github.com/jason-weddington/agent-gtd/commit/607233245151ee7609011afd9801bdf11b6fc14d))

### Features

- **admin**: User management page with list, promote, delete, and reset
  ([`5104ad8`](https://github.com/jason-weddington/agent-gtd/commit/5104ad8686a78830a28ef0cb2525325a0f53410a))

- **auth**: Admin-issued one-time password reset link
  ([`387bce5`](https://github.com/jason-weddington/agent-gtd/commit/387bce54e187407c796ec7f9f825df91e861252b))

- **auth**: Admin-only invite system with gated registration
  ([`a475e22`](https://github.com/jason-weddington/agent-gtd/commit/a475e2206a9d05bf2517499572207daa9437106e))

- **auth**: Self-serve password change in Settings
  ([`05cc7bb`](https://github.com/jason-weddington/agent-gtd/commit/05cc7bbb60f03b825cab2aec1c9549690f18df05))

- **cli**: Add agent-gtd promote-admin <email> subcommand
  ([`ef3356c`](https://github.com/jason-weddington/agent-gtd/commit/ef3356ca37f037c26a062cdb7d5e2385ee5231c0))

- **frontend**: Admin-only invite UI (Register page, AdminRoute, AdminInvites)
  ([`a4802c2`](https://github.com/jason-weddington/agent-gtd/commit/a4802c29109fdbd2ec91206f19de845c4daac723))


## v1.77.0 (2026-04-27)

### Features

- **frontend**: Replace priority pill with colored left border in list views
  ([`3d7645e`](https://github.com/jason-weddington/agent-gtd/commit/3d7645e12e41ea119994991deb015355ed468ac3))


## v1.76.1 (2026-04-26)

### Bug Fixes

- **frontend**: De-dupe label pills and stack project item rows on mobile
  ([`907e298`](https://github.com/jason-weddington/agent-gtd/commit/907e2983606d7afc86a498ea6c4ba626a6b3ddb2))

### Chores

- Untrack machine-specific deploy configs
  ([`1bd9fc7`](https://github.com/jason-weddington/agent-gtd/commit/1bd9fc77720f767072fc05e7d8c6583f886ab3bd))


## v1.76.0 (2026-04-26)

### Features

- **frontend**: Shrink description height and collapse attachments accordion
  ([`0133921`](https://github.com/jason-weddington/agent-gtd/commit/01339216f5c7fc22506134a4a69b9a8ab830c981))


## v1.74.0 (2026-04-25)

### Bug Fixes

- **frontend**: Declare @adobe/css-tools as an explicit devDependency
  ([`80416c5`](https://github.com/jason-weddington/agent-gtd/commit/80416c5d8d8fe8328e57d3a3379fcce887ebbb08))

### Chores

- Lower coverage floor back to 94.0
  ([`e28c5ed`](https://github.com/jason-weddington/agent-gtd/commit/e28c5ed5e04a433b244927d9cfdd1145cdf27ed8))

- Ratchet coverage floor to 94.2
  ([`7b96d16`](https://github.com/jason-weddington/agent-gtd/commit/7b96d167e0380c17b84a9aecde545ab1f652cd1f))

### Features

- **cli**: Add agent-gtd run-status command for shell-based monitoring
  ([`362e877`](https://github.com/jason-weddington/agent-gtd/commit/362e877ab9d701d551fea1c80c60a7d35709b599))

- **frontend**: Add Remote Dispatch shortcuts to the keyboard shortcuts modal
  ([`d89ac5d`](https://github.com/jason-weddington/agent-gtd/commit/d89ac5de73c3253e28c3bad7d65bb3764ef4c165))

- **frontend**: Mobile-friendly layout improvements
  ([`cd982c5`](https://github.com/jason-weddington/agent-gtd/commit/cd982c59cc33f72462fc1e333e2e86b24ffd1b32))

- **frontend**: Open item detail drawer from Weekly Review Next Actions step
  ([`4231f72`](https://github.com/jason-weddington/agent-gtd/commit/4231f72cb93a972bb1d108345d9655f0765b76bb))

### Refactoring

- Remove claim_item/release_item MCP tools, add delete_note + update_project
  ([`fecabdf`](https://github.com/jason-weddington/agent-gtd/commit/fecabdfa16d3916b91254570d243aa10dd19ae0e))


## v1.73.0 (2026-04-23)


## v1.72.0 (2026-04-22)

### Features

- Add CORS origins for HTTPS/hostname access and ignore .kiro
  ([`afed4e4`](https://github.com/jason-weddington/agent-gtd/commit/afed4e4b4bfb04651298603304a6a90ec1b75811))


## v1.71.0 (2026-04-22)

### Chores

- Set coverage precision=1 so fractional fail_under works
  ([`de8b289`](https://github.com/jason-weddington/agent-gtd/commit/de8b2894f5c1da12d9eefb12250df9ca0da9774b))

### Code Style

- Apply ruff-format to dispatch_worker resolution helpers
  ([`dfca487`](https://github.com/jason-weddington/agent-gtd/commit/dfca487d79d2b394220c1b3bbf7b177230ba9a42))

### Features

- Add /api/dispatch/capabilities proxy for engine + agents list
  ([`b2becfd`](https://github.com/jason-weddington/agent-gtd/commit/b2becfde34cf38885f5d25983b34a4efe12d4422))

- Add project-scoped dispatch agent/max_turns resolution with global fallback
  ([`f6bce35`](https://github.com/jason-weddington/agent-gtd/commit/f6bce35d7d5f6009ef1731629229676798011c77))

- Add project-scoped dispatch_agent and dispatch_max_turns overrides
  ([`2e7f2e5`](https://github.com/jason-weddington/agent-gtd/commit/2e7f2e573f6326f87c99d157ea126007e3590048))

- **frontend**: Add Dispatch tab to project detail page
  ([`82a8c93`](https://github.com/jason-weddington/agent-gtd/commit/82a8c9347b8f666e77a0f0c6f0b67b149fb1eb8d))

- **frontend**: Show API key + MCP config in modal after creation
  ([`2eb0109`](https://github.com/jason-weddington/agent-gtd/commit/2eb0109b8ad9ea478a7bbb51db48e06ffc1950be))

- **frontend**: Upgrade agent_name field to Autocomplete dropdown + show engine identity
  ([`bdcd5bf`](https://github.com/jason-weddington/agent-gtd/commit/bdcd5bf387602dec47528638e4bb4f23b91fad7e))


## v1.70.0 (2026-04-20)

### Bug Fixes

- **settings**: Always show masked API key preview in dispatch field
  ([`37b2a14`](https://github.com/jason-weddington/agent-gtd/commit/37b2a14ab1615256629e21acfcaea4e5fbcda191))

### Features

- **settings**: Persist dispatch default_max_turns server-side
  ([`f03f321`](https://github.com/jason-weddington/agent-gtd/commit/f03f3214aa4433945936c023f80a19f8f1e3c491))


## v1.69.0 (2026-04-18)

### Chores

- Relax coverage floor 93.3 -> 93 to absorb rounding fluctuation
  ([`aee3500`](https://github.com/jason-weddington/agent-gtd/commit/aee35002d61d31057b8f735e7aa51c665bc1dfba))

### Features

- Engine + agent_name surfaced in dispatch settings
  ([`edaf790`](https://github.com/jason-weddington/agent-gtd/commit/edaf7909d0513c80d7f3494f90c483ce72efbc5c))

- Per-user dispatch config + owner-only dispatch guard
  ([`1ef51ed`](https://github.com/jason-weddington/agent-gtd/commit/1ef51ed89a1a93687e00a4ef24d24f5f878d4f39))

- **api**: Scope queries to accessible (owned + shared) projects
  ([`cb581fd`](https://github.com/jason-weddington/agent-gtd/commit/cb581fdc4f39e7ba12e9ee89e091997d9ec2a4b2))

- **api**: Search scoping + blocker sandboxing for shared projects
  ([`0623c53`](https://github.com/jason-weddington/agent-gtd/commit/0623c53a407fcbcdd5216832d31fd3c73ec05068))

- **api**: Settings returns service_api_key_preview instead of configured bool
  ([`0d9c1b3`](https://github.com/jason-weddington/agent-gtd/commit/0d9c1b3b332cf4c926a9c8ba64672366ead34f35))

- **api**: Share management endpoints + MCP tools
  ([`8b41176`](https://github.com/jason-weddington/agent-gtd/commit/8b4117640346e9957424de59ae98de0f10ec9f8a))

- **db**: Add project_members table + indexes
  ([`232094a`](https://github.com/jason-weddington/agent-gtd/commit/232094a78185a744e328fe5301f735bb812d884c))

- **frontend**: Masked API key preview — write-only field behavior
  ([`982f3a2`](https://github.com/jason-weddington/agent-gtd/commit/982f3a25d0b802b3d9da3a80cdb39d60d527fcb6))

- **frontend**: Shared-project UI — share tab, handshake, shared-with-you, attribution
  ([`17b5740`](https://github.com/jason-weddington/agent-gtd/commit/17b5740ca9f414b91db783d111de2cecf7d44f8c))

- **mcp**: Board_state snapshot on project-scoped tool responses
  ([`16113b7`](https://github.com/jason-weddington/agent-gtd/commit/16113b758cc1e9f33304d260d9edf2c519652a4a))


## v1.68.0 (2026-04-17)

### Bug Fixes

- **frontend**: Align review inbox triage statuses with kanban
  ([`1edb400`](https://github.com/jason-weddington/agent-gtd/commit/1edb400529dda60beba99b4367f6c7f3b502b6b3))

- **frontend**: Narrow header brand click target to title text only
  ([`234e2c1`](https://github.com/jason-weddington/agent-gtd/commit/234e2c1ed7e28e9a526487f1d0cecc4fb8bbd0ca))

- **frontend**: Prevent MUI right-slide after dispatch slide-up
  ([`84dc012`](https://github.com/jason-weddington/agent-gtd/commit/84dc012c4110855b0df5f64054d05d1768667cc3))

- **frontend**: Sort project list alphabetically case-insensitive
  ([`91d05a5`](https://github.com/jason-weddington/agent-gtd/commit/91d05a508ac03a042a31026f6ca2bc5e44b78729))

- **frontend**: Tick elapsed time live in ActiveRunsIndicator
  ([`6a2ea1f`](https://github.com/jason-weddington/agent-gtd/commit/6a2ea1fa81fe39829a8333aca4e9804c6d4e5512))

### Chores

- Decouple release from deploy
  ([`42ce061`](https://github.com/jason-weddington/agent-gtd/commit/42ce06190a9f9179c262dfffeea0414274fecb4e))

- Gitignore .claude workspace state
  ([`b3ecb00`](https://github.com/jason-weddington/agent-gtd/commit/b3ecb005c86c6a823e88b014166a52bb4873bdb8))

- Relax coverage floor 93.4 -> 93 to absorb per-run fluctuation
  ([`56151f3`](https://github.com/jason-weddington/agent-gtd/commit/56151f3433bdeb6b81aa17bb0e279f4e68f19c57))

### Features

- Surface dispatch max-concurrent in Settings (Agent Dispatch section)
  ([`686208c`](https://github.com/jason-weddington/agent-gtd/commit/686208ccfa18801a5aba7d8de8b06202a6b1ee2d))

- **api**: Blockers service + routes with cycle detection
  ([`f659b5e`](https://github.com/jason-weddington/agent-gtd/commit/f659b5e8a84585626c6ec88ca7d6478b8b25b845))

- **api**: Item typeahead search endpoint /api/items/search
  ([`f2e6115`](https://github.com/jason-weddington/agent-gtd/commit/f2e6115bb3c67260353a8b9204e0cdbd32c48c98))

- **api**: Populate blockers on single-item GET responses
  ([`fe689cd`](https://github.com/jason-weddington/agent-gtd/commit/fe689cd11deb592f1c17e88b43c63dc25573f535))

- **db**: Add item_dependencies table schema and migration
  ([`230adb8`](https://github.com/jason-weddington/agent-gtd/commit/230adb858f21b22eb839bea306ff70a466c1be44))

- **frontend**: BlockerPicker component + API client + types
  ([`3e67d23`](https://github.com/jason-weddington/agent-gtd/commit/3e67d230cbf50f54402f291920f8e4a8e2088017))

- **frontend**: Rationalize Projects-review step
  ([`19a496f`](https://github.com/jason-weddington/agent-gtd/commit/19a496f66830a2c39de21911806bd37acf0ed53e))

- **frontend**: Shortcut hint caption in header
  ([`24f2016`](https://github.com/jason-weddington/agent-gtd/commit/24f201677cf146fb2a6d1b77fe22700cc8532f09))

- **frontend**: Show queued dispatch runs in header + drawer
  ([`9da3e09`](https://github.com/jason-weddington/agent-gtd/commit/9da3e099e8e09bce3bcf163827b051bfabcfa90f))

- **frontend**: Wire BlockerPicker into ItemDetailDrawer and GtdItemList edit dialog
  ([`67e714a`](https://github.com/jason-weddington/agent-gtd/commit/67e714a68ced32f79ab0b672ee7bc608baeea8d4))

- **mcp**: Blockers MCP tools (add_blocker, remove_blocker, list_blockers)
  ([`0e8bffc`](https://github.com/jason-weddington/agent-gtd/commit/0e8bffc92a61222358f49f1dc9dafd3f526d6931))


## v1.67.1 (2026-04-17)

### Bug Fixes

- **frontend**: Quick-capture to project defaults status to 'new' (not 'next_action')
  ([`e75a286`](https://github.com/jason-weddington/agent-gtd/commit/e75a286ab4f7c92597b288f478d1cea1ce5995a1))


## v1.67.0 (2026-04-17)

### Features

- **dispatch**: Bump MAX_CONCURRENT from 3 to 6, expose as env var
  ([`7bb3f3b`](https://github.com/jason-weddington/agent-gtd/commit/7bb3f3b5729f50e59d6a10b841f3557c4f18ba64))


## v1.66.0 (2026-04-17)

### Features

- **frontend**: Remove Inbox from status dropdowns in drawer and edit dialogs
  ([`28f9546`](https://github.com/jason-weddington/agent-gtd/commit/28f95467e331912de965be74d64331242245836a))


## v1.65.4 (2026-04-17)

### Bug Fixes

- **frontend**: Disable MUI drawer exit transition during dispatch slide-up
  ([`3304998`](https://github.com/jason-weddington/agent-gtd/commit/330499852072a6fd127ff0618635959023b1ebd2))


## v1.65.3 (2026-04-17)

### Bug Fixes

- **frontend**: Pin minWidth on drawer status/priority/project dropdowns
  ([`48e8f43`](https://github.com/jason-weddington/agent-gtd/commit/48e8f436d6678e33c87d22906087119014cf058a))


## v1.65.2 (2026-04-17)

### Bug Fixes

- **frontend**: Remove Someday column from kanban board
  ([`07e52f5`](https://github.com/jason-weddington/agent-gtd/commit/07e52f519322be48310c02f8c2b63d526a79244d))


## v1.65.1 (2026-04-17)

### Bug Fixes

- **frontend**: Change shortcut help overlay trigger from Cmd+/ to ?
  ([`1dcae06`](https://github.com/jason-weddington/agent-gtd/commit/1dcae06950c477cb725f4ea710235359117b92fa))


## v1.65.0 (2026-04-16)

### Features

- **frontend**: Keyboard shortcuts help overlay (Cmd+/)
  ([`245cef4`](https://github.com/jason-weddington/agent-gtd/commit/245cef4a39c44faebc00c9a511cb5b7a8085dc9a))


## v1.64.0 (2026-04-16)

### Features

- **frontend**: Slide drawer up and away when dispatching
  ([`3468fdd`](https://github.com/jason-weddington/agent-gtd/commit/3468fdd3ccf03d37ec954b19d971e42a6382c1f4))


## v1.63.1 (2026-04-16)

### Bug Fixes

- Default new project items to status "new" not "next_action"
  ([`5865ddb`](https://github.com/jason-weddington/agent-gtd/commit/5865ddb66798468806804dd482ebb4b8962fe88a))


## v1.63.0 (2026-04-16)

### Features

- Per-project agent activity log
  ([`c79a824`](https://github.com/jason-weddington/agent-gtd/commit/c79a8245cba5eb1c039080a6dd4459ad21245523))


## v1.62.0 (2026-04-16)

### Features

- **frontend**: D and Shift+D keyboard shortcuts to dispatch from drawer
  ([`d167c24`](https://github.com/jason-weddington/agent-gtd/commit/d167c245a40b481f88fa9ca6e33c6abc184520d2))


## v1.61.2 (2026-04-16)

### Bug Fixes

- **frontend**: Replace absolute-positioned action buttons with flex layout
  ([`0f0ced8`](https://github.com/jason-weddington/agent-gtd/commit/0f0ced8c2313342f9f282f6f299fd0f5b7f42249))


## v1.61.1 (2026-04-16)

### Bug Fixes

- **frontend**: Add right padding to project list rows for action buttons
  ([`a0d0a78`](https://github.com/jason-weddington/agent-gtd/commit/a0d0a7812ebccbe5879a46cd346289fd911676f8))


## v1.61.0 (2026-04-16)

### Features

- **frontend**: Replace Working spinner chip with pulsing robot icon
  ([`eee4548`](https://github.com/jason-weddington/agent-gtd/commit/eee4548baa79b97c0ad49579c7cab0eaf9b284af))


## v1.60.4 (2026-04-16)

### Bug Fixes

- **frontend**: Improve drawer header spacing between ID, dropdowns, and labels
  ([`fc9cbc1`](https://github.com/jason-weddington/agent-gtd/commit/fc9cbc1a03dfd9d64a8c136bd88adce6c54c0c83))


## v1.60.3 (2026-04-16)

### Bug Fixes

- **frontend**: Change nav shortcuts from Cmd+N to Cmd+Shift+N
  ([`f31e932`](https://github.com/jason-weddington/agent-gtd/commit/f31e9324a73b8cbbd76da35cfcbbe43cf7e85448))


## v1.60.2 (2026-04-16)

### Bug Fixes

- **frontend**: Prevent project switcher Enter from triggering actions on target page
  ([`800b9e6`](https://github.com/jason-weddington/agent-gtd/commit/800b9e68b8b41e0a9f31a160d13bb8e2d1b75bc5))


## v1.60.1 (2026-04-16)

### Bug Fixes

- **frontend**: Truncate project description before action buttons in list view
  ([`2e8ff8d`](https://github.com/jason-weddington/agent-gtd/commit/2e8ff8d0ddab95406265f51fc91d5a2a361369e1))


## v1.60.0 (2026-04-16)

### Features

- **frontend**: Agent dispatch settings with max turns config
  ([`c4110dd`](https://github.com/jason-weddington/agent-gtd/commit/c4110dd27c7c2ffbdd826ed5a77fe1fdd444e998))


## v1.59.0 (2026-04-16)

### Features

- **frontend**: Default dispatch mode to Plan for new items
  ([`d7f4957`](https://github.com/jason-weddington/agent-gtd/commit/d7f49573d484df2b165abbadbe07ebfbe523795f))


## v1.58.1 (2026-04-16)

### Bug Fixes

- **frontend**: Hide run status chip after agent finishes
  ([`d155093`](https://github.com/jason-weddington/agent-gtd/commit/d155093b4d68fdeb790cb79062995c07a9e7ba31))


## v1.58.0 (2026-04-16)

### Features

- **frontend**: Click active run navigates to project and opens drawer
  ([`3e1a50c`](https://github.com/jason-weddington/agent-gtd/commit/3e1a50c9cc226b5b6abd8ddb818086531cd34cfc))


## v1.57.0 (2026-04-16)

### Features

- **frontend**: Add project selector to item edit modal and drawer
  ([`c4b32b4`](https://github.com/jason-weddington/agent-gtd/commit/c4b32b46a8870e5dab2b8391dd30a18adcf8297d))


## v1.56.2 (2026-04-16)

### Bug Fixes

- **frontend**: Align status dropdown choices with kanban columns
  ([`19af743`](https://github.com/jason-weddington/agent-gtd/commit/19af743a190560bdc5f77197fd14dc46a3d526c6))


## v1.56.1 (2026-04-16)

### Bug Fixes

- **frontend**: Reliable focus on project switcher open
  ([`895806b`](https://github.com/jason-weddington/agent-gtd/commit/895806b1f3b7e9ecec05dd5a69379c921f2fc023))


## v1.56.0 (2026-04-16)

### Features

- **frontend**: Pulsing progress bar and icon animation on active runs
  ([`e0ce641`](https://github.com/jason-weddington/agent-gtd/commit/e0ce641899d78f409b0123fbc8df4ed93b5e1bf1))


## v1.55.0 (2026-04-16)

### Features

- **frontend**: Dispatch button with Plan/Build mode toggle
  ([`19bfd1c`](https://github.com/jason-weddington/agent-gtd/commit/19bfd1c418cb39b5ea04a1b4e802415fc34f874c))


## v1.54.0 (2026-04-16)

### Features

- Set item status to active on dispatch (backend)
  ([`aafe19b`](https://github.com/jason-weddington/agent-gtd/commit/aafe19bdf266a6feeca1412d4fe9042006d9cc29))


## v1.53.0 (2026-04-16)

### Features

- Add dispatch mode parameter (plan vs build) end-to-end
  ([`c9f3f52`](https://github.com/jason-weddington/agent-gtd/commit/c9f3f5262e8d7d5965b215a880c1748d95f6e0f3))


## v1.52.0 (2026-04-16)

### Features

- **frontend**: Wire ActiveRunsIndicator into Layout toolbar
  ([`78e03aa`](https://github.com/jason-weddington/agent-gtd/commit/78e03aa99d79225abd05960db84455f3d608e6ba))


## v1.51.0 (2026-04-16)

### Features

- **frontend**: Add quick project switcher modal (Cmd+Shift+P)
  ([`a7a9de8`](https://github.com/jason-weddington/agent-gtd/commit/a7a9de83fa18bfe7f88b9ee552e7182ae14166a5))


## v1.50.1 (2026-04-16)

### Bug Fixes

- **frontend**: Register left nav keyboard shortcuts in Sidebar
  ([`f30276b`](https://github.com/jason-weddington/agent-gtd/commit/f30276bb3a404dbd5e2e12dcd705260be58011b8))


## v1.50.0 (2026-04-16)

### Features

- **frontend**: Create ActiveRunsIndicator component
  ([`c45e15c`](https://github.com/jason-weddington/agent-gtd/commit/c45e15c1b379eea00a165c2a4cab24e1feff1c00))


## v1.49.1 (2026-04-15)

### Bug Fixes

- **frontend**: Merge To Do column into Ready on kanban board
  ([`7b85d98`](https://github.com/jason-weddington/agent-gtd/commit/7b85d98d7c26a44c435331238511670df1f188b5))

### Chores

- Bump default max_turns from 50 to 100
  ([`727038d`](https://github.com/jason-weddington/agent-gtd/commit/727038d7e9c7020d53ef963a485ae1b2c513f692))


## v1.49.0 (2026-04-15)

### Features

- **frontend**: Add api.runs.list() method
  ([`c57a32b`](https://github.com/jason-weddington/agent-gtd/commit/c57a32ba6ec3e3a568e92cac7ee5d99d5ee87711))


## v1.48.1 (2026-04-15)

### Bug Fixes

- **frontend**: Prevent kanban board from causing page-level horizontal scroll
  ([`d0b54b2`](https://github.com/jason-weddington/agent-gtd/commit/d0b54b2d06a55c2f4e6892da6c720dedf49d8f44))


## v1.48.0 (2026-04-15)

### Features

- **frontend**: Filter task list by label
  ([`3b64424`](https://github.com/jason-weddington/agent-gtd/commit/3b64424559ac824587508e82770de787f3b95385))


## v1.47.0 (2026-04-15)

### Features

- **frontend**: Show labels as compact chips on item cards
  ([`0de3f75`](https://github.com/jason-weddington/agent-gtd/commit/0de3f757fa023d0e791bdb44247c4e3d85e64a76))


## v1.46.1 (2026-04-15)

### Bug Fixes

- **frontend**: Truncate long item titles with ellipsis in list view
  ([`bed462a`](https://github.com/jason-weddington/agent-gtd/commit/bed462a2658996f91ae34ec3b97008c8cd6fefeb))


## v1.46.0 (2026-04-15)

### Features

- Add "new" and "ready" item statuses for grooming workflow
  ([`626b47d`](https://github.com/jason-weddington/agent-gtd/commit/626b47dfad541ec075f4ba37f949fd37a0658f56))


## v1.45.0 (2026-04-15)

### Features

- **frontend**: Set item to active status on dispatch
  ([`f4d7b13`](https://github.com/jason-weddington/agent-gtd/commit/f4d7b13394b0cd906dd2050550e00c8e85301ba7))


## v1.44.0 (2026-04-15)

### Features

- Resilient dispatch run tracking across service restarts
  ([`d944781`](https://github.com/jason-weddington/agent-gtd/commit/d94478131a884624e10001a7181d204872796416))


## v1.43.0 (2026-04-15)

### Features

- **frontend**: Add inline editing to ItemDetailDrawer
  ([`50b1756`](https://github.com/jason-weddington/agent-gtd/commit/50b17563853fb37af363b5387326010658b3bbf2))


## v1.42.0 (2026-04-15)

### Features

- Add "review" item status for agent-completed work awaiting merge
  ([`291f7d9`](https://github.com/jason-weddington/agent-gtd/commit/291f7d9407b56617c3051897a73afb588236e939))


## v1.41.0 (2026-04-15)

### Features

- **frontend**: Add search/filter box to task list in project detail view
  ([`e8eed74`](https://github.com/jason-weddington/agent-gtd/commit/e8eed74f3feb8bc5fa52fbd52ceb4202e30b7175))


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
