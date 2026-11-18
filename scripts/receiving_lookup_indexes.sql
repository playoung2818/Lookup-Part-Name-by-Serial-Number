-- Proposed receiving_log lookup indexes. NOT applied automatically.
-- Requires approval before running. Adds indexes only: no tables, columns,
-- constraints or data changes. CONCURRENTLY avoids blocking reads/writes;
-- run each statement outside a transaction block, e.g.:
--   psql "$DATABASE_DSN" -f scripts/receiving_lookup_indexes.sql
--
-- Matches functions/serial_lookup.py, receiving duplicate checks and
-- /api/sheet-update: upper(trim(serial_number)) = :key
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_receiving_log_serial_key
    ON receiving_log (upper(trim(serial_number)));

-- Exact invoice search (Receiving section 3, incoming form, invoice export).
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_receiving_log_invoice_number
    ON receiving_log (invoice_number);

-- Rollback, if needed:
--   DROP INDEX CONCURRENTLY IF EXISTS ix_receiving_log_serial_key;
--   DROP INDEX CONCURRENTLY IF EXISTS ix_receiving_log_invoice_number;
