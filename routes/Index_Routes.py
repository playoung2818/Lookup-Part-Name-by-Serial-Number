from flask import Blueprint, render_template, request, abort, send_file, redirect, url_for, current_app
import json
import glob
from models.models import ReceivingLog
from sqlalchemy.sql import text
from tempfile import NamedTemporaryFile
import os
import re
import logging

from functions.utils import extract_useful_number
from functions.wo_lookup import find_by_serial
from functions.Validation import validate_sn_part_matches_via_api
from functions.serial_lookup import find_receiving_serial, record_dict, serial_key, PLACEHOLDERS
from routes.Inventory_Count_Routes import suggest_items
from sqlalchemy.exc import SQLAlchemyError
from models.models import db

index_bp = Blueprint('index', __name__)


def invoice_dir():
    return current_app.config['INVOICE_DIR']


def outgoing_dir():
    return current_app.config['OUTGOING_DIR']


def require_folder(path, label):
    if not path or not os.path.isdir(path):
        current_app.logger.warning('%s folder unavailable: %s', label, path)
        abort(503, description=f'The {label} folder is unavailable. Check OneDrive sync or the {label.upper()}_DIR setting.')
    return os.path.realpath(path)


def inside(base, path):
    try:
        return os.path.commonpath([base, os.path.realpath(path)]) == base
    except ValueError:
        return False


def _deduplicate_outgoing_rows(rows):
    def normalized(value):
        return str(value).strip().casefold() if value is not None else ""

    def completeness(row):
        return (
            bool(normalized(row.get("Invoice Date"))),
            sum(bool(normalized(value)) for value in row.values()),
        )

    unique = {}
    for index, source in enumerate(rows):
        row = dict(source)
        # Customer aliases can differ between sources for the same shipment.
        key = tuple(normalized(row.get(field)) for field in (
            "WO/SO #", "Invoice#", "Outgoing Form#"
        ))
        if not all(key):
            # Incomplete identifiers cannot safely establish a duplicate.
            key = (index,)
        if key not in unique:
            unique[key] = row
            continue
        existing = unique[key]
        preferred, other = (row, existing) if completeness(row) > completeness(existing) else (existing, row)
        unique[key] = {
            field: value if normalized(value) else other.get(field)
            for field, value in preferred.items()
        }
    return list(unique.values())


def _is_vendor_name(invoice_number):
    # The receiving log has no separate vendor field; name-only values have no digits.
    invoice_number = (invoice_number or "").strip()
    return bool(invoice_number) and not any(char.isdigit() for char in invoice_number)


def _is_pl_pdf(file_path):
    file_name = os.path.basename(file_path)
    if not file_name.lower().endswith(".pdf"):
        return False
    return re.search(r"(^|[_\-\s])pl([_\-\s]|$)", file_name, flags=re.IGNORECASE) is not None


def _invoice_match_priority(file_path, invoice_number):
    file_name = os.path.basename(file_path)
    file_name_lower = file_name.lower()
    invoice_lower = invoice_number.lower()

    # Prefer browser-renderable invoice PDFs over spreadsheets/other exports.
    if file_name_lower == f"invoice_nta_{invoice_lower}.pdf":
        return (0, file_name_lower)
    if file_name_lower.endswith(".pdf") and f"invoice_nta_{invoice_lower}" in file_name_lower:
        return (1, file_name_lower)
    if file_name_lower.endswith(".pdf") and "invoice" in file_name_lower:
        return (2, file_name_lower)
    if file_name_lower.endswith(".pdf"):
        return (3, file_name_lower)
    return (4, file_name_lower)


def _serial_variants(serial):
    serial = (serial or "").strip()
    if not serial:
        return set()

    variants = {serial, serial.upper(), serial.lower()}
    extracted = extract_useful_number(serial)
    if extracted:
        variants.update({extracted, extracted.upper(), extracted.lower()})
    return variants


