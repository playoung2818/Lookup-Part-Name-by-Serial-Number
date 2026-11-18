"""Read-only invoice export using the existing Incoming Form Word template."""
from collections import OrderedDict
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
import re
from zipfile import BadZipFile, ZipFile

from docx import Document
from docx.shared import Pt
from sqlalchemy import select

from functions.receiving_import import clean, receiving_table

HEADERS = ['Product Number', "Q'TY", 'S/N', 'From\n(Vendor or Customer)',
           'Invoice # or RMA #', 'IQC Result', 'IQC Remark']


def invoice_records(engine, invoice):
    """Exact invoice lookup; no workspace replacement, writes or schema setup."""
    invoice = clean(invoice)
    if not invoice or len(invoice) > 255:
        raise ValueError('Enter an exact invoice number, preserving leading zeros.')
    with engine.connect() as connection:
        table = receiving_table(connection)
        records = [dict(row) for row in connection.execute(select(table).where(
            table.c.invoice_number == invoice).order_by(table.c.id)).mappings()
            if clean(row['invoice_number']) == invoice]
    if not records:
        raise ValueError(f'No receiving records found for invoice {invoice}.')
    return records


def grouped_records(records):
    """Sum by box/part/POD, keep distinct serials and stable carton-range order."""
    groups = OrderedDict()
    for index, row in enumerate(records):
        key = tuple(clean(row.get(field)) for field in ('box_number', 'part_number', 'pod_number'))
        group = groups.setdefault(key, {'box': key[0], 'part': key[1], 'pod': key[2],
                                      'quantity': Decimal(0), 'serials': [], 'seen_serials': set(), 'first': index})
        try:
            quantity = Decimal(str(row.get('quantity') or 0))
            if not quantity.is_finite():
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            quantity = Decimal(0)
        group['quantity'] += quantity
        serial = clean(row.get('serial_number')) or 'NA'
        if serial not in group['seen_serials']:
            group['seen_serials'].add(serial)
            group['serials'].append(serial)

    def sort_key(group):
        match = re.match(r'^\s*(\d+)\s*--\s*(\d+)(?:-(\d+))?', group['box'])
        if match:
            carton, start, end = match.groups()
            return (0, int(carton), int(start), int(end or start), group['first'])
        return (1, 0, 0, 0, group['first'])

    return sorted(groups.values(), key=sort_key)


def template_content(upload=None, configured_path=''):
    if upload is not None and upload.filename:
        if Path(upload.filename).suffix.lower() != '.docx':
            raise ValueError('Choose a Word .docx template.')
        content = upload.read(10 * 1024 * 1024 + 1)
    else:
        path = Path(configured_path) if configured_path else None
        if path is None or not path.is_file():
            raise ValueError('Incoming Form Template.docx is unavailable. Upload a .docx template or configure RECEIVING_INCOMING_TEMPLATE_PATH.')
        if path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError('The Word template must be at most 10 MB.')
        content = path.read_bytes()
    if len(content) > 10 * 1024 * 1024:
        raise ValueError('The Word template must be at most 10 MB.')
    try:
        with ZipFile(BytesIO(content)) as archive:
            if sum(item.file_size for item in archive.infolist()) > 100 * 1024 * 1024:
                raise ValueError('Word template is too large after decompression.')
            if 'word/document.xml' not in archive.namelist():
                raise ValueError('Choose a valid Word .docx template.')
    except BadZipFile as exc:
        raise ValueError('Choose a valid Word .docx template.') from exc
    return content


def incoming_document(records, invoice, template, inspection_passed=False):
    try:
        document = Document(BytesIO(template))
    except (KeyError, ValueError, BadZipFile) as exc:
        raise ValueError('Cannot open this Word template. Choose a valid .docx document.') from exc
    groups = grouped_records(records)
    result = 'PASS' if inspection_passed else 'Pending'
    table = document.add_table(rows=1, cols=len(HEADERS))
    for cell, value in zip(table.rows[0].cells, HEADERS):
        cell.text = value
    for group in groups:
        quantity = format(group['quantity'], 'f')
        if '.' in quantity:
            quantity = quantity.rstrip('0').rstrip('.')
        values = [group['part'], quantity, ', '.join(group['serials']), 'Neousys Technology',
                  invoice, result, '']
        for cell, value in zip(table.add_row().cells, values):
            cell.text = str(value)
    document.add_paragraph()
    paragraph = document.add_paragraph(f'[Receiving & Inspection Result: {"Pass" if inspection_passed else "Pending"}]')
    run = paragraph.runs[0]
    run.bold = True
    run.font.size = Pt(14)
    run.font.name = 'Calibri'
    output = BytesIO()
    document.save(output)
    output.seek(0)
    return output, len(groups)
