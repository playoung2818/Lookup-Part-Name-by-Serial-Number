from flask import Blueprint, render_template, request, jsonify, abort, send_file
import json
import glob
import re
from models.models import ReceivingLog
from sqlalchemy.sql import text
from tempfile import NamedTemporaryFile
import os
import re
import logging

from functions.utils import extract_useful_number
from functions.Validation import validate_sn_part_matches_via_api 
try:
    from docx import Document
except Exception:
    Document = None

index_bp = Blueprint('index', __name__)
INVOICE_DIR = r"C:\Users\Admin\OneDrive - neousys-tech\Share NTA Warehouse\01 Incoming\HQ Shipping Documents"
OUTGOING_DIR = r"C:\Users\Admin\OneDrive - neousys-tech\Share NTA Warehouse\03 Outgoing (WOOF)"


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

@index_bp.route('/', methods=['GET', 'POST'])
def index():
    serial_number = ""
    part_name = ""
    entry_date = ""
    invoice_number = ""
    pod_number = ""
    found = False
    message = ""
    prune_input = ""
    pruned_serials_text = ""
    word_serial_query = ""
    word_serial_results = []
    match_results = []

    refresh_status = request.args.get('refresh_status')
    refresh_message = request.args.get('refresh_message')

    if request.method == 'POST':
        if 'serial_number' in request.form:
            serial_number = request.form.get('serial_number', '').strip()
            if serial_number:
                try:
                    found_entry = ReceivingLog.query.filter_by(serial_number=serial_number).first()
                    if found_entry:
                        part_name = found_entry.part_number
                        entry_date = found_entry.entry_date.strftime('%m-%d-%Y') if found_entry.entry_date else ""
                        invoice_number = found_entry.invoice_number or ""
                        pod_number = found_entry.pod_number or ""
                        message = "Part Found!"
                        found = True
                    else:
                        message = "No part found with that serial number."
                        found = False
                except Exception as e:
                    logging.error(f"Error looking up serial number: {e}")
                    message = "Error occurred during lookup."
                    found = False

        if 'prune_input' in request.form:
            prune_input = request.form.get('prune_input', '').strip()
            if prune_input:
                try:
                    raw_serials = re.split(r'[,\n]+', prune_input)
                    pruned_serials = [extract_useful_number(sn.strip()) for sn in raw_serials if sn.strip()]
                    pruned_serials_text = "\n".join([sn for sn in pruned_serials if sn])
                except Exception as e:
                    logging.error(f"Error pruning serial numbers: {e}")
                    pruned_serials_text = "Error occurred during pruning."

        if 'word_serial_query' in request.form or 'serial_number' in request.form:
            word_serial_query = request.form.get('serial_number', request.form.get('word_serial_query', '')).strip()
            if word_serial_query:
                try:
                    search_variants = sorted(_serial_variants(word_serial_query), key=len, reverse=True)

                    rows = []
                    for variant in search_variants:
                        variant_rows = ReceivingLog.query.session.execute(
                            text(
                                "SELECT * FROM word_file_log "
                                "WHERE CAST(product_details AS text) ILIKE :serial"
                            ),
                            {"serial": f"%{variant}%"}
                        ).mappings().all()
                        rows.extend(dict(row) for row in variant_rows)

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

                    unique_rows = {}
                    for row in rows:
                        key = (
                            row.get("file_path"),
                            row.get("file_name"),
                            row.get("order_id")
                        )
                        unique_rows[key] = row

                    if unique_rows:
                        word_serial_results = list(unique_rows.values())
                    else:
                        all_rows = ReceivingLog.query.session.execute(
                            text("SELECT * FROM word_file_log")
                        ).mappings().all()
                        word_serial_results = [
                            dict(row) for row in all_rows if row_has_exact_serial(row, word_serial_query)
                        ]

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
                                    "FROM public.combined_wo_outgoing_form_filing "
                                    f"WHERE {' OR '.join(where_clauses)}"
                                )
                                outgoing_rows = ReceivingLog.query.session.execute(
                                    text(sql), params
                                ).mappings().all()
                                row["outgoing_info"] = outgoing_rows
                            except Exception as outgoing_error:
                                logging.error(
                                    "Error querying outgoing info for word file %s: %s",
                                    file_name,
                                    outgoing_error
                                )
                except Exception as e:
                    logging.error(f"Error querying word_file_log: {e}")
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

    return render_template('index.html',
                           serial_number=serial_number,
                           part_name=part_name,
                           entry_date=entry_date,
                           invoice_number=invoice_number,
                           pod_number=pod_number,
                           found=found,
                           message=message,
                           prune_input=prune_input,
                           pruned_serials_text=pruned_serials_text,
                           word_serial_query=word_serial_query,
                           word_serial_results=word_serial_results,
                           match_results=match_results,
                           refresh_status=refresh_status,
                           refresh_message=refresh_message)

@index_bp.route('/word-preview', methods=['GET'])
def word_preview():
    file_path = request.args.get('file_path', '').strip()
    if not file_path:
        abort(400)
    if not file_path.lower().endswith('.docx'):
        abort(400)
    if not os.path.isfile(file_path):
        abort(404)

    if Document is None:
        return render_template(
            'word_preview.html',
            file_path=file_path,
            content="",
            error="python-docx is not installed. Run: pip install python-docx"
        )

    try:
        doc = Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text]
        content = "\n".join(paragraphs)
        if not content:
            content = "(No text found in this document.)"
        return render_template(
            'word_preview.html',
            file_path=file_path,
            content=content,
            error=""
        )
    except Exception as e:
        logging.error(f"Error reading word file {file_path}: {e}")
        return render_template(
            'word_preview.html',
            file_path=file_path,
            content="",
            error="Failed to read the Word file."
        )

@index_bp.route('/word-download', methods=['GET'])
def word_download():
    file_path = request.args.get('file_path', '').strip()
    if not file_path:
        abort(400)
    if not file_path.lower().endswith('.docx'):
        abort(400)
    if not os.path.isfile(file_path):
        abort(404)
    return send_file(file_path, as_attachment=True)

@index_bp.route('/invoice-download', methods=['GET'])
def invoice_download():
    invoice_number = request.args.get('invoice_number', '').strip()
    if not invoice_number:
        abort(400)

    pattern = os.path.join(INVOICE_DIR, f"*{invoice_number}*")
    matches = [
        p for p in glob.glob(pattern)
        if os.path.isfile(p) and not _is_pl_pdf(p)
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

    search_terms = [term.lower() for term in [outgoing_form, invoice_number] if term]
    matches = []
    for root, _, files in os.walk(OUTGOING_DIR):
        for name in files:
            name_lower = name.lower()
            if any(term in name_lower for term in search_terms):
                full_path = os.path.join(root, name)
                if not _is_pl_pdf(full_path):
                    matches.append(full_path)

    if not matches:
        abort(404)

    pdf_matches = [p for p in matches if p.lower().endswith(".pdf")]
    selected = pdf_matches[0] if pdf_matches else matches[0]
    return send_file(selected, as_attachment=False)
