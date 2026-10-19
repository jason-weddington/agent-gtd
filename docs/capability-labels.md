# Capability-label routing

Work is only routed to a dispatch host that carries every label the work
requires. The effective requirement is the union of the project's
`required_labels` and the item's `required_labels`; a host's
`capability_labels` are set by the operator (never self-reported).

Everything is manageable from the CLI (and the matching MCP tools).

## Set what a host can do

```bash
agent-gtd set-host-labels <host> camera-data tauri-linux   # replaces the full list
agent-gtd set-host-labels <host> --clear                   # remove all labels
agent-gtd list-dispatch-hosts                              # shows capability_labels
```

`<host>` resolves like `drain-host`: id, exact label, or a unique URL
substring. MCP: `set_dispatch_host_labels(host, labels)`.

## Declare what work needs

```bash
agent-gtd update-project <project_id> --required-label camera-data   # repeatable, replaces the list
agent-gtd update-project <project_id> --clear-required-labels
agent-gtd update-item <item_id> --required-label tauri-linux          # repeatable, replaces the list
agent-gtd update-item <item_id> --clear-required-labels
```

MCP: `update_project(required_labels=[...])` and
`update_item(required_labels=[...])` — `None` leaves the field unchanged and
`[]` clears it.

A drained host is never a candidate, whatever labels it carries; see
`host-drain.md`.
