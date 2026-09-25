"""Warehouse borrowing ledger: calculations mirror Warehouse_Borrowing_Log.xlsx."""
from datetime import date
import secrets
import re

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm.exc import StaleDataError

from models.models import db, WarehouseBorrowLog, ReceivingLog

borrow_log_bp = Blueprint('borrow_log', __name__, url_prefix='/warehouse-borrow-log')
STATUSES = ('BORROWED', 'PARTIAL RETURN', 'RETURNED', 'ERROR')
WAREHOUSES = ('WH01S', 'WH01X', 'WH01', 'WH10', 'Other')
PURPOSES = ('Engineering Testing', 'Troubleshooting', 'Sales Demo', 'Production Use', 'Internal Project', 'Other')
FIELDS = (
    ('borrower', 'Borrower', 'text', True),
    ('serial_number', 'Serial Number', 'text', False),
    ('item_number', 'Item Name / #', 'text', True),
    ('borrowed_qty', 'Borrowed Qty', 'number', True),
    ('warehouse', 'Warehouse', 'text', True),
    ('purpose', 'Purpose', 'text', False),
    ('borrow_date', 'Borrow Date', 'date', True),
    ('returned_qty', 'Returned Qty', 'number', True),
    ('return_date', 'Return Date', 'date', False),
    ('issued_by', 'Issued By', 'text', False),
)


@borrow_log_bp.get('/lookup-item')
def lookup_item():
    serial = request.args.get('serial_number', '').strip()
    serial = re.sub(r'^S/N\s*:?\s*', '', serial, flags=re.I).strip()
    if not serial or serial.upper() in ('NA', 'N/A', 'NONE'):
        return jsonify(found=False, message='Enter the item name manually for items without a serial number.')
    if len(serial) > 255:
        return jsonify(found=False, message='Serial number is too long.'), 400
    try:
        parts = db.session.execute(db.select(ReceivingLog.part_number).where(
            db.func.lower(db.func.trim(ReceivingLog.serial_number)) == serial.lower()
        ).distinct()).scalars().all()
        parts = sorted({part.strip() for part in parts if part and part.strip()})
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Borrow log serial lookup failed')
        return jsonify(found=False, message='Lookup is unavailable. You can enter the item name manually.'), 503
    if len(parts) > 1:
        return jsonify(found=False, message='This serial matches multiple items. Verify and enter the item name manually.'), 409
    if not parts:
        return jsonify(found=False, message='No matching item found. You can enter the item name manually.')
    return jsonify(found=True, item_name=parts[0], serial_number=serial)


def parse_record(form):
    values, errors = {}, []
    for name, label, kind, required in FIELDS:
        value = form.get(name, '').strip()
        if required and not value:
            errors.append(f'{label} is required.')
        if kind == 'number':
            try:
                value = int(value)
                if value < (1 if name == 'borrowed_qty' else 0) or value > 2147483647:
                    raise ValueError
            except ValueError:
                errors.append(f'{label} must be a whole number between {1 if name == "borrowed_qty" else 0} and 2147483647.')
                value = None
        elif kind == 'date':
            try:
                value = date.fromisoformat(value) if value else None
            except ValueError:
                errors.append(f'{label} must be a valid date.')
                value = None
        elif len(value) > (4000 if name == 'purpose' else 100 if name == 'warehouse' else 255):
            errors.append(f'{label} is too long.')
        values[name] = value
    if values['borrow_date'] and values['return_date'] and values['return_date'] < values['borrow_date']:
        errors.append('Return Date cannot be before Borrow Date.')
    return values, errors


@borrow_log_bp.get('/')
def index():
    records = db.session.execute(db.select(WarehouseBorrowLog).order_by(WarehouseBorrowLog.id.desc())).scalars().all()
    open_count = sum(r.status in ('BORROWED', 'PARTIAL RETURN') for r in records)
    total_qty = sum(r.borrowed_qty for r in records)
    query = request.args.get('q', '').strip()
    status = request.args.get('status', 'NOT_RETURNED')
    if query:
        records = [r for r in records if query.casefold() in ' '.join(str(getattr(r, key) or '') for key in
                   ('borrow_id', 'borrower', 'item_number', 'serial_number', 'warehouse', 'purpose', 'issued_by')).casefold()]
    if status == 'NOT_RETURNED':
        records = [r for r in records if r.status != 'RETURNED']
    elif status:
        records = [r for r in records if r.status == status]
    return render_template('borrow_log.html', records=records, open_count=open_count,
                           total_qty=total_qty, query=query, status=status, statuses=STATUSES)


