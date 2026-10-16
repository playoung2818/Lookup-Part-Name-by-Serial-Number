import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# Load local settings for both `python app.py` and Flask/WSGI imports.
# Deployment environment variables take precedence over the local file.
load_dotenv(Path(__file__).resolve().with_name('.env'), override=False)


class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_DSN')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOG_LEVEL = logging.INFO
    MRP_BASE_URL = os.getenv('MRP_BASE_URL', 'http://127.0.0.1:5002')

