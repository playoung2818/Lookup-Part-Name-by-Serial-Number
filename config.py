import logging

# class Config:
#     SQLALCHEMY_DATABASE_URI = 'postgresql://postgres:Czheyuan0227%40@localhost:5432/File_Log'
#     SQLALCHEMY_TRACK_MODIFICATIONS = False
#     LOG_LEVEL = logging.INFO



class Config:
    SQLALCHEMY_DATABASE_URI = (
        "postgresql://postgres.avcznjglmqhmzqtsrlfg:"
        "Czheyuan0227@aws-0-us-east-2.pooler.supabase.com:6543/postgres"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOG_LEVEL = logging.INFO

