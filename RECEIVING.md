# Receiving: template review, serial scanning and sequence fill

Open **http://192.168.60.215:5000/receiving**.

## 1. Generate template and save to database

1. Upload exactly three files: QuickBooks Item Receipt PDF, packing-list PDF, and serial export Excel.
2. Generate a **draft only**. Generation does not insert or update database records.
3. Review/edit date, box, POD, part, SN, quantity and Reference in the draft grid. INV# is fixed to the generated QuickBooks Ref. No.; each transaction must have exactly one nonblank INV#. Adding/deleting draft rows is not supported.
4. **Save draft changes** retains the reviewed template on the server without database writes.
5. **Save template to database & finish** saves current edits, validates the draft and commits all rows in one database transaction. This ends template editing and switches to serial-only database entry.
6. If the INV# already exists, template commit is rejected without modifying existing records. Use the second module to reopen it. Other invoices are never overwritten or deleted by template commit.

There is no POD-Reference upload parameter. If `RECEIVING_REFERENCE_PATH` points to an available workbook, the server can still use it automatically. Otherwise References may be blank and can be reviewed in the draft.

The draft grid supports cell-range selection by dragging, Shift-clicking or Shift+Arrow keys. Paste with Ctrl+V / Cmd+V. A rectangular Excel block expands from one starting cell, or must match the selected range. One copied value fills a selection. INV# remains locked. Pastes that touch INV# are rejected before any cells change. Paste dates as YYYY-MM-DD. Invalid or out-of-bounds pastes are rejected as a whole. Saved invoice entry uses scanning and sequence fill, not spreadsheet-range editing.

Draft cells are not autosaved. Save before leaving. Switching transactions warns about leaving a draft. Draft files are server-side business data, not database records.

## 2. Reload entry by INV#

Search the **exact QuickBooks INV#**, preserving leading zeros. This loads that invoice's current database rows and establishes a browser workspace scoped to the selected invoice. No file uploads are needed.

The receiving records are read-only until you choose **Correct** on a row. Only serial numbers can change after database commit.

### Scan missing serials

1. Choose a carton / POD / product group under **Enter missing serials**.
2. Scan or type one serial number.
3. Press Enter or select **Save serial**.
4. Wait for the saved confirmation before scanning the next item.

Each scan fills the next blank Qty 1 row in database-ID order within the selected group. Existing serials remain unchanged. A full group stops scanning. The app does not select another group automatically. Table filters do not change the selected scan group.

### Fill consecutive serials

1. Choose the destination group.
2. Open **Fill consecutive serials**.
3. Enter the first serial and quantity.
4. Select **Preview sequence**.
5. Review the first serial, last serial, count and destination.
6. Select **Save sequence to database**.

For example, `ABC000127` and quantity `4` produce `ABC000127` through `ABC000130`. Only the trailing digits increase. Leading zeros remain intact. Non-numeric suffixes and changes in numeric width are rejected. Counts must be from 1 to 20,000 and cannot exceed the group's blank unit slots.

The server checks all target rows and serials before any update. A sequence saves in one transaction or saves nothing. Duplicate serials are rejected across the database, not just the selected invoice. No scan or sequence changes a quantity or fills a bulk Qty > 1 row. Existing `NA` values are not blank slots. Use a row correction for exceptional bulk serial entry.

### Correct and recover

Select **Correct** to unlock one serial cell. Save with Enter, **Save**, or by leaving the cell. Ctrl+S / Cmd+S retries pending corrections. Each successful correction locks the cell again. Multi-row spreadsheet paste is not available in saved entry.

If a scan or sequence save is not confirmed, select **Retry same save**. The retry uses the original row IDs, versions and serials. It never allocates another set of blank rows. Alternatively, select **Reload database values** to inspect the current records before starting again. Group changes, corrections, downloads and invoice changes are blocked while the scan or sequence remains unconfirmed. Leaving the page warns about unconfirmed writes.

Every successful scan, sequence or correction updates existing `receiving_log` rows immediately. Unfinished shipments remain available to serial-number lookup. No final import is required.

Filter records by box, POD, part, serial or Reference. Blank-serial and unsaved/error filters are also available. Refresh and downloads read the database. A database failure never substitutes stale file values. Word inspection remains Pending, never automatic PASS.

Other fields cannot be edited through the row endpoint. No database deletion endpoint is provided. Failed corrections must be resolved before another invoice or template opens.

## Database safety

No new tables, indexes or constraints are created. The existing `receiving_log` must have unique non-null IDs. Blank serials remain blank, not automatically NA.

