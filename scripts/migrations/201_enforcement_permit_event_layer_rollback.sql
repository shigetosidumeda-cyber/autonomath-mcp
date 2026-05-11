-- target_db: autonomath
-- migration 201_enforcement_permit_event_layer (ROLLBACK companion)
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.
--
-- Only the VIEW is dropped here. am_enforcement_detail and permit_event
-- belong to other migrations (their own *_rollback.sql files cover their
-- DROP) so this companion intentionally does NOT drop those base tables.

DROP VIEW IF EXISTS v_enforcement_permit_event_layer;
