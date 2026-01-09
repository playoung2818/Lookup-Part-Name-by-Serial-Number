from flask import Blueprint, render_template, request, jsonify, abort, send_file
import json
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

@index_bp.route('/', methods=['GET', 'POST'])
def index():
    serial_number = ""
    part_name = ""
    entry_date = ""
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

        if 'word_serial_query' in request.form:
            word_serial_query = request.form.get('word_serial_query', '').strip()
            if word_serial_query:
                try:
                    rows = ReceivingLog.query.session.execute(
                        text("SELECT * FROM word_file_log")
                    ).mappings().all()

                    def row_has_exact_serial(row, serial):
                        product_details = row.get("product_details")
                        if product_details is None:
                            return False
                        if isinstance(product_details, str):
                            try:
                                product_details = json.loads(product_details)
                            except Exception:
                                return False
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
                            serials = [s.strip() for s in str(sn_field).splitlines() if s.strip()]
                            if serial in serials:
                                return True
                        return False

                    word_serial_results = [
                        row for row in rows if row_has_exact_serial(row, word_serial_query)
                    ]
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
