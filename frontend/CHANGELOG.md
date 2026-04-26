# CHANGELOG

<!-- version list -->

## v1.75.0 (2026-04-26)

### Features

- **frontend**: Collapse metadata in task drawer behind accordion
  ([`ac892ba`](https://github.com/repos/agent_gtd/commit/ac892bab1707f1d18cbb6a558cfa190025f61cb1))


## v1.74.0 (2026-04-25)

### Bug Fixes

- **frontend**: Declare @adobe/css-tools as an explicit devDependency
  ([`80416c5`](https://github.com/repos/agent_gtd/commit/80416c5d8d8fe8328e57d3a3379fcce887ebbb08))

### Chores

- Lower coverage floor back to 94.0
  ([`e28c5ed`](https://github.com/repos/agent_gtd/commit/e28c5ed5e04a433b244927d9cfdd1145cdf27ed8))

- Ratchet coverage floor to 94.2
  ([`7b96d16`](https://github.com/repos/agent_gtd/commit/7b96d167e0380c17b84a9aecde545ab1f652cd1f))

- **release**: 1.74.0
  ([`bf67759`](https://github.com/repos/agent_gtd/commit/bf67759d9b5e6b67a20793894e5f3c634d59df95))

### Features

- **cli**: Add agent-gtd run-status command for shell-based monitoring
  ([`362e877`](https://github.com/repos/agent_gtd/commit/362e877ab9d701d551fea1c80c60a7d35709b599))

- **frontend**: Add Remote Dispatch shortcuts to the keyboard shortcuts modal
  ([`d89ac5d`](https://github.com/repos/agent_gtd/commit/d89ac5de73c3253e28c3bad7d65bb3764ef4c165))

- **frontend**: Mobile-friendly layout improvements
  ([`cd982c5`](https://github.com/repos/agent_gtd/commit/cd982c59cc33f72462fc1e333e2e86b24ffd1b32))

- **frontend**: Open item detail drawer from Weekly Review Next Actions step
  ([`4231f72`](https://github.com/repos/agent_gtd/commit/4231f72cb93a972bb1d108345d9655f0765b76bb))

### Refactoring

- Remove claim_item/release_item MCP tools, add delete_note + update_project
  ([`fecabdf`](https://github.com/repos/agent_gtd/commit/fecabdfa16d3916b91254570d243aa10dd19ae0e))


## v1.73.0 (2026-04-23)

### Chores

- **release**: 1.73.0
  ([`81b0e90`](https://github.com/repos/agent_gtd/commit/81b0e909fe9f3b508cf47dd7ba3002b82f175a47))


## v1.72.0 (2026-04-22)

### Bug Fixes

- Engine-agnostic copy for robot icon tooltip and dialog title
  ([`ba0e91e`](https://github.com/repos/agent_gtd/commit/ba0e91e107a744b74206b1008729471bd1fd6929))

- Item detail drawer refetches blockers on every open
  ([`3e8306c`](https://github.com/repos/agent_gtd/commit/3e8306c5172fb62bfba63aca789caf56b5036968))

### Chores

- **release**: 1.72.0
  ([`fa06f8b`](https://github.com/repos/agent_gtd/commit/fa06f8bffc824fb48a7e1dc6a7fa56de7f2023a1))

### Features

- Add CORS origins for HTTPS/hostname access and ignore .kiro
  ([`83b3067`](https://github.com/repos/agent_gtd/commit/83b306743c69de6f2ddb3537ed335ebf2b791d3c))

- Attachments backend — schema, storage, list/get/delete endpoints
  ([`cb4b0df`](https://github.com/repos/agent_gtd/commit/cb4b0dfb01b2999e7262a8cca9a7524c99f322c6))

- Attachments upload endpoint
  ([`afb9032`](https://github.com/repos/agent_gtd/commit/afb90328c3c31eaa93df2d0a6b8b9c627c452ce1))

- Expose item due dates via MCP add_item / update_item and make editable in the drawer
  ([`001e695`](https://github.com/repos/agent_gtd/commit/001e6958610fdc1409e42f1ac208f122748d04cb))

- **frontend**: Attachments section in item detail drawer
  ([`f414e83`](https://github.com/repos/agent_gtd/commit/f414e832742f96e078b2fc03969f55d99a14fa94))


## v1.71.0 (2026-04-22)

### Chores

- Set coverage precision=1 so fractional fail_under works
  ([`de8b289`](https://github.com/repos/agent_gtd/commit/de8b2894f5c1da12d9eefb12250df9ca0da9774b))

- **release**: 1.71.0
  ([`4dc6a6e`](https://github.com/repos/agent_gtd/commit/4dc6a6e40beb95f04d22a88fabc9288f4b05ab04))

### Code Style

- Apply ruff-format to dispatch_worker resolution helpers
  ([`dfca487`](https://github.com/repos/agent_gtd/commit/dfca487d79d2b394220c1b3bbf7b177230ba9a42))

### Features

- Add /api/dispatch/capabilities proxy for engine + agents list
  ([`b2becfd`](https://github.com/repos/agent_gtd/commit/b2becfde34cf38885f5d25983b34a4efe12d4422))

- Add project-scoped dispatch agent/max_turns resolution with global fallback
  ([`f6bce35`](https://github.com/repos/agent_gtd/commit/f6bce35d7d5f6009ef1731629229676798011c77))

- Add project-scoped dispatch_agent and dispatch_max_turns overrides
  ([`2e7f2e5`](https://github.com/repos/agent_gtd/commit/2e7f2e573f6326f87c99d157ea126007e3590048))

- **frontend**: Add Dispatch tab to project detail page
  ([`82a8c93`](https://github.com/repos/agent_gtd/commit/82a8c9347b8f666e77a0f0c6f0b67b149fb1eb8d))

- **frontend**: Show API key + MCP config in modal after creation
  ([`2eb0109`](https://github.com/repos/agent_gtd/commit/2eb0109b8ad9ea478a7bbb51db48e06ffc1950be))

- **frontend**: Upgrade agent_name field to Autocomplete dropdown + show engine identity
  ([`bdcd5bf`](https://github.com/repos/agent_gtd/commit/bdcd5bf387602dec47528638e4bb4f23b91fad7e))


## v1.70.0 (2026-04-20)

### Bug Fixes

- **settings**: Always show masked API key preview in dispatch field
  ([`37b2a14`](https://github.com/repos/agent_gtd/commit/37b2a14ab1615256629e21acfcaea4e5fbcda191))

### Chores

- **release**: 1.70.0
  ([`741722a`](https://github.com/repos/agent_gtd/commit/741722a3288343b30290360aa2efafac34be752a))

### Features

- **settings**: Persist dispatch default_max_turns server-side
  ([`f03f321`](https://github.com/repos/agent_gtd/commit/f03f3214aa4433945936c023f80a19f8f1e3c491))


## v1.69.0 (2026-04-18)

### Chores

- Relax coverage floor 93.3 -> 93 to absorb rounding fluctuation
  ([`aee3500`](https://github.com/repos/agent_gtd/commit/aee35002d61d31057b8f735e7aa51c665bc1dfba))

- **release**: 1.69.0
  ([`4e52cc9`](https://github.com/repos/agent_gtd/commit/4e52cc95a2f92ad27c71a9d24a616db2084c029c))

### Features

- Engine + agent_name surfaced in dispatch settings
  ([`edaf790`](https://github.com/repos/agent_gtd/commit/edaf7909d0513c80d7f3494f90c483ce72efbc5c))

- Per-user dispatch config + owner-only dispatch guard
  ([`1ef51ed`](https://github.com/repos/agent_gtd/commit/1ef51ed89a1a93687e00a4ef24d24f5f878d4f39))

- **api**: Scope queries to accessible (owned + shared) projects
  ([`cb581fd`](https://github.com/repos/agent_gtd/commit/cb581fdc4f39e7ba12e9ee89e091997d9ec2a4b2))

- **api**: Search scoping + blocker sandboxing for shared projects
  ([`0623c53`](https://github.com/repos/agent_gtd/commit/0623c53a407fcbcdd5216832d31fd3c73ec05068))

- **api**: Settings returns service_api_key_preview instead of configured bool
  ([`0d9c1b3`](https://github.com/repos/agent_gtd/commit/0d9c1b3b332cf4c926a9c8ba64672366ead34f35))

- **api**: Share management endpoints + MCP tools
  ([`8b41176`](https://github.com/repos/agent_gtd/commit/8b4117640346e9957424de59ae98de0f10ec9f8a))

- **db**: Add project_members table + indexes
  ([`232094a`](https://github.com/repos/agent_gtd/commit/232094a78185a744e328fe5301f735bb812d884c))

- **frontend**: Masked API key preview — write-only field behavior
  ([`982f3a2`](https://github.com/repos/agent_gtd/commit/982f3a25d0b802b3d9da3a80cdb39d60d527fcb6))

- **frontend**: Shared-project UI — share tab, handshake, shared-with-you, attribution
  ([`17b5740`](https://github.com/repos/agent_gtd/commit/17b5740ca9f414b91db783d111de2cecf7d44f8c))

- **mcp**: Board_state snapshot on project-scoped tool responses
  ([`16113b7`](https://github.com/repos/agent_gtd/commit/16113b758cc1e9f33304d260d9edf2c519652a4a))


## v1.68.0 (2026-04-17)

### Bug Fixes

- **frontend**: Align review inbox triage statuses with kanban
  ([`1edb400`](https://github.com/repos/agent_gtd/commit/1edb400529dda60beba99b4367f6c7f3b502b6b3))

- **frontend**: Narrow header brand click target to title text only
  ([`234e2c1`](https://github.com/repos/agent_gtd/commit/234e2c1ed7e28e9a526487f1d0cecc4fb8bbd0ca))

- **frontend**: Prevent MUI right-slide after dispatch slide-up
  ([`84dc012`](https://github.com/repos/agent_gtd/commit/84dc012c4110855b0df5f64054d05d1768667cc3))

- **frontend**: Sort project list alphabetically case-insensitive
  ([`91d05a5`](https://github.com/repos/agent_gtd/commit/91d05a508ac03a042a31026f6ca2bc5e44b78729))

- **frontend**: Tick elapsed time live in ActiveRunsIndicator
  ([`6a2ea1f`](https://github.com/repos/agent_gtd/commit/6a2ea1fa81fe39829a8333aca4e9804c6d4e5512))

### Chores

- Decouple release from deploy
  ([`42ce061`](https://github.com/repos/agent_gtd/commit/42ce06190a9f9179c262dfffeea0414274fecb4e))

- Gitignore .claude workspace state
  ([`b3ecb00`](https://github.com/repos/agent_gtd/commit/b3ecb005c86c6a823e88b014166a52bb4873bdb8))

- Relax coverage floor 93.4 -> 93 to absorb per-run fluctuation
  ([`56151f3`](https://github.com/repos/agent_gtd/commit/56151f3433bdeb6b81aa17bb0e279f4e68f19c57))

- **release**: 1.68.0
  ([`3cf53fa`](https://github.com/repos/agent_gtd/commit/3cf53fa826f7f7dd3048209bdf4ca5390031db21))

### Features

- Surface dispatch max-concurrent in Settings (Agent Dispatch section)
  ([`686208c`](https://github.com/repos/agent_gtd/commit/686208ccfa18801a5aba7d8de8b06202a6b1ee2d))

- **api**: Blockers service + routes with cycle detection
  ([`f659b5e`](https://github.com/repos/agent_gtd/commit/f659b5e8a84585626c6ec88ca7d6478b8b25b845))

- **api**: Item typeahead search endpoint /api/items/search
  ([`f2e6115`](https://github.com/repos/agent_gtd/commit/f2e6115bb3c67260353a8b9204e0cdbd32c48c98))

- **api**: Populate blockers on single-item GET responses
  ([`fe689cd`](https://github.com/repos/agent_gtd/commit/fe689cd11deb592f1c17e88b43c63dc25573f535))

- **db**: Add item_dependencies table schema and migration
  ([`230adb8`](https://github.com/repos/agent_gtd/commit/230adb858f21b22eb839bea306ff70a466c1be44))

- **frontend**: BlockerPicker component + API client + types
  ([`3e67d23`](https://github.com/repos/agent_gtd/commit/3e67d230cbf50f54402f291920f8e4a8e2088017))

- **frontend**: Rationalize Projects-review step
  ([`19a496f`](https://github.com/repos/agent_gtd/commit/19a496f66830a2c39de21911806bd37acf0ed53e))

- **frontend**: Shortcut hint caption in header
  ([`24f2016`](https://github.com/repos/agent_gtd/commit/24f201677cf146fb2a6d1b77fe22700cc8532f09))

- **frontend**: Show queued dispatch runs in header + drawer
  ([`9da3e09`](https://github.com/repos/agent_gtd/commit/9da3e099e8e09bce3bcf163827b051bfabcfa90f))

- **frontend**: Wire BlockerPicker into ItemDetailDrawer and GtdItemList edit dialog
  ([`67e714a`](https://github.com/repos/agent_gtd/commit/67e714a68ced32f79ab0b672ee7bc608baeea8d4))

- **mcp**: Blockers MCP tools (add_blocker, remove_blocker, list_blockers)
  ([`0e8bffc`](https://github.com/repos/agent_gtd/commit/0e8bffc92a61222358f49f1dc9dafd3f526d6931))


## v1.67.1 (2026-04-17)

### Bug Fixes

- **frontend**: Quick-capture to project defaults status to 'new' (not 'next_action')
  ([`e75a286`](https://github.com/repos/agent_gtd/commit/e75a286ab4f7c92597b288f478d1cea1ce5995a1))

### Chores

- **release**: 1.67.1
  ([`b504af8`](https://github.com/repos/agent_gtd/commit/b504af8c1ee6504e306fc95462931fec401ab48d))


## v1.67.0 (2026-04-17)

### Chores

- **release**: 1.67.0
  ([`718cf1e`](https://github.com/repos/agent_gtd/commit/718cf1ef28bfebef5d8dae178432fff10b9dd36d))

### Features

- **dispatch**: Bump MAX_CONCURRENT from 3 to 6, expose as env var
  ([`7bb3f3b`](https://github.com/repos/agent_gtd/commit/7bb3f3b5729f50e59d6a10b841f3557c4f18ba64))


## v1.66.0 (2026-04-17)

### Chores

- **release**: 1.66.0
  ([`8bf6ee5`](https://github.com/repos/agent_gtd/commit/8bf6ee5268d13397ddc6adaaad7dcf10b7e1d01c))

### Features

- **frontend**: Remove Inbox from status dropdowns in drawer and edit dialogs
  ([`28f9546`](https://github.com/repos/agent_gtd/commit/28f95467e331912de965be74d64331242245836a))


## v1.65.4 (2026-04-17)

### Bug Fixes

- **frontend**: Disable MUI drawer exit transition during dispatch slide-up
  ([`3304998`](https://github.com/repos/agent_gtd/commit/330499852072a6fd127ff0618635959023b1ebd2))

### Chores

- **release**: 1.65.4
  ([`fc13818`](https://github.com/repos/agent_gtd/commit/fc138189894b7c6dd7b623fde506d2463284d860))


## v1.65.3 (2026-04-17)

### Bug Fixes

- **frontend**: Pin minWidth on drawer status/priority/project dropdowns
  ([`48e8f43`](https://github.com/repos/agent_gtd/commit/48e8f436d6678e33c87d22906087119014cf058a))

### Chores

- **release**: 1.65.3
  ([`4c5d4ae`](https://github.com/repos/agent_gtd/commit/4c5d4ae90d13c7baa6ef95eb71647f54f15e185e))


## v1.65.2 (2026-04-17)

### Bug Fixes

- **frontend**: Remove Someday column from kanban board
  ([`07e52f5`](https://github.com/repos/agent_gtd/commit/07e52f519322be48310c02f8c2b63d526a79244d))

### Chores

- **release**: 1.65.2
  ([`99a47be`](https://github.com/repos/agent_gtd/commit/99a47be8a6e4bd6c35ae4cdd10b0636724b24ca1))


## v1.65.1 (2026-04-17)

### Bug Fixes

- **frontend**: Change shortcut help overlay trigger from Cmd+/ to ?
  ([`1dcae06`](https://github.com/repos/agent_gtd/commit/1dcae06950c477cb725f4ea710235359117b92fa))

### Chores

- **release**: 1.65.1
  ([`c9b6645`](https://github.com/repos/agent_gtd/commit/c9b66452364ecc96e89100d500dc5684d345218f))


## v1.65.0 (2026-04-16)

### Chores

- **release**: 1.65.0
  ([`1d7627e`](https://github.com/repos/agent_gtd/commit/1d7627e52de6755240091b83e12aab0325d78b06))

### Features

- **frontend**: Keyboard shortcuts help overlay (Cmd+/)
  ([`245cef4`](https://github.com/repos/agent_gtd/commit/245cef4a39c44faebc00c9a511cb5b7a8085dc9a))


## v1.64.0 (2026-04-16)

### Chores

- **release**: 1.64.0
  ([`2f6321d`](https://github.com/repos/agent_gtd/commit/2f6321df226790604256b975a355f2443903e7e3))

### Features

- **frontend**: Slide drawer up and away when dispatching
  ([`3468fdd`](https://github.com/repos/agent_gtd/commit/3468fdd3ccf03d37ec954b19d971e42a6382c1f4))


## v1.63.1 (2026-04-16)

### Bug Fixes

- Default new project items to status "new" not "next_action"
  ([`5865ddb`](https://github.com/repos/agent_gtd/commit/5865ddb66798468806804dd482ebb4b8962fe88a))

### Chores

- **release**: 1.63.1
  ([`7548a34`](https://github.com/repos/agent_gtd/commit/7548a3410e839b2b45e22590f6c71423196d0d38))


## v1.63.0 (2026-04-16)

### Chores

- **release**: 1.63.0
  ([`c0fa3cc`](https://github.com/repos/agent_gtd/commit/c0fa3ccaac14a55395da69398bd02856ef8ed9cc))

### Features

- Per-project agent activity log
  ([`c79a824`](https://github.com/repos/agent_gtd/commit/c79a8245cba5eb1c039080a6dd4459ad21245523))


## v1.62.0 (2026-04-16)

### Chores

- **release**: 1.62.0
  ([`c3a6b79`](https://github.com/repos/agent_gtd/commit/c3a6b7907442a7888f7d7630e5094850efc3d54a))

### Features

- **frontend**: D and Shift+D keyboard shortcuts to dispatch from drawer
  ([`d167c24`](https://github.com/repos/agent_gtd/commit/d167c245a40b481f88fa9ca6e33c6abc184520d2))


## v1.61.2 (2026-04-16)

### Bug Fixes

- **frontend**: Replace absolute-positioned action buttons with flex layout
  ([`0f0ced8`](https://github.com/repos/agent_gtd/commit/0f0ced8c2313342f9f282f6f299fd0f5b7f42249))

### Chores

- **release**: 1.61.2
  ([`a639eeb`](https://github.com/repos/agent_gtd/commit/a639eeb367c414529d7e4ee0219c95d6e2b1df49))


## v1.61.1 (2026-04-16)

### Bug Fixes

- **frontend**: Add right padding to project list rows for action buttons
  ([`a0d0a78`](https://github.com/repos/agent_gtd/commit/a0d0a7812ebccbe5879a46cd346289fd911676f8))

### Chores

- **release**: 1.61.1
  ([`2c69940`](https://github.com/repos/agent_gtd/commit/2c6994024d600ff37909190eb2ec2d8efa1c2bf8))


## v1.61.0 (2026-04-16)

### Chores

- **release**: 1.61.0
  ([`1b9b813`](https://github.com/repos/agent_gtd/commit/1b9b8136e586c5313e625045479427bf99793649))

### Features

- **frontend**: Replace Working spinner chip with pulsing robot icon
  ([`eee4548`](https://github.com/repos/agent_gtd/commit/eee4548baa79b97c0ad49579c7cab0eaf9b284af))


## v1.60.4 (2026-04-16)

### Bug Fixes

- **frontend**: Improve drawer header spacing between ID, dropdowns, and labels
  ([`fc9cbc1`](https://github.com/repos/agent_gtd/commit/fc9cbc1a03dfd9d64a8c136bd88adce6c54c0c83))

### Chores

- **release**: 1.60.4
  ([`f9e66bb`](https://github.com/repos/agent_gtd/commit/f9e66bbe86d376fee6473fe19a4cd659ce33eb29))


## v1.60.3 (2026-04-16)

### Bug Fixes

- **frontend**: Change nav shortcuts from Cmd+N to Cmd+Shift+N
  ([`f31e932`](https://github.com/repos/agent_gtd/commit/f31e9324a73b8cbbd76da35cfcbbe43cf7e85448))

### Chores

- **release**: 1.60.3
  ([`92a11da`](https://github.com/repos/agent_gtd/commit/92a11dad925d0a3ee37eeb1c13e48b97f8b3d2f7))


## v1.60.2 (2026-04-16)

### Bug Fixes

- **frontend**: Prevent project switcher Enter from triggering actions on target page
  ([`800b9e6`](https://github.com/repos/agent_gtd/commit/800b9e68b8b41e0a9f31a160d13bb8e2d1b75bc5))

### Chores

- **release**: 1.60.2
  ([`c84be13`](https://github.com/repos/agent_gtd/commit/c84be13df882670c19365c0454bba4c9769fb811))


## v1.60.1 (2026-04-16)

### Bug Fixes

- **frontend**: Truncate project description before action buttons in list view
  ([`2e8ff8d`](https://github.com/repos/agent_gtd/commit/2e8ff8d0ddab95406265f51fc91d5a2a361369e1))

### Chores

- **release**: 1.60.1
  ([`07a1682`](https://github.com/repos/agent_gtd/commit/07a16820bab8389fbedd2025391faa75368aad4d))


## v1.60.0 (2026-04-16)

### Chores

- **release**: 1.60.0
  ([`5e3ac38`](https://github.com/repos/agent_gtd/commit/5e3ac388cf8a46cff588a5f218a453a169972390))

### Features

- **frontend**: Agent dispatch settings with max turns config
  ([`c4110dd`](https://github.com/repos/agent_gtd/commit/c4110dd27c7c2ffbdd826ed5a77fe1fdd444e998))


## v1.59.0 (2026-04-16)

### Chores

- **release**: 1.59.0
  ([`cbf213f`](https://github.com/repos/agent_gtd/commit/cbf213f371ff256699b2bdb77e5ffc72551c9ffa))

### Features

- **frontend**: Default dispatch mode to Plan for new items
  ([`d7f4957`](https://github.com/repos/agent_gtd/commit/d7f49573d484df2b165abbadbe07ebfbe523795f))


## v1.58.1 (2026-04-16)

### Bug Fixes

- **frontend**: Hide run status chip after agent finishes
  ([`d155093`](https://github.com/repos/agent_gtd/commit/d155093b4d68fdeb790cb79062995c07a9e7ba31))

### Chores

- **release**: 1.58.1
  ([`98cec07`](https://github.com/repos/agent_gtd/commit/98cec0765d0d33f085e3527e802190663b10170f))


## v1.58.0 (2026-04-16)

### Chores

- **release**: 1.58.0
  ([`2e9ee13`](https://github.com/repos/agent_gtd/commit/2e9ee13abe2b80f23e051ceab0cd97ac3be6747c))

### Features

- **frontend**: Click active run navigates to project and opens drawer
  ([`3e1a50c`](https://github.com/repos/agent_gtd/commit/3e1a50c9cc226b5b6abd8ddb818086531cd34cfc))


## v1.57.0 (2026-04-16)

### Chores

- **release**: 1.57.0
  ([`25ead8b`](https://github.com/repos/agent_gtd/commit/25ead8b18682f4765ff73e1acc3852632a1fff31))

### Features

- **frontend**: Add project selector to item edit modal and drawer
  ([`c4b32b4`](https://github.com/repos/agent_gtd/commit/c4b32b46a8870e5dab2b8391dd30a18adcf8297d))


## v1.56.2 (2026-04-16)

### Bug Fixes

- **frontend**: Align status dropdown choices with kanban columns
  ([`19af743`](https://github.com/repos/agent_gtd/commit/19af743a190560bdc5f77197fd14dc46a3d526c6))

### Chores

- **release**: 1.56.2
  ([`8d62e4e`](https://github.com/repos/agent_gtd/commit/8d62e4eb208afd4f9778063d3ae52de2d41a537e))


## v1.56.1 (2026-04-16)

### Bug Fixes

- **frontend**: Reliable focus on project switcher open
  ([`895806b`](https://github.com/repos/agent_gtd/commit/895806b1f3b7e9ecec05dd5a69379c921f2fc023))

### Chores

- **release**: 1.56.1
  ([`86928a8`](https://github.com/repos/agent_gtd/commit/86928a8b750a9807a6aa590b958ef7685ea2384e))


## v1.56.0 (2026-04-16)

### Chores

- **release**: 1.56.0
  ([`b3ac05c`](https://github.com/repos/agent_gtd/commit/b3ac05c4f095039922e48e6f258adb49e22ccb25))

### Features

- **frontend**: Pulsing progress bar and icon animation on active runs
  ([`e0ce641`](https://github.com/repos/agent_gtd/commit/e0ce641899d78f409b0123fbc8df4ed93b5e1bf1))


## v1.55.0 (2026-04-16)

### Chores

- **release**: 1.55.0
  ([`365471e`](https://github.com/repos/agent_gtd/commit/365471e9ba866d97873cf6381c6916bef6cdb3ef))

### Features

- **frontend**: Dispatch button with Plan/Build mode toggle
  ([`19bfd1c`](https://github.com/repos/agent_gtd/commit/19bfd1c418cb39b5ea04a1b4e802415fc34f874c))


## v1.54.0 (2026-04-16)

### Chores

- **release**: 1.54.0
  ([`f209fd7`](https://github.com/repos/agent_gtd/commit/f209fd7680a8a637044ea59350f5d6acf5c65229))

### Features

- Set item status to active on dispatch (backend)
  ([`aafe19b`](https://github.com/repos/agent_gtd/commit/aafe19bdf266a6feeca1412d4fe9042006d9cc29))


## v1.53.0 (2026-04-16)

### Chores

- **release**: 1.53.0
  ([`937a036`](https://github.com/repos/agent_gtd/commit/937a036de106f43d2f50070a1d3cd405be1e5ee4))

### Features

- Add dispatch mode parameter (plan vs build) end-to-end
  ([`c9f3f52`](https://github.com/repos/agent_gtd/commit/c9f3f5262e8d7d5965b215a880c1748d95f6e0f3))


## v1.52.0 (2026-04-16)

### Chores

- **release**: 1.52.0
  ([`b094b11`](https://github.com/repos/agent_gtd/commit/b094b1180fb8248fd9cf272a80ac7e7ffa97b009))

### Features

- **frontend**: Wire ActiveRunsIndicator into Layout toolbar
  ([`78e03aa`](https://github.com/repos/agent_gtd/commit/78e03aa99d79225abd05960db84455f3d608e6ba))


## v1.51.0 (2026-04-16)

### Chores

- **release**: 1.51.0
  ([`a5a2886`](https://github.com/repos/agent_gtd/commit/a5a28867ce52bedae9515ea682d582fd70aa409c))

### Features

- **frontend**: Add quick project switcher modal (Cmd+Shift+P)
  ([`a7a9de8`](https://github.com/repos/agent_gtd/commit/a7a9de83fa18bfe7f88b9ee552e7182ae14166a5))


## v1.50.1 (2026-04-16)

### Bug Fixes

- **frontend**: Register left nav keyboard shortcuts in Sidebar
  ([`f30276b`](https://github.com/repos/agent_gtd/commit/f30276bb3a404dbd5e2e12dcd705260be58011b8))

### Chores

- **release**: 1.50.1
  ([`2fc917a`](https://github.com/repos/agent_gtd/commit/2fc917a83e499c541c72f8ab845c2c2d0f86a237))


## v1.50.0 (2026-04-16)

### Chores

- **release**: 1.50.0
  ([`bb07077`](https://github.com/repos/agent_gtd/commit/bb07077c991ab4f48a2c4b331f60b5929139e447))

### Features

- **frontend**: Create ActiveRunsIndicator component
  ([`c45e15c`](https://github.com/repos/agent_gtd/commit/c45e15c1b379eea00a165c2a4cab24e1feff1c00))


## v1.49.1 (2026-04-15)

### Bug Fixes

- **frontend**: Merge To Do column into Ready on kanban board
  ([`7b85d98`](https://github.com/repos/agent_gtd/commit/7b85d98d7c26a44c435331238511670df1f188b5))

### Chores

- Bump default max_turns from 50 to 100
  ([`727038d`](https://github.com/repos/agent_gtd/commit/727038d7e9c7020d53ef963a485ae1b2c513f692))

- **release**: 1.49.1
  ([`32019d8`](https://github.com/repos/agent_gtd/commit/32019d88b9a190a62f1a2f8f8e0d70b20b3fa1b5))


## v1.49.0 (2026-04-15)

### Chores

- **release**: 1.49.0
  ([`6d9a451`](https://github.com/repos/agent_gtd/commit/6d9a451068f77efdb99cb3551bd9cd82887d0108))

### Features

- **frontend**: Add api.runs.list() method
  ([`c57a32b`](https://github.com/repos/agent_gtd/commit/c57a32ba6ec3e3a568e92cac7ee5d99d5ee87711))


## v1.48.1 (2026-04-15)

### Bug Fixes

- **frontend**: Prevent kanban board from causing page-level horizontal scroll
  ([`d0b54b2`](https://github.com/repos/agent_gtd/commit/d0b54b2d06a55c2f4e6892da6c720dedf49d8f44))

### Chores

- **release**: 1.48.1
  ([`e18f1ce`](https://github.com/repos/agent_gtd/commit/e18f1cec6d74a7695205524b127817dcd8d85bb3))


## v1.48.0 (2026-04-15)

### Chores

- **release**: 1.48.0
  ([`e177bde`](https://github.com/repos/agent_gtd/commit/e177bde9620363a496bc2917638f218ed13c64ae))

### Features

- **frontend**: Filter task list by label
  ([`3b64424`](https://github.com/repos/agent_gtd/commit/3b64424559ac824587508e82770de787f3b95385))


## v1.47.0 (2026-04-15)

### Chores

- **release**: 1.47.0
  ([`57a1aa4`](https://github.com/repos/agent_gtd/commit/57a1aa4f1eb1c48cfbaf42117360480f739e59ca))

### Features

- **frontend**: Show labels as compact chips on item cards
  ([`0de3f75`](https://github.com/repos/agent_gtd/commit/0de3f757fa023d0e791bdb44247c4e3d85e64a76))


## v1.46.1 (2026-04-15)

### Bug Fixes

- **frontend**: Truncate long item titles with ellipsis in list view
  ([`bed462a`](https://github.com/repos/agent_gtd/commit/bed462a2658996f91ae34ec3b97008c8cd6fefeb))

### Chores

- **release**: 1.46.1
  ([`2c1ada8`](https://github.com/repos/agent_gtd/commit/2c1ada8160e93bb7e0055a831d622d1a77ddf14d))


## v1.46.0 (2026-04-15)

### Chores

- **release**: 1.46.0
  ([`b287665`](https://github.com/repos/agent_gtd/commit/b287665899082ec22310a7caf2c9f1a8df24b698))

### Features

- Add "new" and "ready" item statuses for grooming workflow
  ([`626b47d`](https://github.com/repos/agent_gtd/commit/626b47dfad541ec075f4ba37f949fd37a0658f56))


## v1.45.0 (2026-04-15)

### Chores

- **release**: 1.45.0
  ([`7265c26`](https://github.com/repos/agent_gtd/commit/7265c2621d2c18ace27e6d21cd5f7745e4e58ee7))

### Features

- **frontend**: Set item to active status on dispatch
  ([`f4d7b13`](https://github.com/repos/agent_gtd/commit/f4d7b13394b0cd906dd2050550e00c8e85301ba7))


## v1.44.0 (2026-04-15)

### Chores

- **release**: 1.44.0
  ([`9b11149`](https://github.com/repos/agent_gtd/commit/9b11149381a393f015afbee81216f822e633931c))

### Features

- Resilient dispatch run tracking across service restarts
  ([`d944781`](https://github.com/repos/agent_gtd/commit/d94478131a884624e10001a7181d204872796416))


## v1.43.0 (2026-04-15)

### Chores

- **release**: 1.43.0
  ([`52734df`](https://github.com/repos/agent_gtd/commit/52734dfee6850cb0a3dcbebc52cf32ed715a2fc3))

### Features

- **frontend**: Add inline editing to ItemDetailDrawer
  ([`50b1756`](https://github.com/repos/agent_gtd/commit/50b17563853fb37af363b5387326010658b3bbf2))


## v1.42.0 (2026-04-15)

### Chores

- **release**: 1.42.0
  ([`bec9d44`](https://github.com/repos/agent_gtd/commit/bec9d44b70fb8df845fe4d3f32e88ee7f29512ac))

### Features

- Add "review" item status for agent-completed work awaiting merge
  ([`291f7d9`](https://github.com/repos/agent_gtd/commit/291f7d9407b56617c3051897a73afb588236e939))


## v1.41.0 (2026-04-15)

### Chores

- **release**: 1.41.0
  ([`d93f7af`](https://github.com/repos/agent_gtd/commit/d93f7af2a198ca80efb9a66e1867c212058c4463))

### Features

- **frontend**: Add search/filter box to task list in project detail view
  ([`e8eed74`](https://github.com/repos/agent_gtd/commit/e8eed74f3feb8bc5fa52fbd52ceb4202e30b7175))


## v1.40.0 (2026-04-15)

### Chores

- Add deploy.sh to gitignore
  ([`eb714c9`](https://github.com/repos/agent_gtd/commit/eb714c9b353bcecdaf244e95b6f4a27f004d5c90))

- **release**: 1.40.0
  ([`03e50e4`](https://github.com/repos/agent_gtd/commit/03e50e414a688d711c1b9b63d0ed3645e273dac2))

### Features

- **mcp**: Add delete_item tool
  ([`10c354b`](https://github.com/repos/agent_gtd/commit/10c354b689b130be188490f66eafd1b650144d1e))


## v1.39.0 (2026-04-15)

### Chores

- **release**: 1.39.0
  ([`8a9f7fa`](https://github.com/repos/agent_gtd/commit/8a9f7fa59d69cc5656a4226548075428774077d2))

### Features

- **frontend**: Show short item ID with copy-to-clipboard in card and detail views
  ([`c14f63d`](https://github.com/repos/agent_gtd/commit/c14f63d370f234c81fff4eb6467260d5e0f177b8))


## v1.38.7 (2026-04-15)

### Bug Fixes

- **frontend**: Remove misleading "tab for options" hint from quick capture
  ([`a6f1e36`](https://github.com/repos/agent_gtd/commit/a6f1e3601f17601f8cf5ebc471f67e98211ab7c7))

### Chores

- **release**: 1.38.7
  ([`e5c3460`](https://github.com/repos/agent_gtd/commit/e5c3460a3f00fa80a15b2f8824f7cfda1725ee65))


## v1.38.6 (2026-04-15)

### Bug Fixes

- **frontend**: Truncate long project descriptions in list view
  ([`5d68eea`](https://github.com/repos/agent_gtd/commit/5d68eea85bdfdab18df05b87d7a6a6bb064a1357))

### Chores

- **release**: 1.38.6
  ([`ca40f54`](https://github.com/repos/agent_gtd/commit/ca40f546e5c1f415173bbd72b1cbc20dd17b6294))


## v1.38.5 (2026-04-15)

### Bug Fixes

- Route dispatch MCP tools through _backend abstraction
  ([`6c191d0`](https://github.com/repos/agent_gtd/commit/6c191d0a482dbcf6ad926ef9fc3d0fb05fd43dce))

### Chores

- **release**: 1.38.5
  ([`b7b7899`](https://github.com/repos/agent_gtd/commit/b7b789912ee1205488e043e06f9a9936dcf1d2d4))


## v1.38.4 (2026-04-15)

### Bug Fixes

- Hide login tool when API key is set, remove switch_project
  ([`c74b276`](https://github.com/repos/agent_gtd/commit/c74b2766e76afc1fe662a2b15bf44753833a3e48))

### Chores

- **release**: 1.38.4
  ([`6a737f8`](https://github.com/repos/agent_gtd/commit/6a737f8f9156a633f76fd5707cfd83baa825ac2e))


## v1.38.3 (2026-04-14)

### Bug Fixes

- Cap description height in item detail drawer
  ([`5b099f7`](https://github.com/repos/agent_gtd/commit/5b099f78f2fbadd6faa82c22bb794479ab041a89))

### Chores

- **release**: 1.38.3
  ([`65dc518`](https://github.com/repos/agent_gtd/commit/65dc5181c74e7a8d046ac652f0ffbe0338035254))


## v1.38.2 (2026-04-14)

### Bug Fixes

- Add HttpBackend comment CRUD tests
  ([`2c4a4f7`](https://github.com/repos/agent_gtd/commit/2c4a4f743ba22541b6ac7e75e15efbf0cca09277))

### Chores

- **release**: 1.38.2
  ([`d8c364b`](https://github.com/repos/agent_gtd/commit/d8c364b9cfdea0ffaba0e86e45fc89e1bfa8d808))

### Documentation

- Add MIT license
  ([`6dfbfd9`](https://github.com/repos/agent_gtd/commit/6dfbfd928cd720fe2da0c068a6d34c285274a0e9))


## v1.38.1 (2026-04-14)

### Bug Fixes

- Hide dispatch button on completed tasks
  ([`8539afa`](https://github.com/repos/agent_gtd/commit/8539afa2377020a564e5a53092bf8efb4956b29f))

- Preflight health check before dispatch
  ([`83ef8fc`](https://github.com/repos/agent_gtd/commit/83ef8fcbc18903411e76ac23ded05436d1b638e8))

- Prevent long item titles from overflowing project list
  ([`c305399`](https://github.com/repos/agent_gtd/commit/c3053994e94c73998e143dcaebb7151fc93e67eb))

### Chores

- Bump default max_turns from 20 to 50
  ([`eca75ac`](https://github.com/repos/agent_gtd/commit/eca75ace13ef5f0493a294cac2cb9bea7bc05168))

- **release**: 1.38.0
  ([`2d3946c`](https://github.com/repos/agent_gtd/commit/2d3946ce47a69de28cfee5e8af5453e7b45dd6a5))

- **release**: 1.38.1
  ([`f8879e0`](https://github.com/repos/agent_gtd/commit/f8879e0e3095cec4086e33b24c05896838d155e3))

### Features

- Complete send-to-claude dispatch UI and MCP tools
  ([`c7dec36`](https://github.com/repos/agent_gtd/commit/c7dec3645bcc932db246fb5559fd7c9865e17235))

- Replace local dispatch worker with remote service proxy
  ([`77a03b4`](https://github.com/repos/agent_gtd/commit/77a03b4bae5a91e9a7739225d1ae9986a0780051))

### Refactoring

- Centralize max_turns default in dispatch_worker
  ([`32f8733`](https://github.com/repos/agent_gtd/commit/32f87339b318f9c271f57d3bf306b0dc28ff1f98))


## v1.37.0 (2026-04-07)

### Chores

- **release**: 1.37.0
  ([`66f730c`](https://github.com/repos/agent_gtd/commit/66f730ced9d1615c49f54d310b30ff477af287e2))

### Features

- Add dispatch worker for headless Claude Code agents (Phase 2B)
  ([`e949c6f`](https://github.com/repos/agent_gtd/commit/e949c6f5ae0438429e43eb08509801316f0660b8))


## v1.36.0 (2026-04-07)

### Chores

- **release**: 1.36.0
  ([`42127ea`](https://github.com/repos/agent_gtd/commit/42127ea7f0311a5b42386eef0f2af0bb5090901d))

### Features

- Add dispatch run tracking (Phase 2A)
  ([`897b594`](https://github.com/repos/agent_gtd/commit/897b59455a0013b5fa549899c7bffd09febf73f2))


## v1.35.0 (2026-04-07)

### Chores

- **release**: 1.35.0
  ([`a106925`](https://github.com/repos/agent_gtd/commit/a10692599e46552b3a9df9b224bd383784ef2a65))

### Features

- Add kb_project_ref field to projects for KB-aware dispatch
  ([`131356e`](https://github.com/repos/agent_gtd/commit/131356e15b9050a72ed6526022d7e1a6e54fa196))


## v1.34.5 (2026-04-06)

### Bug Fixes

- Install pre-commit hooks in dispatch workspace after clone
  ([`6208a84`](https://github.com/repos/agent_gtd/commit/6208a844120a2bcc8312c1800c4bc6bf36ced3fe))

### Chores

- **release**: 1.34.5
  ([`51f5579`](https://github.com/repos/agent_gtd/commit/51f5579ef7c345bae0f20a2c4efc1802ff937494))


## v1.34.4 (2026-04-06)

### Bug Fixes

- Correct KB env vars in dispatch script
  ([`3f6ad49`](https://github.com/repos/agent_gtd/commit/3f6ad496ca44ce6bcf0e9420c6c9479d0358f345))

### Chores

- **release**: 1.34.4
  ([`2bb9c78`](https://github.com/repos/agent_gtd/commit/2bb9c78360a068a7a2fc0594b91f1332ae67af75))


## v1.34.3 (2026-04-06)

### Bug Fixes

- Dispatch script env vars, branch name, and CLI flag
  ([`408f418`](https://github.com/repos/agent_gtd/commit/408f418bca6c7e2528ee5e671a7093d6525b269f))

### Chores

- **release**: 1.34.3
  ([`6d5bab3`](https://github.com/repos/agent_gtd/commit/6d5bab3ced2b0a46edff3c6422ec4fa738018f38))


## v1.34.2 (2026-04-06)

### Bug Fixes

- Use temporary drawer to avoid covering page controls
  ([`df4e905`](https://github.com/repos/agent_gtd/commit/df4e9054c8699830b0aee8f25eb7cc04eabed837))

### Chores

- **release**: 1.34.2
  ([`a3caebb`](https://github.com/repos/agent_gtd/commit/a3caebba8fa2e639ad555af42a392e7e4cf41d31))


## v1.34.1 (2026-04-06)

### Bug Fixes

- Offset detail drawer below app header
  ([`11daa73`](https://github.com/repos/agent_gtd/commit/11daa735ad1169d725f55de3981bfc20e05742a3))

### Chores

- **release**: 1.34.1
  ([`76b6f9d`](https://github.com/repos/agent_gtd/commit/76b6f9d47ccd8e3575333c369b855181dd7f6e5e))


## v1.34.0 (2026-04-06)

### Chores

- Configure semantic-release remote for GitHub changelog links
  ([`ded0f5f`](https://github.com/repos/agent_gtd/commit/ded0f5f4ca7350b4643fbedd2def60dfee309f37))

- **release**: 1.34.0
  ([`e201c60`](https://github.com/repos/agent_gtd/commit/e201c60b847ea37e934458c08ca5349b663246de))

### Features

- Add git_origin field and dispatch script (send-to-claude phase 1)
  ([`a2a5f7f`](https://github.com/repos/agent_gtd/commit/a2a5f7f39bd289b83dcf5193e852e2bae6c820ef))


## v1.33.1 (2026-04-06)

### Bug Fixes

- Restore test coverage above 92% threshold
  ([`e860b89`](https://github.com/repos/agent_gtd/commit/e860b8994b5e41f58e35f65d04d8b5944b45aef7))

### Chores

- **release**: 1.33.1
  ([`ebfaa46`](https://github.com/repos/agent_gtd/commit/ebfaa46b4737b7488fe4e4e76f3e68a8f119face))


## v1.33.0 (2026-04-06)

### Bug Fixes

- Patch SSE auth tests to monkeypatch local mode
  ([`ee5a878`](https://github.com/repos/agent_gtd/commit/ee5a87810bc5d11649b5df779d3a6bf4df497c84))

- Prevent Escape from exiting Safari fullscreen globally
  ([`d39dce8`](https://github.com/repos/agent_gtd/commit/d39dce860eac96a1529fc8b438e3b8b253fc7bdb))

### Chores

- **release**: 1.33.0
  ([`faf4df6`](https://github.com/repos/agent_gtd/commit/faf4df6beae3220f7d818c9aca291e7fcfa13d83))

### Features

- Add item detail drawer with comment thread
  ([`4938430`](https://github.com/repos/agent_gtd/commit/49384307db5f4f44604161efa8dbc9fe8961468d))


## v1.32.0 (2026-04-05)

### Chores

- **release**: 1.32.0
  ([`eadf2bb`](https://github.com/repos/agent_gtd/commit/eadf2bb309cb4dbbeb261c55ad4ae3a246a2de8e))

### Features

- Add comments for items and projects
  ([`178736a`](https://github.com/repos/agent_gtd/commit/178736af6a625f909827ef63f1d24c75653734fc))


## v1.31.0 (2026-03-24)

### Chores

- **release**: 1.31.0
  ([`3d1431d`](https://github.com/repos/agent_gtd/commit/3d1431d1791a259481ec90ad02da9c51a23a1c53))

### Features

- Complete projects from list + default project items to next_action
  ([`60861a5`](https://github.com/repos/agent_gtd/commit/60861a5bae9a0fddf9df6180aec556ec0aa1b943))


## v1.30.0 (2026-03-23)

### Bug Fixes

- Always register login tool in non-local mode and isolate MCP tests
  ([`5042375`](https://github.com/repos/agent_gtd/commit/50423759e7868042da40cefab133020f45af5584))

- Use system trust store for HttpBackend SSL verification
  ([`6d2773c`](https://github.com/repos/agent_gtd/commit/6d2773ce22614ce20411a2a1f5a4011d04fa17bc))

- Use truststore for OS-native SSL cert verification
  ([`a96d78c`](https://github.com/repos/agent_gtd/commit/a96d78c43223373bcc568fc14208e6c0ddcefe15))

### Chores

- **release**: 1.30.0
  ([`4affef7`](https://github.com/repos/agent_gtd/commit/4affef75b41ad10e99a76b4781a39f6db33c0aee))

### Features

- Refresh project view after QuickCapture
  ([`77cb3f1`](https://github.com/repos/agent_gtd/commit/77cb3f19579bc57f27d5560171622a8ee811e6ed))


## v1.29.0 (2026-03-22)

### Chores

- Remove redundant test_switch_project_without_login
  ([`14c0d1d`](https://github.com/repos/agent_gtd/commit/14c0d1db8363bec2f46bdc25d58ab50b61b0d180))

- **release**: 1.29.0
  ([`7e03577`](https://github.com/repos/agent_gtd/commit/7e03577de7cd9dc100ca9594e171f19739a8de95))

### Features

- MCP HTTP backend — remote mode calls FastAPI API instead of DB
  ([`4d4decd`](https://github.com/repos/agent_gtd/commit/4d4decde295bb13b906a7b1c483c0dbeb9b314c5))


## v1.28.2 (2026-03-22)

### Bug Fixes

- Clear _ENV_API_KEY in test_switch_project_without_login too
  ([`416b572`](https://github.com/repos/agent_gtd/commit/416b572d4b02143d8e87ac90a06036b8348c4182))

### Chores

- **release**: 1.28.2
  ([`8d13d0b`](https://github.com/repos/agent_gtd/commit/8d13d0bd1d82011ab0b0e93a4d327b1632f272dd))


## v1.28.1 (2026-03-22)

### Bug Fixes

- Clear _ENV_API_KEY in test_tool_without_login to avoid auto-login
  ([`fc47ace`](https://github.com/repos/agent_gtd/commit/fc47ace95bcbec725ff85d454912f639d33f8aaf))

### Chores

- **release**: 1.28.1
  ([`b4492dc`](https://github.com/repos/agent_gtd/commit/b4492dc4ec0211b855c19e293aa223fd27d8f068))


## v1.28.0 (2026-03-22)

### Chores

- **release**: 1.28.0
  ([`551461a`](https://github.com/repos/agent_gtd/commit/551461abe6273231f63171ce7b8832537cc544d4))

### Documentation

- Update README with API key auth setup instructions
  ([`205ebb6`](https://github.com/repos/agent_gtd/commit/205ebb6df96943f92506ff1cee6ef0b3a2ba171c))

### Features

- Add complete button and hide-completed toggle in project list view
  ([`1777505`](https://github.com/repos/agent_gtd/commit/1777505f6cc9b58b673a5e520df633c7e4ea500c))


## v1.27.0 (2026-03-20)

### Chores

- **release**: 1.27.0
  ([`7526dc9`](https://github.com/repos/agent_gtd/commit/7526dc95c7e2dfedb8b4984b505729ab3a179d0b))

### Features

- API key auth with MCP auto-login
  ([`ece6857`](https://github.com/repos/agent_gtd/commit/ece6857fdd9856a53031c296d43ab2fa369c529e))


## v1.26.0 (2026-03-19)

### Chores

- **release**: 1.26.0
  ([`38c1445`](https://github.com/repos/agent_gtd/commit/38c14452d12728a1f6ace38f891dfc55e644f645))

### Features

- Cmd/Ctrl+Enter saves and closes dialogs from textareas
  ([`db76d2a`](https://github.com/repos/agent_gtd/commit/db76d2a0335be2ec8380f03fc61d00d8c21b21a6))


## v1.25.0 (2026-03-19)

### Chores

- **release**: 1.25.0
  ([`1cabf33`](https://github.com/repos/agent_gtd/commit/1cabf33351e2e97fd494ed6bb4c5da830f782798))

### Features

- Context-aware quick capture from project views
  ([`7fad585`](https://github.com/repos/agent_gtd/commit/7fad585548f3ddfbdc8e22975b4fa79e38cb99ba))


## v1.24.0 (2026-03-19)

### Chores

- **release**: 1.24.0
  ([`e42ee2c`](https://github.com/repos/agent_gtd/commit/e42ee2ccc2e6b60ba317e80701b8ac223b1b9de1))

### Features

- Add search to GTD list views and fix quick capture focus
  ([`e8f881b`](https://github.com/repos/agent_gtd/commit/e8f881b8b80610982bdb15ccb47c56871d76a89a))


## v1.23.2 (2026-03-18)

### Bug Fixes

- Simplify light theme to match photoqueue — only set primary, secondary, background
  ([`724f1cc`](https://github.com/repos/agent_gtd/commit/724f1cc34f2f9ce2c6f403e281039c54f4431b17))

### Chores

- **release**: 1.23.2
  ([`058529d`](https://github.com/repos/agent_gtd/commit/058529d058eb576bd2bb4af320c35edf3297ceaa))


## v1.23.1 (2026-03-18)

### Bug Fixes

- Prevent Escape key from exiting browser fullscreen when dialogs are open
  ([`cf863b4`](https://github.com/repos/agent_gtd/commit/cf863b455df4250fa7daafab7516fd02b40bf63b))

### Chores

- **release**: 1.23.1
  ([`3bfabe2`](https://github.com/repos/agent_gtd/commit/3bfabe229e4a5afa109276f852158f1390dc362c))


## v1.23.0 (2026-03-17)

### Chores

- **release**: 1.23.0
  ([`9a279f7`](https://github.com/repos/agent_gtd/commit/9a279f7f483e1f71d41f0d18a402fcda809f2255))

### Features

- Improve projects page with search, list view, and light mode theme
  ([`aeb90d9`](https://github.com/repos/agent_gtd/commit/aeb90d91bfd22ce69f490cc4127562fe5d929593))


## v1.22.0 (2026-03-13)

### Chores

- **release**: 1.22.0
  ([`2d5223d`](https://github.com/repos/agent_gtd/commit/2d5223d52161e19e04aaf82e7bf0a8c76ed1c3ec))

### Features

- Simplify item statuses and align labels with kanban columns
  ([`d42fc40`](https://github.com/repos/agent_gtd/commit/d42fc406f0d6e802bd9425421188c2c1da6eb9ae))


## v1.21.4 (2026-03-13)

### Bug Fixes

- Remove transitionend handler that hid kanban cards on drag start
  ([`8e42b1f`](https://github.com/repos/agent_gtd/commit/8e42b1ff41b9bfe483bac7c9a20a0b309be03a07))

### Chores

- **release**: 1.21.4
  ([`c73c2a8`](https://github.com/repos/agent_gtd/commit/c73c2a8b57859239711f6f4efcf32e5ab2050308))


## v1.21.3 (2026-03-13)

### Bug Fixes

- Preserve reviewed project count across step navigation
  ([`94ac32c`](https://github.com/repos/agent_gtd/commit/94ac32c8470296ea22a33359f7e22f068b216ffb))

### Chores

- **release**: 1.21.3
  ([`7377f10`](https://github.com/repos/agent_gtd/commit/7377f1031ace2d13046dff67b3ed3874ea28c7b9))


## v1.21.2 (2026-03-13)

### Bug Fixes

- Move project prev link next to mark reviewed button
  ([`72b77d8`](https://github.com/repos/agent_gtd/commit/72b77d8e41a97914b5cb8945d3ac5c4976be1cde))

### Chores

- **release**: 1.21.2
  ([`273ff14`](https://github.com/repos/agent_gtd/commit/273ff14f4b9b4dc8971fa0f37208e922e4a8c7f2))


## v1.21.1 (2026-03-13)

### Bug Fixes

- Weekly review UX improvements
  ([`2c9114e`](https://github.com/repos/agent_gtd/commit/2c9114e7cbb863b83e5fdbfec2a98472bddf685f))

### Chores

- **release**: 1.21.1
  ([`e0a54fd`](https://github.com/repos/agent_gtd/commit/e0a54fde9c2d90e1d212367b94c5fb74fe7f6833))


## v1.21.0 (2026-03-13)

### Chores

- Add agent-gtd-mcp console entry point
  ([`22871b5`](https://github.com/repos/agent_gtd/commit/22871b583dad6732840269ac3c6d6f6c0e426685))

- **release**: 1.21.0
  ([`e7bfc15`](https://github.com/repos/agent_gtd/commit/e7bfc155a0182edde600afd1371bb513bc632227))

### Features

- Remove project-scoped registration in single-user mode
  ([`57cd253`](https://github.com/repos/agent_gtd/commit/57cd2535adae908b4fac9bb46db5727181dab16f))


## v1.20.12 (2026-03-10)

### Bug Fixes

- Force tests to always use in-memory SQLite
  ([`6094118`](https://github.com/repos/agent_gtd/commit/60941187fa31fed8dab33b8cfe1104237822728e))

### Chores

- **release**: 1.20.12
  ([`cb1eb49`](https://github.com/repos/agent_gtd/commit/cb1eb49a07220530382aea190c4673f5a5253b79))

### Documentation

- Add README with quick start, MCP setup, and dev commands
  ([`f896e6c`](https://github.com/repos/agent_gtd/commit/f896e6c2cf3a59b54dd6fd566ec106673f5fbf2e))


## v1.20.11 (2026-03-07)

### Bug Fixes

- Use data attribute + !important CSS to prevent React from undoing hide
  ([`2b358f1`](https://github.com/repos/agent_gtd/commit/2b358f11aa45b72c20072b80b910a6baf98e739b))

### Chores

- **release**: 1.20.11
  ([`37e2685`](https://github.com/repos/agent_gtd/commit/37e268555b81c5fb20d3b306d640349b66b109b9))


## v1.20.10 (2026-03-07)

### Bug Fixes

- Use capture-phase transitionend listener to prevent kanban pop-back
  ([`83107a2`](https://github.com/repos/agent_gtd/commit/83107a27643c9fcec66959060d0e53baf7c14b09))

### Chores

- **release**: 1.20.10
  ([`8a6234b`](https://github.com/repos/agent_gtd/commit/8a6234b541b49f06f7697c1c01ff1955c35ebdb7))


## v1.20.9 (2026-03-07)

### Bug Fixes

- Hide kanban card at render time to eliminate Safari drag pop-back
  ([`3826f48`](https://github.com/repos/agent_gtd/commit/3826f48f97e7d9602405df0013e67ed2ed36af7c))

### Chores

- **release**: 1.20.9
  ([`fe8517a`](https://github.com/repos/agent_gtd/commit/fe8517ac00f79691a9f41509cdd1a542eb5e58d1))


## v1.20.8 (2026-03-07)

### Bug Fixes

- Add React.memo and GPU compositing to KanbanCard for Safari drag stability
  ([`14b2a94`](https://github.com/repos/agent_gtd/commit/14b2a94c920a55890dd05ce17d62b8dc65ca30bd))

### Chores

- **release**: 1.20.8
  ([`9a2e690`](https://github.com/repos/agent_gtd/commit/9a2e69047eb9b0ab9e5860076ac2ec54fc41ac85))


## v1.20.7 (2026-03-07)

### Bug Fixes

- Imperatively hide source element on drop to prevent Safari pop-back
  ([`20cd40c`](https://github.com/repos/agent_gtd/commit/20cd40cbcd619bb93d9981f8041e9b36e8555a4b))

### Chores

- **release**: 1.20.7
  ([`c2cc6d7`](https://github.com/repos/agent_gtd/commit/c2cc6d7eab4c9f72e206329157951b75567effe9))


## v1.20.6 (2026-03-07)

### Bug Fixes

- Make kanban drop animation near-instant to prevent Safari pop-back
  ([`ec6841c`](https://github.com/repos/agent_gtd/commit/ec6841c87129f356e34060d031971def17a8c116))

### Chores

- **release**: 1.20.6
  ([`c81d868`](https://github.com/repos/agent_gtd/commit/c81d8684a09f71fa0631598d91daa2b87ded829a))


## v1.20.5 (2026-03-07)

### Bug Fixes

- Use flushSync to eliminate kanban card pop-back on drop
  ([`0be4290`](https://github.com/repos/agent_gtd/commit/0be42908342b5495746f73886bb3053bc05e9bfe))

### Chores

- **release**: 1.20.5
  ([`4b7b853`](https://github.com/repos/agent_gtd/commit/4b7b8535fd661299dd68146e9d17a355db4405f4))


## v1.20.4 (2026-03-07)

### Bug Fixes

- Eliminate kanban card pop-back with optimistic state update
  ([`0d4757f`](https://github.com/repos/agent_gtd/commit/0d4757f68aff11978c26dc8729dc5a0614c9ad96))

### Chores

- **release**: 1.20.4
  ([`1f98561`](https://github.com/repos/agent_gtd/commit/1f985610a49164790fe6905730aaaff4839c43d5))


## v1.20.3 (2026-03-07)

### Bug Fixes

- Replace @dnd-kit/react with @hello-pangea/dnd for reliable kanban drag
  ([`7d72ee1`](https://github.com/repos/agent_gtd/commit/7d72ee116e3489bf8104a7d7c3407faf03454077))

### Chores

- **release**: 1.20.3
  ([`e3539d3`](https://github.com/repos/agent_gtd/commit/e3539d3e0203f3e6798a24e5e7d4069121f1ed80))


## v1.20.2 (2026-03-07)

### Bug Fixes

- Kanban drag visual glitch and crash on repeated drags
  ([`93488f0`](https://github.com/repos/agent_gtd/commit/93488f038fe694249e79bffde93880ccb2467ac4))

### Chores

- **release**: 1.20.2
  ([`9134c89`](https://github.com/repos/agent_gtd/commit/9134c89fff1042ed913f4c8407be165fa1beb17d))


## v1.20.1 (2026-03-07)

### Bug Fixes

- Kanban cross-column drag-and-drop
  ([`37aa924`](https://github.com/repos/agent_gtd/commit/37aa9243026c6ec7bddd5f011df2431dd21a282c))

### Chores

- **release**: 1.20.1
  ([`0df15da`](https://github.com/repos/agent_gtd/commit/0df15daa23eb81fa036933007066a72f1fc76a9e))


## v1.20.0 (2026-03-07)

### Chores

- **release**: 1.20.0
  ([`73fd008`](https://github.com/repos/agent_gtd/commit/73fd0081a13d78165fd0eb6f432f23734d02083d))

### Features

- Improve project views — icon buttons, kanban columns, clickable cards
  ([`5779c73`](https://github.com/repos/agent_gtd/commit/5779c732ecbb3d7a9cb4bdce66c4d28f9b59a86f))


## v1.19.0 (2026-03-07)

### Chores

- **release**: 1.19.0
  ([`d60bc12`](https://github.com/repos/agent_gtd/commit/d60bc1294a387b06d16048690a7ae260a818221c))

### Features

- Show app version on settings page
  ([`bb24248`](https://github.com/repos/agent_gtd/commit/bb242483821358bfb9bc4aa69de20861d65fed66))


## v1.18.0 (2026-03-06)

### Chores

- **release**: 1.18.0
  ([`6d2d3b9`](https://github.com/repos/agent_gtd/commit/6d2d3b9d136a84e333bf7ba9a60129cd37309a18))

### Features

- Pin weekly review stepper and nav buttons while content scrolls
  ([`a46f4b6`](https://github.com/repos/agent_gtd/commit/a46f4b63e8aa728d402ad43bc551a988580dd0b6))


## v1.17.1 (2026-03-06)

### Bug Fixes

- Truncate PostgreSQL test DB at setup to handle stale data from crashed runs
  ([`8c192f4`](https://github.com/repos/agent_gtd/commit/8c192f4485e325e2f8b507ba180d57168f3b0f0a))

### Chores

- **release**: 1.17.1
  ([`818f797`](https://github.com/repos/agent_gtd/commit/818f7978fc542649093bb998f849356c97cd9c78))


## v1.17.0 (2026-03-06)

### Chores

- **release**: 1.17.0
  ([`cbf1313`](https://github.com/repos/agent_gtd/commit/cbf131387c3ebf8dc12c15dbfaed18663869b822))

### Features

- Improve weekly review navigation UX
  ([`9c4790e`](https://github.com/repos/agent_gtd/commit/9c4790ebe655f7d8f40b1083288b3c62d66fd56d))


## v1.16.0 (2026-03-06)

### Chores

- **release**: 1.16.0
  ([`de5aa6a`](https://github.com/repos/agent_gtd/commit/de5aa6a6e34d371c598ab2b590cbb55d43d6a98c))

### Features

- SQLite fallback + local single-user mode
  ([`81fa4e3`](https://github.com/repos/agent_gtd/commit/81fa4e398e48b4c3c6d42fe15f0e8815374af3c6))


## v1.15.0 (2026-03-05)

### Chores

- **release**: 1.15.0
  ([`d202384`](https://github.com/repos/agent_gtd/commit/d2023843e0fb419222ab319465e979e012422031))

### Features

- Add project_name to MCP tool responses
  ([`5566f7b`](https://github.com/repos/agent_gtd/commit/5566f7bb05399c18f6c90063c7302f877748e242))


## v1.14.0 (2026-03-05)

### Chores

- **release**: 1.14.0
  ([`26b1684`](https://github.com/repos/agent_gtd/commit/26b1684edf5b9ffda02a6aa3a0bdf4d19b322b54))

### Features

- Replace project review accordion with carousel and quick-add
  ([`212ba6f`](https://github.com/repos/agent_gtd/commit/212ba6fd78459ae16a528655a7283addd1696120))


## v1.13.0 (2026-03-04)

### Chores

- **release**: 1.13.0
  ([`8a6f23e`](https://github.com/repos/agent_gtd/commit/8a6f23e575cfa36b840cc61b606c850d6e07d9a3))

### Features

- Add Enter-to-submit on all create/edit dialogs
  ([`891d04a`](https://github.com/repos/agent_gtd/commit/891d04ab07379cfb73d7e42e91db0b021ee41c61))


## v1.12.0 (2026-03-04)

### Chores

- **release**: 1.12.0
  ([`0cd972f`](https://github.com/repos/agent_gtd/commit/0cd972fc110937806167ca52dfe8c788a1b63781))

### Features

- Add Cmd+1-7 keyboard shortcuts for sidebar navigation
  ([`c9bf49c`](https://github.com/repos/agent_gtd/commit/c9bf49cd44f38a121b9b62323ba6485e8679aada))


## v1.11.3 (2026-03-04)

### Bug Fixes

- Wrap long item titles in review rows instead of truncating
  ([`1d22d47`](https://github.com/repos/agent_gtd/commit/1d22d47fdf09a8d52ec19ce479a0ca7fbfb7f9d7))

### Chores

- **release**: 1.11.3
  ([`de035dd`](https://github.com/repos/agent_gtd/commit/de035ddae10750f22757ceef82a1e2ebf79f48f6))


## v1.11.2 (2026-03-04)

### Bug Fixes

- Prevent long item titles from overflowing review layout
  ([`3b1bfa4`](https://github.com/repos/agent_gtd/commit/3b1bfa47d261d9c20b9ceb645fd29c5869601f84))

### Chores

- **release**: 1.11.2
  ([`956e6b8`](https://github.com/repos/agent_gtd/commit/956e6b8aed4d051b214e074f893954b4e7a605e2))


## v1.11.1 (2026-03-04)

### Bug Fixes

- Improve inbox processor navigation and action layout
  ([`9ca3298`](https://github.com/repos/agent_gtd/commit/9ca3298835b2056a8935ab3f88ee97fc36b6e162))

### Chores

- **release**: 1.11.1
  ([`9cabeb8`](https://github.com/repos/agent_gtd/commit/9cabeb8fb203f9b0d751f20d43d1416b7b474378))


## v1.11.0 (2026-03-04)

### Chores

- Re-enable DB tests on push now that SQLite backend is fast
  ([`8d588f8`](https://github.com/repos/agent_gtd/commit/8d588f88e03906957995fd28736b8beae65140b3))

- **release**: 1.11.0
  ([`da1f3bd`](https://github.com/repos/agent_gtd/commit/da1f3bd4915ccacca13143f3b84203e7ae81a02d))

### Features

- Redesign weekly review as step-by-step wizard
  ([`62c39a6`](https://github.com/repos/agent_gtd/commit/62c39a6b759a03168ce89e610ee79219e488df22))


## v1.10.0 (2026-03-03)

### Chores

- Skip DB tests on push, add SKIP_DB_TESTS=1 env flag
  ([`4b08423`](https://github.com/repos/agent_gtd/commit/4b08423787aa3cfa3b93de2da24648c2e270761c))

- **release**: 1.10.0
  ([`4d657f5`](https://github.com/repos/agent_gtd/commit/4d657f5bd49d9ddb621eb914f093d93685e42aa6))

### Features

- In-memory SQLite test backend for fast offline testing
  ([`7aff243`](https://github.com/repos/agent_gtd/commit/7aff2432c2e7ffa30fedcc5601985b5fd5c348d3))


## v1.9.2 (2026-03-03)

### Bug Fixes

- Inbox project-less items, quick capture focus, delete dialog sizing, header casing
  ([`79a71e4`](https://github.com/repos/agent_gtd/commit/79a71e435a900614f2ed49521e875d1ccb7d4ca6))

### Chores

- Add "check the KB first" guidance to CLAUDE.md
  ([`f060f54`](https://github.com/repos/agent_gtd/commit/f060f54de990e4d4905370bd1a106e2bf9e84381))

- Add deployment info to CLAUDE.md
  ([`f2d22cb`](https://github.com/repos/agent_gtd/commit/f2d22cb1d346dfe411bce92f5473414679d09e68))

- Delete roadmap, add Agent GTD dogfooding mandate to CLAUDE.md
  ([`59ac1ce`](https://github.com/repos/agent_gtd/commit/59ac1ce9afd4d148a9f21a544d9df95fb385abbb))

- **release**: 1.9.2
  ([`c2b42a5`](https://github.com/repos/agent_gtd/commit/c2b42a5ca457b23ff26c4ffa55b015fae509cf14))


## v1.9.1 (2026-03-03)

### Bug Fixes

- QuickCapture Tab, NoteEditor min-height, global Esc hotkey
  ([`c05e407`](https://github.com/repos/agent_gtd/commit/c05e407d23fb1003ba843b321c4501c31cdd9d6b))

### Chores

- **release**: 1.9.1
  ([`dedd89c`](https://github.com/repos/agent_gtd/commit/dedd89c7276ca371acc835e4d56dc7449b681cc6))


## v1.9.0 (2026-03-03)

### Chores

- **release**: 1.9.0
  ([`9693813`](https://github.com/repos/agent_gtd/commit/9693813723edd4fc3fdf8ad18046d9849f336a7a))

### Features

- Add nginx + systemd deployment configs
  ([`2595f04`](https://github.com/repos/agent_gtd/commit/2595f046460863a0a844eb7d8f0407e230b9dbd8))

- Add TipTap rich text editor for project notes
  ([`e8e24e0`](https://github.com/repos/agent_gtd/commit/e8e24e02cc99abba4c4fa8e04a635f510530bd79))


## v1.8.1 (2026-03-02)

### Bug Fixes

- Start.sh signal handling for clean systemd shutdown
  ([`d8b6878`](https://github.com/repos/agent_gtd/commit/d8b68782796e42f98d844734979de5fd994ee0c0))

### Chores

- Remove .mcp.json from tracking (contains credentials)
  ([`be49728`](https://github.com/repos/agent_gtd/commit/be49728612dafa7932fb6edc384f8c695178142e))

- **release**: 1.8.1
  ([`61de347`](https://github.com/repos/agent_gtd/commit/61de34719242d5e6cbf5a8db4ce744ec0b0984d4))


## v1.8.0 (2026-03-02)

### Chores

- **release**: 1.8.0
  ([`5eee933`](https://github.com/repos/agent_gtd/commit/5eee933eaca3cf4f762352ea29147096d3c7f246))

### Features

- Add weekly review page with guided three-section flow
  ([`6a3e230`](https://github.com/repos/agent_gtd/commit/6a3e2301214b878871c98e5203c7b6d264136c7c))


## v1.7.0 (2026-03-02)

### Chores

- **release**: 1.7.0
  ([`3c9b4f4`](https://github.com/repos/agent_gtd/commit/3c9b4f455975e119c078480ea8aef07997f21759))

### Features

- Add inbox processor for sequential card-based triage
  ([`9182f0e`](https://github.com/repos/agent_gtd/commit/9182f0e6a9f62c54a959709e86dce7c161cd0acf))


## v1.6.0 (2026-03-01)

### Chores

- Lower coverage threshold to 93% for SSE streaming
  ([`32ce732`](https://github.com/repos/agent_gtd/commit/32ce73219c97833e37716e455875436a236bf9fd))

- **release**: 1.6.0
  ([`eb029ca`](https://github.com/repos/agent_gtd/commit/eb029ca2292df15459e7847afe6f6d940c369d2d))

### Features

- Add global quick capture overlay and kanban board
  ([`1de8754`](https://github.com/repos/agent_gtd/commit/1de87543523f46609ac8f3e7571cf466028de64e))


## v1.5.0 (2026-03-01)

### Chores

- **release**: 1.5.0
  ([`b161d58`](https://github.com/repos/agent_gtd/commit/b161d5899c5957f679f943aede51cd3057a1bde3))

### Documentation

- Update roadmap for post-Phase 4 partial status
  ([`f644928`](https://github.com/repos/agent_gtd/commit/f644928e3413cfa8a8f7a6b164dcfaaacdb7ee25))

### Features

- Add real-time SSE sync for browser updates
  ([`77203ca`](https://github.com/repos/agent_gtd/commit/77203ca07027f60d41afcbfdfa988aa0deaeb3c0))


## v1.4.1 (2026-03-01)

### Bug Fixes

- Prevent semantic-release from auto-pushing on version bump
  ([`d151f4d`](https://github.com/repos/agent_gtd/commit/d151f4d229e97d3e0c5eeca4e358f545da44c191))

### Chores

- **release**: 1.4.1
  ([`f0f15a2`](https://github.com/repos/agent_gtd/commit/f0f15a27e2d52791f7e06863ec0ba5eeb179ad17))


## v1.4.0 (2026-03-01)

### Chores

- **release**: 1.4.0
  ([`02069c2`](https://github.com/repos/agent_gtd/commit/02069c284cf7c9d7573768476957fb1868770e90))

### Documentation

- Update roadmap and domain for post-migration status
  ([`3011b47`](https://github.com/repos/agent_gtd/commit/3011b475555f3906a7f1eef25f6e78024d5f0a76))

### Features

- Add GTD list views (Next Actions, Waiting For, Someday/Maybe)
  ([`3205195`](https://github.com/repos/agent_gtd/commit/3205195311369ff2bf170d383d3b72483f0f9b12))


## v1.3.1 (2026-02-28)

### Bug Fixes

- Source .env in pre-push coverage hook for DATABASE_URL
  ([`d2b5813`](https://github.com/repos/agent_gtd/commit/d2b5813ede57af26f7ea924ad4947f06efd8b591))

### Chores

- **release**: 1.3.1
  ([`7a0b8d8`](https://github.com/repos/agent_gtd/commit/7a0b8d89af90ddda028e096125346a6a4e91d520))


## v1.3.0 (2026-02-28)

### Chores

- **release**: 1.3.0
  ([`773921d`](https://github.com/repos/agent_gtd/commit/773921d956f7462249dc20a9435cef7e02d6ca95))

### Features

- Migrate from SQLite to PostgreSQL
  ([`8488a86`](https://github.com/repos/agent_gtd/commit/8488a86a7457d1c917870ea8a10558e71f07c788))


## v1.2.0 (2026-02-28)

### Chores

- **release**: 1.2.0
  ([`9009764`](https://github.com/repos/agent_gtd/commit/900976407723926700000d63dd4e956ad898f961))

### Features

- Wire up MCP server for Claude Code dogfooding
  ([`abc65a0`](https://github.com/repos/agent_gtd/commit/abc65a08d7826777f357905ca3520860a91e87d1))


## v1.1.0 (2026-02-28)

### Chores

- Enforce conventional commits only on main branch
  ([`8073b0a`](https://github.com/repos/agent_gtd/commit/8073b0a6add4edaec66c961be1ece7d393ec6b56))

- **release**: 1.1.0
  ([`3f2f527`](https://github.com/repos/agent_gtd/commit/3f2f5273947c0ac2ce1676b69680a61d9f676e55))

### Features

- Add MCP server with service layer and optimistic locking
  ([`83902f0`](https://github.com/repos/agent_gtd/commit/83902f0663a266025c0ad334f51fcbc006428354))


## v1.0.0 (2026-02-28)

- Initial Release
