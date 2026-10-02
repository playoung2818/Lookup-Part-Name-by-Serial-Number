import logging
import os

class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_DSN",
        "postgresql://postgres:Ry_K9sOTbTUXWI8TnOCQwEexChYTOpDm8RG3PmfNV9HKI_hnJlGvQvANUIdGpJxA@127.0.0.1:5432/postgres",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOG_LEVEL = logging.INFO

