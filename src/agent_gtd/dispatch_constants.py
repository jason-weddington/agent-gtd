"""Shared constants for dispatch configuration and validation."""

# Bounds for dispatch_max_turns (applies to both global settings and project overrides)
MIN_TURNS: int = 10
MAX_TURNS: int = 500

# Bounds for dispatch_timeout_minutes (global settings + project overrides)
MIN_TIMEOUT_MINUTES: int = 5
MAX_TIMEOUT_MINUTES: int = 480
