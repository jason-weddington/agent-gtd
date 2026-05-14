-- One-off migration: remove wave reaper artifacts (item 99eaab2d).
-- Run during the deploy that ships feat/99eaab2d-remove-the-wave-reaper.

-- Reclassify any historical crashed waves as cancelled
UPDATE autonomous_wave_runs
SET status = 'cancelled',
    halt_reason = COALESCE(halt_reason, 'crashed (legacy)')
WHERE status = 'crashed';

-- Delete reaper-emitted events
DELETE FROM wave_events
WHERE actor = 'reaper' OR kind = 'wave_crashed';
