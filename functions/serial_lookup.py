"""Normalized, read-only receiving serial lookup shared by the UI and API."""
from sqlalchemy import func

from models.models import ReceivingLog

PLACEHOLDERS = {'', 'NA', 'N/A', 'NAN', 'NONE'}
MAX_MATCHES = 50


def serial_key(value):
    return str(value or '').strip().upper()


def find_receiving_serial(serial, limit=MAX_MATCHES):
    """All matches regardless of case/surrounding spaces, newest first.

    Placeholder serials (blank/NA) are not searchable: thousands of rows share them.
    The expression matches scripts/receiving_lookup_indexes.sql.
    """
    key = serial_key(serial)
    if key in PLACEHOLDERS:
        return []
    return (ReceivingLog.query
            .filter(func.upper(func.trim(ReceivingLog.serial_number)) == key)
            .order_by(ReceivingLog.id.desc())
            .limit(limit)
            .all())


def record_dict(record):
    return {
        'id': record.id,
        'serial_number': (record.serial_number or '').strip(),
        'part_name': record.part_number,
        'entry_date': record.entry_date.strftime('%m-%d-%Y') if record.entry_date else None,
        'invoice_number': record.invoice_number or '',
        'pod_number': record.pod_number or '',
        'box_number': record.box_number or '',
    }