def _sn_field_variants(sn_field):
    variants = set()
    tokens = [
        token.strip()
        for token in re.split(r"[,;\n\r\t]+", str(sn_field))
        if token and token.strip()
    ]

    for token in tokens:
        variants.update(_serial_variants(token))

        # Handle serials embedded in prose like "SN: Q0700370" or "Serial No Q0700370".
        compact_matches = re.findall(r"[A-Za-z0-9-]{4,}", token)
        for match in compact_matches:
            variants.update(_serial_variants(match))

    return variants


def _order_lookup_variants(order_id):
    order_id = (order_id or "").strip()
    if not order_id:
        return []

    variants = [order_id]
    match = re.search(r"^WO\d{2}-(\d+)$", order_id, flags=re.IGNORECASE)
    if match:
        variants.append(f"SO-{match.group(1)}")
    return variants

def used_history(serial):
    """wo_details records whose product serial fields contain this exact serial,
    with matching outgoing records. Raises on database errors."""
    search_variants = sorted(_serial_variants(serial), key=len, reverse=True)

    rows = find_by_serial(search_variants)

    def row_has_exact_serial(row, serial):
        search_variants = _serial_variants(serial)
        if not search_variants:
            return False

        product_details = row.get("product_details")
        if product_details is None:
            return False
        if isinstance(product_details, str):
            try:
                product_details = json.loads(product_details)
            except Exception:
                raw_lower = product_details.lower()
                return any(variant.lower() in raw_lower for variant in search_variants)
        if isinstance(product_details, dict):
            product_details = [product_details]
        if not isinstance(product_details, list):
            return False

        for item in product_details:
            if not isinstance(item, dict):
                continue
            sn_field = item.get("sn")
            if not sn_field:
                continue
            if _sn_field_variants(sn_field) & search_variants:
                return True
        return False

    word_serial_results = [row for row in rows if row_has_exact_serial(row, serial)]

    def extract_eight_digits(file_name):
        if not file_name:
            return ""
        match = re.search(r"\b(\d{8})\b", str(file_name))
        return match.group(1) if match else ""

    for row in word_serial_results:
        file_name = row.get("file_name")
        order_id = row.get("order_id")
        eight_digits = extract_eight_digits(file_name)

        where_clauses = []
        params = {}
        for idx, order_variant in enumerate(_order_lookup_variants(order_id)):
            key = f"order_id_{idx}"
            where_clauses.append(f"\"WO/SO #\" ILIKE :{key}")
            params[key] = f"%{order_variant}%"
        if eight_digits:
            where_clauses.append("\"WO/SO #\" ILIKE :eight_digits")
            params["eight_digits"] = f"%{eight_digits}%"

        row["outgoing_info"] = []
        if where_clauses:
            try:
                sql = (
                    "SELECT \"WO/SO #\", \"Customer\", \"Invoice#\", "
                    "\"Outgoing Form#\", \"Invoice Date\" "
                    "FROM public.outgoing_records "
                    f"WHERE {' OR '.join(where_clauses)}"
                )
                outgoing_rows = ReceivingLog.query.session.execute(
                    text(sql), params
                ).mappings().all()
                row["outgoing_info"] = _deduplicate_outgoing_rows(outgoing_rows)
            except Exception as outgoing_error:
                logging.error(
                    "Error querying outgoing info for word file %s: %s",
                    file_name,
                    outgoing_error
                )
    return word_serial_results

ORDER_PATTERN = r'(?:(?:SO\s*-?\s*)|(?:WO\d{2}\s*-\s*))?(\d{8})'


