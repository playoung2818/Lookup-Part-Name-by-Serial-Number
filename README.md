# 🔍 Lookup Part Name by Serial Number



This is a Flask-based web application that allows users to:
- Look up part names by serial numbers
- Retrieve part usage history
- Prune multiple serial numbers from raw text
- Sync receiving log data from a Excel Sheet to a PostgreSQL database

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

receiving_log_app/
├── app/                        # Application package
│   ├── __init__.py             # App factory setup
│   ├── config.py               # Configurations (DB, logging, etc.)
│   ├── models/                 # SQLAlchemy models
│   │   └── models.py
│   ├── routes/                 # Route handlers
│   │   ├── index_routes.py
│   │   └── api_routes.py
│   ├── services/               # Core logic (business logic layer)
│   │   ├── data_loader.py      # Data loading from Google Sheets / Excel
│   │   ├── utils.py            # Helper functions
│   │   └── validation.py       # Validation and matching logic
│   └── templates/              # Frontend HTML templates
│       └── index.html
├── app.py                      # App runner (can use create_app pattern)
├── requirements.txt            # Python dependencies
├── README.md                   # Project documentation



