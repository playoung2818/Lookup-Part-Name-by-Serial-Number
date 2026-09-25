# 🔍 Lookup Part Name by Serial Number



This is a Flask-based web application that allows users to:
- Look up part names by serial numbers
- Prune multiple serial numbers from raw text
- Sync receiving log data from a Excel Sheet to a PostgreSQL database

To run this app with the Word-file API, run
`python app.py`. This single process serves both the web app and API on port 5000;
no separate API process is needed.
The API is available at `http://127.0.0.1:5000/api/word-files` and
`http://localhost:5000/api/word-files`.
The API reads existing records from `word_file_log`; importing Word files is
handled separately. Set `DATABASE_DSN` to override the database connection.

---

![Animation](https://github.com/user-attachments/assets/639a5ecf-670b-4952-8bad-09c2a29fa427)

---

## 📦 Features

- **Serial Number Lookup:** Search for parts by entering serial numbers
- **Batch Pruning:** Clean and extract useful serial numbers from messy input
- **Excel Sheet Sync:** Automatically loads data from an Excel Sheet
- **Word File Validation:** Upload `.docx` files to validate SN-part mappings via internal API

---


## 🏗️ Project Structure

- `receiving_log_app/`
  - `app/` – Application package  
    - `__init__.py` – App factory setup  
    - `config.py` – Configuration (DB, logging, etc.)  
    - `models/models.py` – SQLAlchemy models  
    - `routes/index_routes.py` – Main UI routes  
    - `routes/api_routes.py` – API endpoints   
    - `services/utils.py` – Helper functions (e.g., SN extractor)  
    - `services/validation.py` – Serial number and part matching logic
    - `templates/index.html` – Frontend template  
  - `app.py` – Entry point using `create_app()`  
  - `requirements.txt` – Python dependencies  
  - `README.md` – Project documentation




# Warehouse Borrow Log

Open `/warehouse-borrow-log/` or use the **Warehouse Borrow Log** tab. Add a borrow
record with **New entry**, which opens the Excel-style grid by default; select its
Borrow ID to edit it or record a return. The grid supports one or up to 100 items per save.
Add/remove rows, tab between cells, or paste an Excel range matching the grid's
column order. New rows copy warehouse, purpose, borrower, and borrow date from the previous row.
New-entry columns are Serial Number, Item Name / #, Borrowed Qty, Warehouse,
Purpose, Borrower, and Borrow Date. New records start with Returned Qty 0 and blank
Return Date and Issued By; those fields remain available when editing saved records.
Each serial has its own lookup. Rows without both serial and item name are skipped.
All used rows are validated and saved in one transaction; errors preserve the grid
and save nothing. Each item receives its own Borrow ID and return tracking.
Returned Qty is the cumulative quantity returned, not the quantity for one return.
Serial Number appears before Item Name / # in the form and table. Typing a serial
automatically looks up `receiving_log.part_number` using a full serial match
(case-insensitive; surrounding spaces and an `S/N` prefix are accepted).
Unknown or unavailable serials allow manual item entry. Changing the serial clears
the previous item, and delayed lookup results never overwrite a newer manual edit.

The module mirrors `Warehouse_Borrowing_Log.xlsx`: the same 13 columns, blue table
format, all-record Open Records and Total Borrowed Qty summaries, yellow quantity
mismatches, orange durations at 31–60 days, and red durations above 60 days.
Status is calculated as BORROWED, PARTIAL RETURN, RETURNED, or ERROR (returned
quantity greater than borrowed quantity). Duration ends on Return Date when entered;
otherwise it uses the server's current date. Leave Return Date blank while items
remain outstanding. Borrow IDs use `BR-yymmdd-NNN`, with a database sequence instead
of a worksheet row; changing Borrow Date changes the date portion of the ID.
Warehouse and purpose suggestions permit custom values, as the workbook does.

Create just the new PostgreSQL table (does not alter existing tables):

```powershell
python setup_borrow_log.py
```

Optionally initialize an empty table with the workbook's existing records:

```powershell
python setup_borrow_log.py "C:\path\to\Warehouse_Borrowing_Log.xlsx"
```

Import preserves the worksheet Borrow ID suffixes and skips an already populated
table. It reads but never modifies the workbook; there is no ongoing Excel sync.
Restart the app after deployment. Set `SECRET_KEY` in the app's environment for
sessions that survive restarts; otherwise open forms expire when the app restarts.

Validation and workflow tests use an isolated in-memory database:

```powershell
python -B -m unittest discover -s tests -v
```
