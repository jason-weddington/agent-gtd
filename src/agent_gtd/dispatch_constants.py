"""Shared constants for dispatch configuration and validation."""

# Bounds for dispatch_max_turns (applies to both global settings and project overrides)
MIN_TURNS: int = 10
MAX_TURNS: int = 500

# Bounds for dispatch_timeout_minutes (global settings + project overrides)
MIN_TIMEOUT_MINUTES: int = 5
# REVISIT when the resident rollout manager is retired: an 8-hour ceiling only
# makes sense for a long-lived manager that babysits a whole wave.  A
# short-lived per-item merge reviewer lives for minutes, so this bound stops
# expressing anything meaningful the moment that lands — it is kept here only
# because lowering it now would reject existing configured values.
MAX_TIMEOUT_MINUTES: int = 480

# AUTHORITATIVE manage-mode timeout.
#
# The manage timeout used to resolve in three independent places that agreed
# only by coincidence: this GTD-side app setting, the dispatch service's
# ``config.MANAGE_TIMEOUT_SECONDS``, and a third fallback inside
# ``dispatch.run_agent``.  There is now exactly one source of truth:
#
#   ``dispatch.manager_default_timeout_minutes`` (app_settings), seeded from and
#   falling back to this constant, is AUTHORITATIVE.  It is resolved by
#   ``dispatch_worker`` and sent on the wire as ``DispatchRequest.timeout_minutes``.
#
# The dispatch service's ``config.MANAGE_TIMEOUT_SECONDS`` is a derived backstop:
# it only applies to a manage dispatch that arrives with no explicit
# ``timeout_minutes`` at all, and it must stay numerically equal to this value
# (240 min = 14400 s).  ``run_agent``'s former third fallback is gone — it now
# calls ``config.timeout_seconds_for_mode``.
MANAGER_DEFAULT_TIMEOUT_MINUTES: int = 240
