import logging
import os
from pathlib import Path
from datetime import timedelta

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

# Load local settings for both `python app.py` and Flask/WSGI imports.
# Deployment environment variables take precedence over the local file.
load_dotenv(Path(__file__).resolve().with_name('.env'), override=False)


def database_uri(value):
    if not value:
        return value
    url = make_url(value)
    if url.host in ('localhost', '127.0.0.1', '::1'):
        return url.set(host='192.168.60.215').render_as_string(hide_password=False)
    return value


SHARE_ROOT = Path.home() / 'OneDrive - neousys-tech' / 'Share NTA Warehouse'


class Config:
    SQLALCHEMY_DATABASE_URI = database_uri(os.getenv('DATABASE_DSN'))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOG_LEVEL = logging.INFO
    PERMANENT_SESSION_LIFETIME = timedelta(days=365)
    RECEIVING_REFERENCE_PATH = os.getenv(
        'RECEIVING_REFERENCE_PATH', str(SHARE_ROOT / '01 Incoming' / 'POD-Reference.xlsx'))
    # Shared document folders resolve from the current user's home unless overridden.
    INVOICE_DIR = os.getenv('INVOICE_DIR', str(SHARE_ROOT / '01 Incoming' / 'HQ Shipping Documents'))
    OUTGOING_DIR = os.getenv('OUTGOING_DIR', str(SHARE_ROOT / '03 Outgoing (WOOF)'))
    # /api/sheet-update is disabled unless a shared bearer token is configured.
    SHEET_UPDATE_TOKEN = os.getenv('SHEET_UPDATE_TOKEN', '')
    RECEIVING_INCOMING_TEMPLATE_PATH = os.getenv(
        'RECEIVING_INCOMING_TEMPLATE_PATH',
        str(SHARE_ROOT / '01 Incoming' / 'Incoming Form Template.docx'))
    MRP_BASE_URL = os.getenv('MRP_BASE_URL', 'http://192.168.60.215:5002')
    MES_BASE_URL = os.getenv('MES_BASE_URL', 'http://192.168.60.215:5001')
    # File shares the web app must be able to open (work-order PDFs). Checked by /health
    # and at startup. Semicolon-separated; empty disables the check.
    # SwitchBot Hub 2 humidity panel on the homepage (functions/switchbot.py).
    SWITCHBOT_TOKEN = os.getenv('SWITCHBOT_TOKEN', '').strip()
    SWITCHBOT_SECRET = os.getenv('SWITCHBOT_SECRET', '').strip()
    SWITCHBOT_DEVICE_ID = os.getenv('SWITCHBOT_DEVICE_ID', '').strip()  # blank = first Hub 2
    SWITCHBOT_HUMIDIFIER_ID = os.getenv('SWITCHBOT_HUMIDIFIER_ID', '').strip()  # blank = first Evaporative Humidifier
    SWITCHBOT_POLL_SECONDS = int(os.getenv('SWITCHBOT_POLL_SECONDS', '300'))
    CLIMATE_OK_MIN = float(os.getenv('CLIMATE_OK_MIN', '40'))  # % RH, inclusive
    CLIMATE_OK_MAX = float(os.getenv('CLIMATE_OK_MAX', '80'))
    REQUIRED_SHARES = [share for share in os.getenv('RECEIVING_REQUIRED_SHARES', r'\\quickbook2024\d').split(';') if share]

