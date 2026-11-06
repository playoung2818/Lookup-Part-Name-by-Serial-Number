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


class Config:
    SQLALCHEMY_DATABASE_URI = database_uri(os.getenv('DATABASE_DSN'))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOG_LEVEL = logging.INFO
    PERMANENT_SESSION_LIFETIME = timedelta(days=365)
    RECEIVING_REFERENCE_PATH = os.getenv(
        'RECEIVING_REFERENCE_PATH',
        str(Path.home() / 'OneDrive - neousys-tech' / 'Share NTA Warehouse' / '01 Incoming' / 'POD-Reference.xlsx'))
    MRP_BASE_URL = os.getenv('MRP_BASE_URL', 'http://192.168.60.215:5002')
    MES_BASE_URL = os.getenv('MES_BASE_URL', 'http://192.168.60.215:5001')

