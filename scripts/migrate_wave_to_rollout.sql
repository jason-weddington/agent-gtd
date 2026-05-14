-- Migration: rename wave_run → rollout across the schema
-- Run against the production DB before merging the rename PR.
--
-- Forward (apply):
--   Renames tables, columns, and makes claude_runs.item_id nullable
--   to support manage-mode runs without a placeholder item.
--
-- Rollback (undo):
--   Reverses every rename and restores the NOT NULL constraint.

-- ============================================================
-- FORWARD
-- ============================================================

-- Rename tables
ALTER TABLE autonomous_wave_runs RENAME TO autonomous_rollouts;
ALTER TABLE wave_plans RENAME TO rollout_plans;
ALTER TABLE wave_plan_items RENAME TO rollout_items;
ALTER TABLE wave_events RENAME TO rollout_events;

-- Rename wave_run_id → rollout_id columns on child tables
ALTER TABLE rollout_plans RENAME COLUMN wave_run_id TO rollout_id;
ALTER TABLE rollout_items RENAME COLUMN wave_run_id TO rollout_id;
ALTER TABLE rollout_events RENAME COLUMN wave_run_id TO rollout_id;
ALTER TABLE claude_runs RENAME COLUMN wave_run_id TO rollout_id;

-- Rename item lock column
ALTER TABLE items RENAME COLUMN locked_by_wave_id TO locked_by_rollout_id;

-- Make claude_runs.item_id nullable to support manage-mode runs
-- that are scoped to a rollout rather than a single item.
ALTER TABLE claude_runs ALTER COLUMN item_id DROP NOT NULL;

-- ============================================================
-- ROLLBACK (reverse all of the above in reverse order)
-- ============================================================

-- ALTER TABLE claude_runs ALTER COLUMN item_id SET NOT NULL;
-- ALTER TABLE items RENAME COLUMN locked_by_rollout_id TO locked_by_wave_id;
-- ALTER TABLE claude_runs RENAME COLUMN rollout_id TO wave_run_id;
-- ALTER TABLE rollout_events RENAME COLUMN rollout_id TO wave_run_id;
-- ALTER TABLE rollout_items RENAME COLUMN rollout_id TO wave_run_id;
-- ALTER TABLE rollout_plans RENAME COLUMN rollout_id TO wave_run_id;
-- ALTER TABLE rollout_events RENAME TO wave_events;
-- ALTER TABLE rollout_items RENAME TO wave_plan_items;
-- ALTER TABLE rollout_plans RENAME TO wave_plans;
-- ALTER TABLE autonomous_rollouts RENAME TO autonomous_wave_runs;
