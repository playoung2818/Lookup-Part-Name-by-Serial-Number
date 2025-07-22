from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, String, Float, Date, Integer

db = SQLAlchemy()

class ReceivingLog(db.Model):
    __tablename__ = 'receiving_log'
    id = Column(Integer, primary_key=True, autoincrement=True)
    serial_number = db.Column(db.String(255), primary_key=True)
    entry_date    = db.Column(db.Date)
    invoice_number= db.Column(db.String(255))
    box_number    = db.Column(db.String(255))
    pod_number    = db.Column(db.String(255))
    part_number   = db.Column(db.String(255))
    quantity      = db.Column(db.Float)
    reference      = db.Column('Reference', db.Text) 

