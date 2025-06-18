from flask import Flask, request, render_template, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import text
from tempfile import NamedTemporaryFile
import logging
import os
import re
from dateutil.parser import parse
from config import Config


from models.models import db, ReceivingLog
from functions.utils import (
    extract_useful_number,
    get_part_name_from_db,
    extract_product_details_from_word,
    validate_sn_part_matches_via_api
)
from routes.Index_Routes import index_bp
from routes.Api_Routes import api_bp

def create_app():
    """Application factory — makes testing & deployment easier."""
    app = Flask(__name__,
                template_folder="templates",
                static_folder="static")
    app.config.from_object(Config)

    # initialize SQLAlchemy
    db.init_app(app)

    # register your modular routes
    app.register_blueprint(index_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    return app



# # Initialize app
# app = Flask(__name__)
# from config import Config
# app.config.from_object(Config)     


# db.init_app(app)

# # Main Route
# @app.route('/', methods=['GET', 'POST'])
# def index():
#     serial_number = ""
#     part_name = ""
#     entry_date = ""
#     found = False
#     message = ""
#     prune_input = ""
#     pruned_serials_text = ""
#     word_serial_query = ""
#     word_serial_results = []
#     match_results = []

#     refresh_status = request.args.get('refresh_status')
#     refresh_message = request.args.get('refresh_message')

#     if request.method == 'POST':
#         if 'serial_number' in request.form:
#             serial_number = request.form.get('serial_number', '').strip()
#             if serial_number:
#                 try:
#                     found_entry = ReceivingLog.query.filter_by(serial_number=serial_number).first()
#                     if found_entry:
#                         part_name = found_entry.part_number
#                         entry_date = found_entry.entry_date.strftime('%m-%d-%Y') if found_entry.entry_date else ""
#                         message = "Part Found!"
#                         found = True
#                     else:
#                         message = "No part found with that serial number."
#                 except Exception as e:
#                     logging.error(f"Lookup error: {e}")
#                     message = "Error occurred during lookup."

#         if 'prune_input' in request.form:
#             prune_input = request.form.get('prune_input', '').strip()
#             if prune_input:
#                 try:
#                     raw_serials = re.split(r'[,\n]+', prune_input)
#                     pruned_serials = [extract_useful_number(sn.strip()) for sn in raw_serials if sn.strip()]
#                     pruned_serials_text = "\n".join(pruned_serials)
#                 except Exception as e:
#                     logging.error(f"Prune error: {e}")
#                     pruned_serials_text = "Error during pruning."

#         if 'word_serial_query' in request.form:
#             word_serial_query = request.form.get('word_serial_query', '').strip()
#             if word_serial_query:
#                 try:
#                     word_serial_results = db.session.execute(
#                         text("SELECT * FROM word_file_log WHERE product_details::text ILIKE :query"),
#                         {"query": f"%{word_serial_query}%"}
#                     ).fetchall()
#                 except Exception as e:
#                     logging.error(f"Word log query error: {e}")

#         if 'word_file' in request.files:
#             uploaded_file = request.files['word_file']
#             if uploaded_file and uploaded_file.filename.endswith('.docx'):
#                 try:
#                     with NamedTemporaryFile(delete=False, suffix='.docx') as tmp:
#                         uploaded_file.save(tmp.name)
#                         match_results = validate_sn_part_matches_via_api(tmp.name, db.session)
#                         os.unlink(tmp.name)
#                 except Exception as e:
#                     logging.error(f"Word file processing error: {e}")

#     return render_template('index.html',
#         serial_number=serial_number,
#         part_name=part_name,
#         entry_date=entry_date,
#         found=found,
#         message=message,
#         prune_input=prune_input,
#         pruned_serials_text=pruned_serials_text,
#         word_serial_query=word_serial_query,
#         word_serial_results=word_serial_results,
#         match_results=match_results,
#         refresh_status=refresh_status,
#         refresh_message=refresh_message
#     )

# # API Route: Lookup
# @app.route('/api/lookup', methods=['GET'])
# def api_lookup():
#     serial_number = request.args.get('serial_number', '').strip()
#     if not serial_number:
#         return jsonify({"error": "Missing serial_number"}), 400
#     try:
#         found_entry = ReceivingLog.query.filter_by(serial_number=serial_number).first()
#         if found_entry:
#             return jsonify({
#                 "serial_number": found_entry.serial_number,
#                 "part_name": found_entry.part_number,
#                 "entry_date": found_entry.entry_date.strftime('%m-%d-%Y') if found_entry.entry_date else None
#             }), 200
#         else:
#             return jsonify({"error": "Not found"}), 404
#     except Exception as e:
#         logging.error(f"API error: {e}")
#         return jsonify({"error": "Internal error"}), 500

# # API Route: Sheet Update
# @app.route('/api/sheet-update', methods=['POST'])
# def sheet_update():
#     try:
#         data = request.get_json()
#         serial = data.get("serial_number")
#         if not serial:
#             return jsonify({"error": "Missing serial_number"}), 400

#         entry = ReceivingLog.query.get(serial)
#         if entry:
#             for field in ['entry_date', 'invoice_number', 'box_number', 'pod_number', 'part_number', 'quantity']:
#                 setattr(entry, field, data.get(field))
#         else:
#             entry = ReceivingLog(**data)
#             db.session.add(entry)

#         db.session.commit()
#         return jsonify({"status": "ok"}), 200
#     except Exception as e:
#         logging.error(f"Sheet update error: {e}")
#         return jsonify({"error": "Internal error"}), 500

# if __name__ == '__main__':
#     with app.app_context():
#         try:
#             db.create_all()
#             # load_success = load_data("Receiving Log_ZC")  
#             # if not load_success:
#             #     logging.error("load_data() returned False – check your sheet or credentials.")
#         except Exception as e:
#             logging.error(f"Startup error: {e}")

#     app.run(host='0.0.0.0', port=5000, debug=True)


if __name__ == '__main__':
    logging.basicConfig(level=Config.LOG_LEVEL)
    app = create_app()
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)


