import secrets
from datetime import date
from math import isfinite

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from models.models import db, ReceivingLog
from functions.serial_lookup import find_receiving_serial, record_dict, serial_key, PLACEHOLDERS

api_bp = Blueprint('api', __name__)

@api_bp.route('/climate', methods=['GET'])
def climate():
    """Hub 2 humidity for the homepage panel: latest reading and chart points."""
    from functions.switchbot import chart_data
    ok_range = (current_app.config['CLIMATE_OK_MIN'], current_app.config['CLIMATE_OK_MAX'])
    recorder = current_app.extensions.get('climate_recorder')
    if request.args.get('refresh') == '1' and recorder is not None:
        recorder.refresh()  # fresh Hub 2 reading; skipped if one was taken in the last minute
    try:
        data = chart_data(db.engine, request.args.get('range', '24h'), ok_range=ok_range)
    except SQLAlchemyError:
        current_app.logger.exception('Climate readings unavailable')
        return jsonify(error='Humidity history is unavailable.'), 503
    response = jsonify(data)
    response.headers['Cache-Control'] = 'no-store'
    return response


def humidifier_service():
    """One shared Humidifier (cached status, rate-limited commands) per app."""
    from functions.switchbot import Humidifier
    token, secret = current_app.config.get('SWITCHBOT_TOKEN'), current_app.config.get('SWITCHBOT_SECRET')
    if not token or not secret:
        return None
    if 'humidifier' not in current_app.extensions:
        current_app.extensions['humidifier'] = Humidifier(token, secret, current_app.config.get('SWITCHBOT_HUMIDIFIER_ID', ''))
    return current_app.extensions['humidifier']


@api_bp.route('/humidifier', methods=['GET'])
def humidifier():
    """Warehouse humidifier power/mode for the homepage (read-only; no control from this site)."""
    from functions.switchbot import SwitchBotError
    service = humidifier_service()
    if service is None:
        return jsonify(error='SwitchBot is not configured.'), 503
    try:
        status = service.status(force=request.args.get('refresh') == '1')
    except (SwitchBotError, OSError) as error:
        current_app.logger.warning('Humidifier status unavailable: %s', error)
        return jsonify(error='Humidifier status is unavailable.'), 503
    response = jsonify(status)
    response.headers['Cache-Control'] = 'no-store'
    return response


SHEET_FIELDS = ('entry_date', 'invoice_number', 'box_number', 'pod_number', 'part_number', 'quantity')


@api_bp.route('/lookup', methods=['GET'])
def api_lookup():
    serial_number = request.args.get('serial_number', '').strip()
    if not serial_number:
        return jsonify({"error": "Missing serial_number"}), 400
    if len(serial_number) > 255:
        return jsonify({"error": "serial_number is too long"}), 400
    if serial_key(serial_number) in PLACEHOLDERS:
        return jsonify({"error": "Blank/NA placeholders are not searchable"}), 400
    try:
        matches = [record_dict(record) for record in find_receiving_serial(serial_number)]
    except SQLAlchemyError:
        current_app.logger.exception('API serial lookup failed')
        return jsonify({"error": "Internal error"}), 500
    if not matches:
        return jsonify({"error": "Not found"}), 404
    # Top-level fields keep the original response shape (newest match).
    first = matches[0]
    return jsonify({"serial_number": first['serial_number'], "part_name": first['part_name'],
                    "entry_date": first['entry_date'], "match_count": len(matches),
                    "matches": matches}), 200


def authorized():
    expected = current_app.config.get('SHEET_UPDATE_TOKEN') or ''
    supplied = request.headers.get('Authorization', '')
    if not expected or not supplied.startswith('Bearer '):
        return False
    token = supplied[len('Bearer '):]
    return token.isascii() and secrets.compare_digest(token, expected)


def parse_sheet_values(data):
    values = {}
    for field in SHEET_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if field == 'entry_date':
            if value in (None, ''):
                value = None
            else:
                try:
                    value = date.fromisoformat(str(value))
                except ValueError:
                    raise ValueError('entry_date must be YYYY-MM-DD.')
        elif field == 'quantity':
            if value in (None, ''):
                value = None
            else:
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    raise ValueError('quantity must be a number.')
                if not isfinite(value) or value <= 0:
                    raise ValueError('quantity must be a positive number.')
        else:
            if value is not None and not isinstance(value, (str, int)):
                raise ValueError(f'{field} must be text.')
            value = '' if value is None else str(value).strip()
            if len(value) > 255:
                raise ValueError(f'{field} is too long.')
        values[field] = value
    return values


@api_bp.route('/sheet-update', methods=['POST'])
def sheet_update():
    """Token-protected upsert of one receiving row by serial; no schema changes.

    Disabled unless SHEET_UPDATE_TOKEN is configured. Only whitelisted fields are
    accepted. Ambiguous serials (multiple rows) are rejected rather than guessed.
    """
    if not current_app.config.get('SHEET_UPDATE_TOKEN'):
        return jsonify({"error": "Sheet updates are disabled"}), 403
    if not authorized():
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Expected a JSON object"}), 400
    unknown = sorted(set(data) - set(SHEET_FIELDS) - {'serial_number'})
    if unknown:
        return jsonify({"error": "Unsupported fields: " + ", ".join(unknown)}), 400
    serial = data.get('serial_number')
    if not isinstance(serial, str) or serial_key(serial) in PLACEHOLDERS or len(serial.strip()) > 255:
        return jsonify({"error": "Missing or invalid serial_number"}), 400
    try:
        values = parse_sheet_values(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    try:
        entries = (ReceivingLog.query
                   .filter(func.upper(func.trim(ReceivingLog.serial_number)) == serial_key(serial))
                   .limit(2).all())
        if len(entries) > 1:
            return jsonify({"error": "Serial matches multiple receiving rows; update it in Receiving instead"}), 409
        if entries:
            entry, status = entries[0], 'updated'
            for field, value in values.items():
                setattr(entry, field, value)
        else:
            entry, status = ReceivingLog(serial_number=serial.strip(), **values), 'created'
            db.session.add(entry)
        db.session.commit()
        return jsonify({"status": "ok", "result": status, "id": entry.id}), 200
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Sheet update failed')
        return jsonify({"error": "Internal error"}), 500
