# Receiving: template review and invoice-scoped serial entry

Open **http://192.168.60.215:5000/receiving**.

## 1. Generate template and save to database

1. Upload exactly three files: QuickBooks Item Receipt PDF, packing-list PDF, and serial export Excel.
2. Generate a **draft only**. Generation does not insert or update database records.
3. Review/edit date, box, POD, part, SN, quantity and Reference in the draft grid. INV# is fixed to the generated QuickBooks Ref. No.; each transaction must have exactly one nonblank INV#. Adding/deleting draft rows is not supported.
4. **Save draft changes** retains the reviewed template on the server without database writes.
5. **Save template to database & finish** saves current edits, validates the draft and commits all rows in one database transaction. This ends template editing and switches to serial-only database entry.
6. If the INV# already exists, template commit is rejected without modifying existing records. Use the second module to reopen it. Other invoices are never overwritten or deleted by template commit.

There is no POD-Reference upload parameter. If `RECEIVING_REFERENCE_PATH` points to an available workbook, the server can still use it automatically. Otherwise References may be blank and can be reviewed in the draft.

Both grids support cell-range selection by dragging, Shift-clicking or Shift+Arrow keys. Paste with Ctrl+V / Cmd+V. In drafts, a rectangular Excel block expands from one starting cell, or must match the selected range. One copied value fills a selection. INV# remains locked; pastes touching it are rejected before changing any cells. Dates must be pasted as YYYY-MM-DD; invalid or out-of-bounds pastes are rejected as a whole. In saved invoice entry, selection/paste is restricted to the SN column and visible rows.

Draft cells are not autosaved. Save before leaving. Switching transactions warns about leaving a draft. Draft files are server-side business data, not database records.

## 2. Reload entry by INV#

Search the **exact QuickBooks INV#**, preserving leading zeros. This loads that invoice's current database rows and establishes a browser workspace scoped to the selected invoice. No file uploads are needed.

Only SN is editable after database commit or invoice search:

- Each changed SN saves individually after a short pause, on Enter, or on blur.
- Enter / Arrow Down advances; Shift+Enter / Arrow Up goes back.
- Paste one Excel column into consecutive visible rows. Bulk Qty > 1 rows accept SN entry without changing quantities.
- Ctrl+S / Cmd+S retries individual row updates. Each row also has a Save/retry button.
- Filter by box/POD/part/SN/Reference, blank SN, or unsaved/error status.
- Refresh reads the current database. Database failure never substitutes stale file values.
- Excel and Word downloads read current database values in entry mode. Word inspection remains Pending, never automatic PASS.

Other fields cannot be edited through the row endpoint. No database deletion endpoint is provided. Selecting a different invoice or generating another template waits for pending SN saves; failed entries must be resolved first.

## Database safety

No new tables, indexes or constraints are created. The existing `receiving_log` must have unique non-null IDs. Blank serials remain blank, not automatically NA.

- Draft updates are validated as a complete batch before replacing saved draft values. Stale template revisions are rejected.
- Template commits acquire the existing PostgreSQL `SHARE ROW EXCLUSIVE` lock (10-second timeout), or SQLite `BEGIN IMMEDIATE`. The existing-invoice check happens under this lock.
- A durable write-ahead journal bridges database commit and recording generated IDs. Retry an ambiguous save; do not regenerate. Refresh recovers a confirmed commit without reinsertion. Pending journals prevent replacement/editing.
- `POST /receiving/row` accepts only workspace ID, row ID, SN and expected database-row version. The server resolves the row in the active workspace, verifies its current database invoice matches the fixed invoice scope, and updates only SN with an ID-and-invoice predicate.
- Stale versions reject external changes rather than overwrite them. If a row moves to another invoice externally, it cannot be edited through the old selection. Deleted rows are not recreated.
- Duplicate nonblank/non-NA serials are checked across the database. Lost-response retries for an already stored SN are read-only.
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
node tests/receiving_entry.test.cjs
node tests/receiving_grid.test.cjs
```

Receiving tests use generated workbooks, SQL metadata and a transactional fake database, never production records or DDL. They cover deferred generation, draft validation, explicit commit, closed-template protection, existing-invoice rejection, invoice search, serial-only payloads, cross-workspace rejection, stale edits, duplicates and save recovery. `tests/receiving_entry.browser.html` is an isolated browser fixture for draft rectangular paste, atomic locked-invoice rejection, SN range selection, draft review/commit and scanner/paste/serial entry.
