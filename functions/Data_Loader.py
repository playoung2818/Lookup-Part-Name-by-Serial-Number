import logging
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy import text
from dateutil.parser import parse
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Set up engine and Google Sheets auth
engine = create_engine('postgresql://postgres:Czheyuan0227%40@localhost:5432/File_Log')

scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name(
    r'c:\Users\Admin\Desktop\receivinglogsync-a87f27ccfa24.json', scope)
client = gspread.authorize(creds)

def load_data(sheet_name: str) -> bool:
    try:
        sheet = client.open(sheet_name).sheet1
        data = sheet.get_all_records()
        df = pd.DataFrame(data)

        # Drop unnecessary columns like 'Reference'
        df = df.drop(columns=['Reference'], errors='ignore')

        # Fill missing quantities and parse entry dates
        df['QTY'] = df['QTY'].fillna(1)
        df.rename(columns={
            'Date': 'entry_date',
            'Inv# ': 'invoice_number',
            'Box #': 'box_number',
            'POD#': 'pod_number',
            'Part#': 'part_number',
            'SN#': 'serial_number',
            'QTY': 'quantity'
        }, inplace=True)

        # Clean and convert data
        df = df[df['serial_number'].astype(str).str.strip() != '']
        df['entry_date'] = df['entry_date'].apply(lambda d: parse(d).date() if d else None)
        df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(1)

        # Append (not delete or replace)
        df.to_sql('receiving_log', engine, if_exists='append', index=False)
        logging.info(f"{len(df)} rows inserted into receiving_log from Google Sheet.")
        return True

    except Exception as e:
        logging.error(f"Error loading data from Google Sheet: {e}")
        return False



