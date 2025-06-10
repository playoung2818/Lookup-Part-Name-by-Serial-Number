from flask import Blueprint, render_template, request, jsonify
from models.models import ReceivingLog
from sqlalchemy.sql import text
from tempfile import NamedTemporaryFile
import os
import re
import logging

from functions.utils import extract_useful_number
from functions.validation import validate_sn_part_matches_via_api

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
                    word_serial_results = ReceivingLog.query.session.execute(
                        text("SELECT * FROM word_file_log WHERE product_details::text ILIKE :query"),
                        {"query": f"%{word_serial_query}%"}
                    ).fetchall()
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