- Draft updates are validated as a complete batch before replacing saved draft values. Stale template revisions are rejected.
- Template commits acquire the existing PostgreSQL `SHARE ROW EXCLUSIVE` lock (10-second timeout), or SQLite `BEGIN IMMEDIATE`. The existing-invoice check happens under this lock.
- A durable write-ahead journal bridges database commit and recording generated IDs. Retry an ambiguous save; do not regenerate. Refresh recovers a confirmed commit without reinsertion. Pending journals prevent replacement/editing.
- `POST /receiving/row` accepts only workspace ID, row ID, SN and expected database-row version. The server resolves the row in the active workspace, verifies its current database invoice matches the fixed invoice scope, and updates only SN with an ID-and-invoice predicate.
- Stale versions reject external changes rather than overwrite them. If a row moves to another invoice externally, it cannot be edited through the old selection. Deleted rows are not recreated.
- Duplicate nonblank/non-NA serials are checked across the database. Lost-response retries for an already stored SN are read-only.
- `POST /receiving/serials` accepts a workspace ID, one carton/POD/product group, and explicit row ID/version/serial assignments. It uses the existing receiving lock. Every row must belong to the fixed invoice and group, retain Qty 1, and remain blank with the expected version. An exact retry of an already stored value is read-only. All assignments commit together. It never inserts rows or overwrites a different serial.
- The original occurrence-aware receipt matching and recovery machinery remains available for legacy workspaces. New template commits reject existing invoices rather than reconcile/overwrite them.

**Access control:** The module uses signed browser sessions and CSRF protection, but does not add user login or per-user invoice permissions. Anyone with deployment access can search an invoice. Transaction scoping protects the selected editing workflow; restrict deployment access if only designated staff should open particular invoices.

## Sources and generation rules

- QuickBooks Date and Ref. No. supply receiving Date and INV#, preserving the identifier exactly (e.g. `80003610`). Vendor invoice may differ (e.g. `8003610`); serial-export invoice must exactly match the packing invoice.
- Packing list supplies carton/range, POD, model and quantity. Omitted cartons inherit the preceding carton across pages. Ranges remain ranges; individual allocations are not guessed.
- Serial headers: `Customer PO No`, `Ordering Model`, `S/N`, `Invoice No`. Consume in source order by POD + normalized model. Duplicate export serials and invoice mismatches block generation.
- Configured reference lookup headers: `POD`, `Reference`; first exact POD match wins. Actual text is stored, not external formulas.
- Prefixes `Cbl, DIN, AccsyBx, Gpubr, Ant, FK, TB, Screw, Wmkit, Dmpbr, DtC` retain bulk quantities; other products expand to Qty 1 rows. Three notebook SSD aliases apply.
- Packing quantities/carton totals must reconcile. No-POD lines are excluded and reported, not assigned guessed PODs. Missing References and unused serials are reported.
- Validate QuickBooks quantity × cost and totals. Component lines remain evidence, not additional physical receiving rows.
- Generated workbook exports retain source evidence; invoice-search exports contain current rows without original generation evidence.
- Open PO price/bundle inference, purchase-order writes, shared-folder POD merging and server printing are not implemented.

## Persistence and deployment

`instance/receiving_workspaces/<owner>/` holds active selection, draft rows, source evidence, database IDs and save-recovery metadata. In entry mode the database is the source of displayed values. These ignored files should be protected/backed up. Never delete pending journals.

Signed persistent browser cookies identify the active selection (365-day session lifetime). Use a stable `SECRET_KEY`. Clearing cookies creates a new selection; saved database invoices can still be searched again. Workspaces do not expire automatically. All workers must share the workspace filesystem; cross-process locks serialize changes.

Legacy workspace migration retains a `.before_database.json` backup. Already initialized legacy workspaces read database values; uninitialized legacy workspaces offer initial-save recovery.

Dependencies: existing Flask/SQLAlchemy stack plus `pdfplumber`, `openpyxl`, `python-docx`. Limits: 10 MB/file, 32 MB/upload, 100 PDF pages, 20,000 rows/units, 100 MB decompressed workbook.

Restart with `scripts/run_web.py` or the deployed WSGI factory. Do not run schema setup scripts for this feature.

## Verification

```text
python -m unittest discover -s tests
node --check static/receiving.js
node --check static/receiving_template.js
node --check static/receiving_grid.js
node --check static/receiving_serials.js
node tests/receiving_entry.test.cjs
node tests/receiving_grid.test.cjs
node tests/receiving_serials.test.cjs
```

Receiving tests use generated workbooks, SQL metadata and a transactional fake database, never production records or DDL. They cover deferred generation, draft validation, explicit commit, closed-template protection, existing-invoice rejection, invoice search, serial-only payloads, cross-workspace rejection, stale edits, duplicates and save recovery. Serial-fill tests also cover group boundaries, bulk protection, atomic rollback, preserved leading zeros and large numeric suffixes.

Run the isolated browser fixture with `python tests/serve_receiving_browser_fixture.py --instance PATH_TO_EMPTY_TEMP_DIRECTORY --port 5019`. Open `http://127.0.0.1:5019/browser-check`. The fixture uses a transactional fake database. It covers draft review/commit, read-only records, scanning, sequence preview/fill, group boundaries, lost-response retry, corrections and database-backed reload.
