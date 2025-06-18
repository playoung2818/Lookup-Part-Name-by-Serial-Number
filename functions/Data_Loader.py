import logging
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy import text
from dateutil.parser import parse
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, request, render_template_string, jsonify
from flask_sqlalchemy import SQLAlchemy

# # Load Excel
# logging.basicConfig(level=logging.INFO)

# app = Flask(__name__)

# # Database configuration
# app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:Czheyuan0227%40@localhost:5432/File_Log'
# app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# db = SQLAlchemy(app)
# def load_data():
#     file_path2 = r"c:\Users\Admin\OneDrive - neousys-tech\Share NTA Warehouse\01 Incoming\Receiving Log_ZC.xlsm"
#     try:
#         data = pd.read_excel(file_path2)
#         logging.info(f"Loaded {data.shape[0]} rows from Excel.")
#         data['QTY'] = data['QTY'].fillna(1)
#         data.rename(columns={
#             'Date': 'entry_date',
#             'Inv# ': 'invoice_number',
#             'Box #': 'box_number',
#             'POD#': 'pod_number',
#             'Part#': 'part_number',
#             'SN#': 'serial_number',
#             'QTY': 'quantity'
#         }, inplace=True)
#         logging.info(f"Transformed data columns: {data.columns.tolist()}")
#         data.to_sql('receiving_log', db.engine, if_exists='replace', index=False)
#         logging.info("Data successfully inserted into the database.")
#         return True
#     except Exception as e:
#         logging.error(f"Error loading data: {e}")
#         return False


import logging
import pandas as pd
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine
from config import Config

# ——— Logging ———
logging.basicConfig(level=Config.LOG_LEVEL)

# ——— Flask App & DB Setup ———
app = Flask(__name__)
app.config.from_object(Config)
db = SQLAlchemy(app)

plain_engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)

def load_data(*args, **kwargs):
    """
    Reads the latest Excel snapshot and does a full replace-load
    into the receiving_log table on Supabase.
    """
    file_path = r"c:\Users\Admin\OneDrive - neousys-tech\Share NTA Warehouse\01 Incoming\Receiving Log_ZC.xlsm"
    try:
        # 1. Load & normalize
        df = pd.read_excel(file_path)
        logging.info(f"Loaded {df.shape[0]} rows from Excel.")

        df['QTY'] = df['QTY'].fillna(1)
        df.rename(..., inplace=True)
        # keep _all_ the columns you want in your table:
        wanted = [
            'entry_date', 'invoice_number', 'box_number', 'pod_number',
            'part_number','serial_number','quantity','Reference','Unnamed: 8'
        ]
        df = df[wanted]

        logging.info(f"Transformed columns: {df.columns.tolist()}")

        # 2. Replace-load into Supabase
        df.to_sql(
            'receiving_log',
            con=plain_engine,
            if_exists='replace',
            index=False,
            method='multi'
        )
        logging.info("Data successfully inserted into receiving_log.")
        return True

    except Exception as e:
        logging.error(f"Error loading data: {e}")
        return False

if __name__ == "__main__":
    # ensure tables exist, then load
    with app.app_context():
        db.create_all()
        success = load_data()
        if not success:
            logging.error("Initial load failed; check logs.")
    app.run(host='0.0.0.0', port=5000, debug=True)