@index_bp.get('/lookup')
def lookup():
    """One box, one page: serial number, SO number and inventory item results together."""
    from routes.Inventory_Count_Routes import inventory_data
    from functions.so_status import find_so_status
    from functions.wo_lookup import find_work_orders
    query = request.args.get('q', '').strip()
    if not query:
        return redirect(url_for('index.index'))
    if len(query) > 255:
        abort(400)

    order = re.fullmatch(ORDER_PATTERN, query, re.I)

    # 1. Serial number: receiving records and used history. SO numbers are not
    # serials (the legacy serial clean-up would reduce "SO-..." to "O" and over-match).
    serial = {'records': [], 'history': [], 'error': None, 'placeholder': serial_key(query) in PLACEHOLDERS}
    if not serial['placeholder'] and not order:
        try:
            serial['records'] = [dict(record_dict(r), invoice_is_vendor_name=_is_vendor_name(r.invoice_number))
                                 for r in find_receiving_serial(query)]
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('Receiving lookup failed')
            serial['error'] = 'Receiving records are unavailable.'
        try:
            serial['history'] = used_history(query)
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Used history lookup failed')
            serial['error'] = (serial['error'] + ' ' if serial['error'] else '') + 'Used history is unavailable.'

    # 2. SO number: workflow status and work-order records.
    so = {'number': f'SO-{order.group(1)}' if order else None, 'workflow': None, 'records': [], 'error': None}
    if order:
        try:
            so['workflow'] = find_so_status(so['number'])
        except Exception:
            current_app.logger.exception('SO workflow lookup failed')
            so['error'] = 'Workflow status is unavailable.'
        try:
            so['records'] = find_work_orders('%' + order.group(1) + '%')
        except Exception:
            current_app.logger.exception('Work order lookup failed')
            so['error'] = (so['error'] + ' ' if so['error'] else '') + 'Work-order records are unavailable.'

    # 3. Inventory item: exact item stock, plus other matching items.
    item = {'name': None, 'data': None, 'matches': [], 'error': None}
    if not order:
        item['matches'] = suggest_items(query)
        key = query.casefold()
        item['name'] = next((name for name in item['matches'] if name.strip().casefold() == key), None)
        if item['name']:
            try:
                item['data'] = inventory_data(item['name'])
            except Exception:
                current_app.logger.warning('MRP inventory unavailable for %s', item['name'])
                item['error'] = 'Stock quantities are unavailable from MRP.'
        item['matches'] = [name for name in item['matches'] if name != item['name']]

    found = bool(serial['records'] or serial['history'] or so['workflow'] or so['records']
                 or item['name'] or item['matches'])
    return render_template('lookup_results.html', query=query, serial=serial, so=so,
                           inventory=item, found=found, search_value=query)


@index_bp.get('/serial-search')
def serial_search():
    """Former sidebar landing page; the homepage search replaces it."""
    return redirect(url_for('index.index'))


