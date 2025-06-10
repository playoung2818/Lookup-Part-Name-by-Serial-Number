from flask import Blueprint, request, jsonify, current_app
from models.models import ReceivingLog

api_bp = Blueprint('api', __name__)

@api_bp.route('/api/lookup', methods=['GET'])
def api_lookup():
    serial_number = request.args.get('serial_number', '').strip()
    if not serial_number:
        return jsonify({"error": "Missing serial_number"}), 400

    db = current_app.extensions['sqlalchemy'].db
    try:
        found_entry = db.session.query(ReceivingLog).filter_by(serial_number=serial_number).first()
        if found_entry:
            return jsonify({
                "serial_number": found_entry.serial_number,
                "part_name": found_entry.part_number,
                "entry_date": found_entry.entry_date.strftime('%m-%d-%Y') if found_entry.entry_date else None
            }), 200
        else:
            return jsonify({"error": "Not found"}), 404
    except Exception as e:
        current_app.logger.error(f"API error: {e}")
        return jsonify({"error": "Internal error"}), 500


@api_bp.route('/api/sheet-update', methods=['POST'])
def sheet_update():
    db = current_app.extensions['sqlalchemy'].db
    try:
        data = request.get_json()
        serial = data.get("serial_number")
        if not serial:
            return jsonify({"error": "Missing serial_number"}), 400

        entry = db.session.get(ReceivingLog, serial)
        if entry:
            for field in ['entry_date', 'invoice_number', 'box_number', 'pod_number', 'part_number', 'quantity']:
                setattr(entry, field, data.get(field))
        else:
            entry = ReceivingLog(**data)
            db.session.add(entry)

        db.session.commit()
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        current_app.logger.error(f"Sheet update error: {e}")
        return jsonify({"error": "Internal error"}), 500
