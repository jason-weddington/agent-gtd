"""Shared constants for dispatch configuration and validation."""

# Bounds for dispatch_max_turns (applies to both global settings and project overrides)
MIN_TURNS: int = 10
MAX_TURNS: int = 500

# Bounds for dispatch_timeout_minutes (global settings + project overrides)
MIN_TIMEOUT_MINUTES: int = 5
# The resident rollout manager has been retired (item 7baf77d0), so as an
# upper bound for the MANAGER timeout this 8-hour ceiling is now meaningless:
# it only ever made sense for a long-lived manager that babysat a whole wave,
# and a short-lived per-item reviewer lives for minutes.  It is kept because it
# also bounds the build-run timeout, and lowering it would reject existing
# configured values.
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
# (45 min = 2700 s).  ``run_agent``'s former third fallback is gone — it now
# calls ``config.timeout_seconds_for_mode``.
#
# SIZED FOR A SHORT-LIVED REVIEWER (45 min, the dispatch service's
# ``REVIEW_TIMEOUT_SECONDS``), not the 4-hour resident manager it used to bound.
# The boot migration only seeds the setting when it is absent, so a deployment
# that already stored 240 keeps it until an operator lowers it in Settings.
MANAGER_DEFAULT_TIMEOUT_MINUTES: int = 45
