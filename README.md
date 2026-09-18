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




