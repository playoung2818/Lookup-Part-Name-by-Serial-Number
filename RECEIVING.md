# Receiving upload and conflict review

Open **Receiving** (`/receiving`). Upload the workbook, review an expandable serial-number tree, choose versions to keep, then explicitly apply the selected changes. Upload and preview never modify database records.

## Workbook requirements

- `.xlsx` or `.xlsm`; the first worksheet is imported regardless of its name.
- First-row headers: `Date`, `Inv#`, `Box #`, `POD#`, `Part#`, `SN#`, `QTY`. Surrounding header whitespace is ignored.
- Maximum 10 MB request, 100 MB uncompressed workbook, 20,000 worksheet rows.
- Blank, `NA`, and `nan` serials are skipped (case-insensitive).
- Text is trimmed. Serial comparison ignores case and surrounding spaces, preserving internal spaces and hyphens.
- Date and part number required for non-placeholder serials. Dates must be Excel dates or ISO `YYYY-MM-DD` text.
- Blank quantities default to 1. Invalid, nonfinite, zero, and negative quantities are rejected. Formula fields must be converted to values first.
- Invalid Excel values still block saving; duplicates are now reviewable decisions, not validation errors.

## GitHub-style change tree

Each new or conflicting serial has an expandable comparison with all database versions and distinct uploaded versions. Database IDs and Excel row numbers identify the candidates. Other database fields, including Reference, are displayed alongside the import fields. Changed cells are highlighted against the first database version (or first uploaded version for new serials). Search filters the tree without changing any decisions. Expand/collapse controls and a leave-all-unchanged action are available.

All conflict groups are displayed, not only the first 100. Validation errors alone are limited to the first 100 messages.

A repeated serial is not necessarily a duplicate event: an original purchase followed by a DOA/RMA return is valid history. Exact events compare date, invoice, box, POD, part, normalized serial, and quantity. Review the differences to distinguish a legitimate new receipt from an erroneous edit.

Choices per serial:

- **Keep history / add new events**: preserve every existing database record and insert only distinct uploaded events not already recorded. Never updates or deletes existing records, and requires no deletion authorization. For a Newegg purchase followed by a Samsung RMA already in the database, a matching uploaded Samsung row is skipped and both original database rows remain intact.
- **Leave unchanged** (default for conflicts): skip this serial's upload and leave all its database rows untouched. Existing duplicates are not deleted. Other selected serials can still be applied.
- **Keep DB #ID**: preserve the selected database row in full and delete other existing rows with this normalized serial. Do not import its uploaded versions.
- **Keep Excel row #**: if no database row exists, insert the chosen version. Otherwise update the lowest-ID database row with the seven imported fields and delete the other existing versions. The survivor's ID, Reference, and non-imported fields are preserved; notes on deleted rows are not merged.

New serials with just one uploaded version default to importing it, but can be left unchanged. Repeated uploaded rows with identical details are collapsed. A serial with exactly one matching database row and one matching uploaded version is skipped automatically.

History mode labels existing rows KEEP HISTORY and uploaded rows INSERT NEW EVENT or ALREADY RECORDED — SKIP. The individual-version cleanup choices still intentionally keep only one record; do not select those for legitimate RMA history.

The UI labels database rows KEEP, UPDATE, DELETE, or UNCHANGED as decisions change, and summarizes insert/update/delete counts. Database deletions require a separate explicit authorization checkbox, enforced server-side as well as in the browser. Back up data before resolving duplicates. No records are changed until **Apply selected changes** is clicked.

## Transaction safety

The existing `receiving_log` table must have unique, non-null `id` values. No tables, indexes, or constraints are created. Connection configuration remains the application's `DATABASE_DSN`.

Preview tokens contain only affected serials, are signed and session-bound, and expire after 30 minutes. A stable `SECRET_KEY` must be shared by application workers. CSRF validation protects both POST steps. This feature uses the application's existing access controls; it does not introduce authentication.

Apply acquires a PostgreSQL `SHARE ROW EXCLUSIVE` table lock (10-second timeout), or SQLite `BEGIN IMMEDIATE`, before rechecking the selected serials. PostgreSQL ordinary reads remain available while other writers wait. Other database dialects are rejected.

A snapshot includes every database field for each affected serial. If any selected serial's records changed since preview, the entire operation is cancelled; upload again. Unchanged/skipped serials are never modified and do not block application of other decisions. All choices and deletion authorization are checked before writes begin. Insert/update/delete errors roll back the entire batch, including foreign-key constraint failures. Replaying an already-applied change fails the snapshot check rather than duplicating records.

Locks protect this transaction, not future writes by other applications. Do not enforce uniqueness on serial alone: legitimate RMA history may repeat a serial. Any permanent database-wide event uniqueness rule requires a separately approved schema design that accounts for distinct receipt events. Preview reads all receiving rows; very large tables may eventually need targeted indexed lookups.

## Read-only PostgreSQL duplicate audit

```sql
SELECT *
FROM (
    SELECT *, COUNT(*) OVER (
        PARTITION BY UPPER(TRIM(serial_number))
    ) AS cnt
    FROM receiving_log
    WHERE serial_number IS NOT NULL
      AND UPPER(TRIM(serial_number)) NOT IN ('', 'NA', 'NAN')
) t
WHERE cnt > 1
ORDER BY entry_date DESC, id DESC;
```

## Verification

```text
python -B -m unittest discover -s tests -p 'test_receiving.py' -v
node --check static/receiving.js
```

Tests use generated workbooks and mocked database connections; no database tables are created or production records modified. Live PostgreSQL locking/constraint behavior should also be verified in an approved test environment before database cleanup.
