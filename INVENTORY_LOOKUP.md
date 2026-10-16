# Inventory-count lookup (read-only)

The lookup interface has moved from MRP to Receiving Log App. This is NOT the earlier physical-count entry feature: no physical counts, variance records, snapshot tables, or inventory adjustments are created.

## URLs

- Receiving: `/inventory_count` (also `/inventory-count`).
- MRP: `GET /api/inventory-lookup?item=...` returns the lookup data.
- The old MRP `/inventory_count` page, template, and navigation entry are removed. Use the Receiving page directly.

## Ownership

MRP retains item normalization, published inventory quantities, stock summaries, open-order lookup and last-seven-days receipt aggregation. Receiving renders the returned data and provides item autocomplete. It does not query WO records to recompute WIP or derive On Hand minus WIP.

Search by item only. SO/QB references can still appear in the open-order results table, but there is no SO/QB search field. With no item selected, the page lists the published inventory items; clicking an item opens its details.

## Configuration

Receiving `MRP_BASE_URL` defaults to `http://127.0.0.1:5002`. Configure the process environment if MRP is on another host.

Restart Receiving Log App to register the new module. Restart/reload MRP if its new API is unavailable. No database setup/migration is required, and no new tables are created.

## Reload and errors

Reload MRP data refreshes MRP's database cache and recent receiving cache. It does not run ETL or change inventory. Run the normal MRP ETL when calculated inventory needs updating.

“MRP data loaded” is the MRP cache-load timestamp, not the time of the underlying ERP export or ETL calculation. Upstream failures show an unavailable-data message, not zero stock. Missing quantities display a dash rather than falling back to On Hand.

## Files

Receiving: `routes/Inventory_Count_Routes.py`, `templates/inventory_count.html`, `static/inventory_count.css`, `static/inventory_count.js`.

MRP: lookup payload and API remain in `ERP_System/Webpage/server.py` and use its existing helpers/data cache. The original MRP inventory template and page route have been deleted.

## Tests

Receiving: `python -m unittest discover -s tests -v`

MRP (from MRP_System 3.0): `python -m unittest discover -s tests -v`

Checks cover item-only input, MRP-owned metrics, alias/case matching, item suggestions, no local count entry, read-only GET requests, reload preservation, old-page removal, missing data, upstream failure, and HTML escaping.
