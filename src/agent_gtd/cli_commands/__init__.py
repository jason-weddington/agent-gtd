"""Per-resource CLI subcommand package for the ``agent-gtd`` CLI.

This package holds one module per resource group (added incrementally by later
items in the CLI-parity wave). Each command module follows a fixed registration
convention so that :func:`register_all` can discover and wire it up without the
top-level :mod:`agent_gtd.cli` needing to know about it.

Registration convention
------------------------
Every command module (e.g. ``cli_commands/item.py``) must:

1. Start with ``from __future__ import annotations`` — this keeps the
   private-generic parameter annotation below from being evaluated at runtime.
2. Define a module-level function::

       def register(subparsers: argparse._SubParsersAction[Any]) -> None:
           ...

   that builds its own subparser(s) via ``subparsers.add_parser(...)``, adds
   arguments, and attaches its handler with
   ``parser.set_defaults(func=handler)`` where ``handler`` matches the alias
   :data:`~agent_gtd.cli_commands._shared.CommandHandler` =
   ``Callable[[argparse.Namespace], None]``.

The command handler is dispatched by :mod:`agent_gtd.cli`'s ``main()`` via the
``args.func(args)`` fall-through branch — the handler never has to be named in
``cli.py``'s if/elif chain.

Module naming
-------------
Modules whose names start with ``_`` (such as :mod:`._shared`) are helper
modules, NOT command modules, and are skipped by auto-discovery. Command
modules must therefore use non-underscore names.

Import discipline
-----------------
:func:`register_all` imports NO command (non-underscore) submodule at
package-import time — command discovery happens only inside ``register_all`` at
runtime. This package imports nothing from :mod:`agent_gtd.cli`, so there is no
circular import. (Importing :mod:`._shared` at package-import time for the
convenience re-exports below is permitted, since ``_shared`` is not a command
module.)
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING, Any

from agent_gtd.cli_commands._shared import (
    CommandHandler,
    backend_session,
    emit_json,
    fail,
    load_json_payload,
)

if TYPE_CHECKING:
    import argparse
    from collections.abc import Iterable

__all__ = [
    "CommandHandler",
    "backend_session",
    "emit_json",
    "fail",
    "load_json_payload",
    "register_all",
]


def register_all(
    subparsers: argparse._SubParsersAction[Any],
    modules: Iterable[Any] | None = None,
) -> None:
    """Register every per-resource command module on *subparsers*.

    When *modules* is ``None`` (the normal case), command modules are
    auto-discovered: :func:`pkgutil.iter_modules` walks this package, any module
    whose name starts with ``_`` is skipped (so ``_shared`` is never treated as
    a command module), and each remaining module is imported via
    :func:`importlib.import_module` and has its ``register(subparsers)`` called.

    When *modules* is provided, it is iterated directly and each element's
    ``register(subparsers)`` is called. ``Iterable[Any]`` is deliberate so test
    fakes (e.g. ``types.SimpleNamespace`` with a ``register`` attribute) pass
    ``mypy --strict`` without casts.

    A discovered command module that lacks a ``register`` attribute is a
    convention violation and a bug: the ``AttributeError`` from accessing
    ``mod.register`` propagates out of this function (no ``hasattr`` skip).

    Args:
        subparsers: The subparsers action returned by
            ``parser.add_subparsers(...)`` in ``cli.py``.
        modules: Optional explicit iterable of module-like objects to register
            (each must expose a ``register`` callable). When ``None``,
            submodules are auto-discovered.
    """
    if modules is None:
        for mod_info in pkgutil.iter_modules(__path__):
            if mod_info.name.startswith("_"):
                continue
            mod: Any = importlib.import_module(f"{__name__}.{mod_info.name}")
            mod.register(subparsers)
    else:
        for mod in modules:
            mod.register(subparsers)
