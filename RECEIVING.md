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

The draft grid supports cell-range selection by dragging, Shift-clicking or Shift+Arrow keys. Paste with Ctrl+V / Cmd+V. A rectangular Excel block expands from one starting cell, or must match the selected range. One copied value fills a selection. INV# remains locked. Pastes that touch INV# are rejected before any cells change. Paste dates as YYYY-MM-DD. Invalid or out-of-bounds pastes are rejected as a whole. Saved invoice entry supports scanning and SN-only range selection/paste; non-SN columns remain locked.

Draft cells are not autosaved. Save before leaving. Switching transactions warns about leaving a draft. Draft files are server-side business data, not database records.

## 2. Fill consecutive serials — standalone tool

This always-expanded tool is available before loading an invoice, during draft review, or while viewing saved records. It does not select table rows, call the database, or save serials into records.

1. Enter the first serial and quantity (1–20,000).
2. Select **Generate serials**.
3. Review the first/last serial and generated column.
4. Select **Copy serial list**. If browser clipboard access is unavailable over HTTP, the list is selected for manual Ctrl+C / Cmd+C.

For example, `SC69031431` and quantity `20` produce `SC69031431` through `SC69031450`. Only trailing digits increase. Leading zeros remain intact. Non-numeric suffixes and changes in numeric width are rejected. Generated results do not depend on available database rows and are not checked for duplicates against the database. Editing either input clears stale results. Copying the list does not save it anywhere. To enter it into a saved invoice, select the destination SN cells in the receiving table and paste.

## 3. Reload entry by INV#

Search the **exact QuickBooks INV#**, preserving leading zeros. This loads that invoice's current database rows and establishes a browser workspace scoped to the selected invoice. No file uploads are needed.

Only serial numbers can change after database commit. Only populated serials require **Correct**; blank SN cells unlock when focused regardless of quantity.

### Scan missing serials directly in the table

