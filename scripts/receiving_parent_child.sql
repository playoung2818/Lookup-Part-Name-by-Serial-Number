-- Parent/child (configured system) columns for receiving_log. Approved schema change.
-- Adds three NULLABLE columns: no new tables, no defaults, no data rewrite,
-- existing rows/applications are unaffected (all values stay NULL).
--   item_role       'parent' | 'child' | NULL (ordinary row)
--   ordering_model  parent's full ordering model, e.g. SEMIL-1708-i7OCG9-FF08-64
--   parent_id       child -> parent receiving_log.id (no FK: the primary key is
--                   (id, serial_number), so id alone cannot be referenced)
-- Run once, e.g.:  psql "$DATABASE_DSN" -f scripts/receiving_parent_child.sql
-- Restart the web app afterwards (receiving_log structure is cached per process).

SET lock_timeout = '10s';
ALTER TABLE receiving_log
    ADD COLUMN IF NOT EXISTS item_role varchar(10),
    ADD COLUMN IF NOT EXISTS ordering_model varchar(255),
    ADD COLUMN IF NOT EXISTS parent_id integer;
RESET lock_timeout;

-- Find the children of a parent quickly (run outside a transaction block).
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_receiving_log_parent_id
    ON receiving_log (parent_id) WHERE parent_id IS NOT NULL;

-- Rollback, if needed:
--   DROP INDEX CONCURRENTLY IF EXISTS ix_receiving_log_parent_id;
--   ALTER TABLE receiving_log DROP COLUMN IF EXISTS parent_id,
--       DROP COLUMN IF EXISTS ordering_model, DROP COLUMN IF EXISTS item_role;
