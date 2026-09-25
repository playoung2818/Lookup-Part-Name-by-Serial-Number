from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, String, Float, Date, Integer
from datetime import date

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


class WarehouseBorrowLog(db.Model):
    __tablename__ = 'warehouse_borrow_log'
    id = db.Column(db.Integer, primary_key=True)
    borrower = db.Column(db.String(255), nullable=False)
    item_number = db.Column(db.String(255), nullable=False)
    serial_number = db.Column(db.String(255), nullable=False, default='')
    borrowed_qty = db.Column(db.Integer, nullable=False)
    warehouse = db.Column(db.String(100), nullable=False)
    purpose = db.Column(db.Text, nullable=False, default='')
    borrow_date = db.Column(db.Date, nullable=False)
    returned_qty = db.Column(db.Integer, nullable=False, default=0)
    return_date = db.Column(db.Date)
    issued_by = db.Column(db.String(255), nullable=False, default='')
    version = db.Column(db.Integer, nullable=False, default=1)
    __mapper_args__ = {'version_id_col': version}
    __table_args__ = (
        db.CheckConstraint('borrowed_qty > 0', name='borrow_qty_positive'),
        db.CheckConstraint('returned_qty >= 0', name='return_qty_nonnegative'),
        db.CheckConstraint('return_date IS NULL OR return_date >= borrow_date', name='borrow_date_order'),
    )

    @property
    def borrow_id(self):
        return f'BR-{self.borrow_date:%y%m%d}-{self.id:03d}'

    @property
    def status(self):
        if self.returned_qty > self.borrowed_qty:
            return 'ERROR'
        if self.returned_qty == self.borrowed_qty:
            return 'RETURNED'
        return 'PARTIAL RETURN' if self.returned_qty > 0 else 'BORROWED'

    @property
    def duration_days(self):
        return ((self.return_date or date.today()) - self.borrow_date).days