1. Click any blank SN cell, including bulk rows.
2. Scan or type one serial number.
3. Press Enter (or use the scanner's Enter suffix).
4. Wait for saving to finish and focus to move before scanning the next item.

Enter moves to the next visible blank SN row in the same carton/POD/product group. Existing serials are skipped; quantity does not restrict SN entry and is never changed. A saving error keeps focus on the current cell. At the end of the group, click another blank cell to continue. There is no separate group dropdown or single-scan form.

### Correct and recover

Select **Correct** to unlock one serial cell. Save with Enter, **Save**, or by leaving the cell. Ctrl+S / Cmd+S retries pending corrections. Each successful correction locks the cell again.

### Select and paste serial numbers

Drag over SN cells, Shift-click the last cell, or use Shift+Arrow keys to select a range. Paste a one-column serial list with Ctrl+V / Cmd+V. A list must match the selected range; alternatively click one starting SN cell and paste down visible rows. One copied value fills a selection (useful for repeated `NA`; repeated real serials are rejected). Table filters determine which rows are included; changing a filter clears the selection.

Blank SN cells accept paste directly regardless of quantity. Only populated serials require **Correct** on each intended row before pasting. A bulk row still stores one SN value; typing, scanning or pasting does not split the row or change its quantity. A locked destination, invalid value, local duplicate, mismatched selection or out-of-bounds paste rejects the entire paste before any edits. After validation, each row saves individually using the existing stale-version, database-duplicate and retry checks. This is not an atomic database batch: some rows may save while others show errors. Check row statuses and retry failed rows with Save or Ctrl+S. No non-SN fields or quantities change.

If a row save is not confirmed, use that row's **Save** button to retry its entered serial. An already stored value is read-only on retry. Leaving the page warns about unconfirmed row writes. The standalone generator remains usable even if a row has an error.

Every successful table scan or correction updates existing `receiving_log` rows immediately. Unfinished shipments remain available to serial-number lookup. No final import is required.

Filter records by box, POD, part, serial or Reference. Blank-serial and unsaved/error filters are also available. Refresh and downloads read the database. A database failure never substitutes stale file values. Word inspection remains Pending, never automatic PASS.

Other fields cannot be edited through the row endpoint. No database deletion endpoint is provided. Failed corrections must be resolved before another invoice or template opens.

## 4. Generate incoming form

Enter an exact saved invoice number (leading zeros preserved), optionally upload the existing Word template, then select **Generate incoming form (.docx)**. There is no need to load that invoice into the entry table, and the active invoice/draft is not replaced.

The function reads `receiving_log` in ID order, groups by box/product/POD, sums quantities and joins distinct serials in first-seen order. Blank/missing serials display as `NA`. Carton labels matching `group--start-end` sort numerically, followed by unmatched labels in stable first-seen order. It appends the seven requested columns to the original template: Product Number, Q'TY, S/N, From (Vendor or Customer), Invoice # or RMA #, IQC Result, IQC Remark. Vendor is Neousys Technology. Existing template content is preserved; fractional quantities are not silently truncated.

Check **I confirm inspection has passed** to write `PASS` and `[Receiving & Inspection Result: Pass]`. Otherwise inspection stays Pending. Generating a document does not perform an inspection. The existing **Incoming Word draft** table download remains a separate Pending-only export.

The default template is `OneDrive - neousys-tech\Share NTA Warehouse\01 Incoming\Incoming Form Template.docx`, resolved relative to the current user's home folder (`Path.home()`), not the app's working directory. No drive letter is hard-coded. Override it with `RECEIVING_INCOMING_TEMPLATE_PATH`, or upload a `.docx` (10 MB maximum). The browser downloads `I{MM}-{MMDDYY}-TaiwanHQ-<invoice>.docx`, using the server's local date when generated (including an automatically updated month prefix); neither the template nor shared-folder documents are overwritten. No database tables are created and no receiving records are updated. The existing `DATABASE_DSN` is used; no notebook credentials or new Flask app/model are embedded. No pandas or IPython runtime dependency is required.

## Database safety

No new tables, indexes or constraints are created. The existing `receiving_log` must have unique non-null IDs. Blank serials remain blank, not automatically NA.

- Draft updates are validated as a complete batch before replacing saved draft values. Stale template revisions are rejected.
- Template commits acquire the existing PostgreSQL `SHARE ROW EXCLUSIVE` lock (10-second timeout), or SQLite `BEGIN IMMEDIATE`. The existing-invoice check happens under this lock. The commit reads only rows that can affect it (its bound IDs, its INV# and its serials), not the whole table.
- Single-row scans/corrections (`POST /receiving/row`) use row-level locking on PostgreSQL: `ROW EXCLUSIVE` on the table (excludes batch writers, allows concurrent scans of other rows), `SELECT … FOR UPDATE` on the target row, and a transaction advisory lock per serial so two scans of the same SN cannot both pass the duplicate check. SQLite still uses `BEGIN IMMEDIATE`.
- `POST /receiving/row` returns only the saved row plus workspace metadata (`{workspace, row}`), not the whole invoice. Use Refresh to see external changes to other rows.
- The `receiving_log` structure is reflected once per process. Restart the app after altering its columns.
- Lookup indexes from `scripts/receiving_lookup_indexes.sql` (`ix_receiving_log_serial_key`, `ix_receiving_log_invoice_number`) are applied to the production database.
- A durable write-ahead journal bridges database commit and recording generated IDs. Retry an ambiguous save; do not regenerate. Refresh recovers a confirmed commit without reinsertion. Pending journals prevent replacement/editing.
- `POST /receiving/row` accepts only workspace ID, row ID, SN and expected database-row version. The server resolves the row in the active workspace, verifies its current database invoice matches the fixed invoice scope, and updates only SN with an ID-and-invoice predicate.
- Stale versions reject external changes rather than overwrite them. If a row moves to another invoice externally, it cannot be edited through the old selection. Deleted rows are not recreated.
- Duplicate nonblank/non-NA serials are checked across the database. Lost-response retries for an already stored SN are read-only.
- The legacy batch endpoint (not used by the standalone Section 2 tool), `POST /receiving/serials`, accepts a workspace ID, a nullable group, and explicit row ID/version/serial assignments. A null group enables invoice-wide fill; a group object retains compatibility with older clients. It uses the existing receiving lock. Every row must belong to the fixed invoice (and group, if supplied), retain its selected carton/POD/product and Qty 1, and remain blank with the expected version. An exact retry of an already stored value is read-only. All assignments commit together. It never inserts rows or overwrites a different serial.
- The original occurrence-aware receipt matching and recovery machinery remains available for legacy workspaces. New template commits reject existing invoices rather than reconcile/overwrite them.

**Access control:** The module uses signed browser sessions and CSRF protection, but does not add user login or per-user invoice permissions. Anyone with deployment access can search an invoice. Transaction scoping protects the selected editing workflow; restrict deployment access if only designated staff should open particular invoices.

## Sources and generation rules

- QuickBooks Date and Ref. No. supply receiving Date and INV#, preserving the identifier exactly (e.g. `80003610`). Vendor invoice may differ (e.g. `8003610`); serial-export invoice must exactly match the packing invoice.
- Packing list supplies carton/range, POD, model and quantity. Omitted cartons inherit the preceding carton across pages. Ranges remain ranges; individual allocations are not guessed.
- Serial headers: `Customer PO No`, `Ordering Model`, `S/N`, `Invoice No`. Consume in source order by POD + normalized model. Duplicate export serials and invoice mismatches block generation.
- Configured reference lookup headers: `POD`, `Reference`; first exact POD match wins. Actual text is stored, not external formulas.
- Prefixes `Cbl, DIN, AccsyBx, Gpubr, Ant, FK, TB, Screw, Wmkit, Dmpbr, DtC` retain bulk quantities; other products expand to Qty 1 rows. Three notebook SSD aliases apply.
- Packing quantities/carton totals must reconcile. No-POD lines are excluded and reported, not assigned guessed PODs. Missing References and unused serials are reported.
- Validate QuickBooks quantity × cost and totals.
- **Configured systems (parent/child).** A packing line described as `<QB item>, including <components>` (e.g. `SEMIL-1708-FF, including i7-9700E`) whose base is a QuickBooks item becomes, per unit: one **parent** row (Part# = QuickBooks item, SN from the export, `Ordering Model` = packing model such as `SEMIL-1708-i7OCG9-FF08-64`) followed by one **child** row per included component (`2x` = two Qty 1 rows; bulk prefixes such as `Cbl`/`DtC` keep one row with the quantity). Child SNs start blank and are scanned later. Descriptive kits (`... cable kit, including: ...`) and bases not on the receipt are not split. Packing/QuickBooks name differences are mapped in `COMPONENT_ALIASES`.
- Stored in nullable `receiving_log` columns `item_role` (`parent`/`child`/NULL), `ordering_model` and `parent_id` (child → parent `id`), added by `scripts/receiving_parent_child.sql` (applied). Reload by INV#, refresh and Excel export (`Role`, `Ordering Model`, `Parent Row` columns) keep the links.
- **QB Reconciliation** sheet: receiving quantities per part vs QuickBooks physical lines; differences appear as `QB quantity mismatch` exceptions for review (not blocking).
- Packing layout tolerance: `INV NO:` with or without a period, totals printed on the `TOTAL ... CTNS` line, whole-number net weights. Serial exports may print `<MODEL> S/N <serial>`; exact repeated export rows are used once and reported, while one SN on different POD/model combinations still blocks generation.
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
node --check static/receiving_incoming.js
node tests/receiving_entry.test.cjs
node tests/receiving_grid.test.cjs
node tests/receiving_serials.test.cjs
node --test tests/receiving_sequence_ui.test.cjs
python -m unittest discover -s tests -p 'test_incoming_form.py'
```

Receiving tests use generated workbooks, SQL metadata and a transactional fake database, never production records or DDL. They cover deferred generation, draft validation, explicit commit, closed-template protection, existing-invoice rejection, invoice search, serial-only payloads, cross-workspace rejection, stale edits, duplicates and save recovery. Serial-fill tests also cover invoice-wide fill across groups, legacy group boundaries, bulk protection, atomic rollback, preserved leading zeros and large numeric suffixes.

Run the isolated browser fixture with `python tests/serve_receiving_browser_fixture.py --instance PATH_TO_EMPTY_TEMP_DIRECTORY --port 5019`. Open `http://192.168.60.215:5019/browser-check`. The fixture uses a transactional fake database. It covers the standalone Section 2 generator before invoice load and during draft review, section order, generation without network/database writes, draft review/commit, direct scanning with Enter advancement, range paste with locked-cell and duplicate rejection, corrections, blank bulk SN entry with quantity preservation and database-backed reload.