@index_bp.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'GET' and not request.args.get('serial_number', '').strip():
        return render_template('home.html', home_page=True)
    serial_number = ""
    part_name = ""
    entry_date = ""
    invoice_number = ""
    pod_number = ""
    receiving_matches = []
    found = False
    message = ""
    prune_input = ""
    pruned_serials_text = ""
    word_serial_query = ""
    word_serial_results = []
    match_results = []

    refresh_status = request.args.get('refresh_status')
    refresh_message = request.args.get('refresh_message')

    lookup_data = request.form if request.method == 'POST' else request.args
    if request.method == 'POST' or 'serial_number' in request.args:
        if 'serial_number' in lookup_data:
            serial_number = lookup_data.get('serial_number', '').strip()
            if serial_number:
                try:
                    if serial_key(serial_number) in PLACEHOLDERS:
                        message = "Enter an actual serial number; blank/NA placeholders are not searchable."
                    receiving_matches = [
                        dict(record_dict(record), invoice_is_vendor_name=_is_vendor_name(record.invoice_number))
                        for record in find_receiving_serial(serial_number)]
                    if receiving_matches:
                        first = receiving_matches[0]
                        part_name = first['part_name']
                        entry_date = first['entry_date'] or ""
                        invoice_number = first['invoice_number']
                        pod_number = first['pod_number']
                        message = ("Part Found!" if len(receiving_matches) == 1 else
                                   f"{len(receiving_matches)} receiving records match this serial number.")
                        found = True
                    else:
                        message = message or "No part found with that serial number."
                        found = False
                except Exception as e:
                    logging.error(f"Error looking up serial number: {e}")
                    message = "Error occurred during lookup."
                    found = False

        if request.method == 'POST' and 'prune_input' in lookup_data:
            prune_input = lookup_data.get('prune_input', '').strip()
            if prune_input:
                try:
                    raw_serials = re.split(r'[,\n]+', prune_input)
                    pruned_serials = [extract_useful_number(sn.strip()) for sn in raw_serials if sn.strip()]
                    pruned_serials_text = "\n".join([sn for sn in pruned_serials if sn])
                except Exception as e:
                    logging.error(f"Error pruning serial numbers: {e}")
                    pruned_serials_text = "Error occurred during pruning."

        if 'word_serial_query' in lookup_data or 'serial_number' in lookup_data:
            word_serial_query = lookup_data.get('serial_number', lookup_data.get('word_serial_query', '')).strip()
            if word_serial_query:
                try:
                    word_serial_results = used_history(word_serial_query)
                except Exception as e:
                    logging.error(f"Error querying wo_details: {e}")
                    word_serial_results = []

        if 'word_file' in request.files:
            uploaded_file = request.files['word_file']
            if uploaded_file and uploaded_file.filename.endswith('.docx'):
                try:
                    with NamedTemporaryFile(delete=False, suffix='.docx') as tmp:
                        uploaded_file.save(tmp.name)
                        match_results = validate_sn_part_matches_via_api(tmp.name)
                        os.unlink(tmp.name)
                except Exception as e:
                    logging.error(f"Error processing uploaded file: {e}")
                    match_results = []

    item_suggestions = []
    if serial_number and not receiving_matches and not word_serial_results:
        item_suggestions = suggest_items(serial_number)

    return render_template('index.html',
                           item_suggestions=item_suggestions,
                           serial_number=serial_number,
                           part_name=part_name,
                           entry_date=entry_date,
                           invoice_number=invoice_number,
                           pod_number=pod_number,
                           receiving_matches=receiving_matches,
                           invoice_is_vendor_name=_is_vendor_name(invoice_number),
                           found=found,
                           message=message,
                           prune_input=prune_input,
                           pruned_serials_text=pruned_serials_text,
                           word_serial_query=word_serial_query,
                           word_serial_results=word_serial_results,
                           match_results=match_results,
                           refresh_status=refresh_status,
                           refresh_message=refresh_message)

# Arbitrary-path /word-preview and /word-download routes were removed: they
# served any .docx path supplied in the URL. Documents are served only from
# configured folders below, or by database record ID in Work_Order_Routes.


@index_bp.route('/invoice-download', methods=['GET'])
def invoice_download():
    invoice_number = request.args.get('invoice_number', '').strip()
    if (not invoice_number or len(invoice_number) > 255 or _is_vendor_name(invoice_number)
            or re.search(r'[\\/:]|\.\.', invoice_number)):
        abort(400)
    base = require_folder(invoice_dir(), 'invoice')
    pattern = os.path.join(base, f"*{glob.escape(invoice_number)}*")
    matches = [
        p for p in glob.glob(pattern)
        if os.path.isfile(p) and not _is_pl_pdf(p) and inside(base, p)
    ]
    if not matches:
        abort(404)

    selected = sorted(
        matches,
        key=lambda path: _invoice_match_priority(path, invoice_number)
    )[0]

    return send_file(selected, as_attachment=False)


@index_bp.route('/outgoing-invoice', methods=['GET'])
def outgoing_invoice():
    invoice_number = request.args.get('invoice_number', '').strip()
    outgoing_form = request.args.get('outgoing_form', '').strip()
    if not invoice_number and not outgoing_form:
        abort(400)
    if len(invoice_number) > 255 or len(outgoing_form) > 255:
        abort(400)

    base = require_folder(outgoing_dir(), 'outgoing')
    search_terms = [term.lower() for term in [outgoing_form, invoice_number] if term]
    matches = []
    for root, _, files in os.walk(base):
        for name in sorted(files):
            name_lower = name.lower()
            if any(term in name_lower for term in search_terms):
                full_path = os.path.join(root, name)
                if not _is_pl_pdf(full_path) and inside(base, full_path):
                    matches.append(full_path)

    if not matches:
        abort(404)

    pdf_matches = [p for p in matches if p.lower().endswith(".pdf")]
    selected = pdf_matches[0] if pdf_matches else matches[0]
    return send_file(selected, as_attachment=False)