@borrow_log_bp.route('/new', methods=['GET', 'POST'])
@borrow_log_bp.route('/<int:record_id>/edit', methods=['GET', 'POST'])
def edit(record_id=None):
    if record_id is None and request.method == 'GET':
        return redirect(url_for('borrow_log.batch'))
    record = db.get_or_404(WarehouseBorrowLog, record_id) if record_id else None
    session.setdefault('borrow_csrf', secrets.token_urlsafe(32))
    errors, code = [], 200
    if request.method == 'POST':
        if not secrets.compare_digest(session['borrow_csrf'], request.form.get('csrf_token', '')):
            abort(400, description='This form has expired. Reload the page and try again.')
        values, errors = parse_record(request.form)
        if record and request.form.get('version') != str(record.version):
            errors.append('Someone else updated this record. Reload it before saving your changes.')
            code = 409
        if not errors:
            try:
                if record is None:
                    record = WarehouseBorrowLog()
                    db.session.add(record)
                for key, value in values.items():
                    setattr(record, key, value)
                db.session.commit()
                return redirect(url_for('borrow_log.index'), code=303)
            except StaleDataError:
                db.session.rollback()
                errors.append('Someone else updated this record. Reload it before saving your changes.')
                code = 409
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception('Could not save warehouse borrow record')
                errors.append('The record could not be saved. Please try again.')
                code = 503
        elif code == 200:
            code = 400
        data = request.form
    else:
        data = {name: getattr(record, name) if record else '' for name, *_ in FIELDS}
        if not record:
            data.update(borrow_date=date.today(), borrowed_qty=1, returned_qty=0, warehouse='WH01S')
        data['version'] = record.version if record else ''
    return render_template('borrow_form.html', record=record, data=data, errors=errors,
                           fields=FIELDS, warehouses=WAREHOUSES, purposes=PURPOSES), code


@borrow_log_bp.route('/new-multiple', methods=['GET', 'POST'])
def batch():
    session.setdefault('borrow_csrf', secrets.token_urlsafe(32))
    entry_names = ('serial_number', 'item_number', 'borrowed_qty', 'warehouse', 'purpose', 'borrower', 'borrow_date')
    entry_fields = [next(field for field in FIELDS if field[0] == name) for name in entry_names]
    defaults = dict(borrowed_qty='1', warehouse='WH01S', borrow_date=date.today().isoformat())
    rows = [dict(defaults) for _ in range(5)]
    errors, code = [], 200
    if request.method == 'POST':
        if not secrets.compare_digest(session['borrow_csrf'], request.form.get('csrf_token', '')):
            abort(400, description='This form has expired. Reload the page and try again.')
        columns = {name: request.form.getlist(name) for name in entry_names}
        count = len(columns['serial_number'])
        if not 1 <= count <= 100 or any(len(values) != count for values in columns.values()):
            abort(400, description='Submit between 1 and 100 complete rows.')
        rows = [{name: values[i] for name, values in columns.items()} for i in range(count)]
        records = []
        for number, row in enumerate(rows, 1):
            # Rows containing only shared details/defaults are unused grid rows.
            if not row['serial_number'].strip() and not row['item_number'].strip():
                continue
            values, row_errors = parse_record(dict(row, returned_qty='0', return_date='', issued_by=''))
            errors.extend(f'Row {number}: {error}' for error in row_errors)
            if not row_errors:
                records.append(WarehouseBorrowLog(**values))
        if not records and not errors:
            errors.append('Enter at least one item. Each used row needs a serial number or an item name.')
        if errors:
            code = 400
        else:
            try:
                db.session.add_all(records)
                db.session.commit()
                flash(f'Saved {len(records)} borrow records.')
                return redirect(url_for('borrow_log.index'), code=303)
            except SQLAlchemyError:
                db.session.rollback()
                current_app.logger.exception('Could not save multiple borrow records')
                errors.append('No records were saved. Please try again.')
                code = 503
    return render_template('borrow_batch.html', rows=rows, errors=errors, fields=entry_fields,
                           defaults=defaults, warehouses=WAREHOUSES, purposes=PURPOSES), code
