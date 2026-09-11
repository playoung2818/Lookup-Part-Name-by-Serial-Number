"""Work order viewer using the existing document and outgoing mapping tables."""
import json
import os
import re

from flask import Blueprint, abort, current_app, render_template, request, send_file
from sqlalchemy import text

from models.models import db
from routes.Index_Routes import OUTGOING_DIR, _is_pl_pdf


work_orders_bp = Blueprint("work_orders", __name__, url_prefix="/work-orders")


def order_digits(query):
    match = re.fullmatch(r"(?:(?:SO\s*-?\s*)|(?:WO\d{2}\s*-\s*))?(\d{8})", query, re.I)
    return match.group(1) if match else None


def filename_matches(name, value):
    value = str(value or "").strip()
    if value.upper() in {"", "N/A", "NA", "NONE", "NAN", "-"}:
        return False
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(value) + r"(?![A-Za-z0-9])", name, re.I) is not None


def find_outgoing_files(mappings):
    for row in mappings:
        row["files"] = []
    if not mappings:
        return True
    if not os.path.isdir(OUTGOING_DIR):
        return False
    for root, _, names in os.walk(OUTGOING_DIR):
        for name in sorted(names):
            if not name.lower().endswith(".pdf") or _is_pl_pdf(name):
                continue
            for row in mappings:
                if any(filename_matches(name, row.get(key)) for key in ("Outgoing Form#", "Invoice#")):
                    row["files"].append({"name": name, "path": os.path.relpath(os.path.join(root, name), OUTGOING_DIR)})
    for row in mappings:
        row["files"].sort(key=lambda f: f["path"].lower())
    return True


@work_orders_bp.route("/", methods=["GET", "POST"])
def index():
    query = (request.form if request.method == "POST" else request.args).get("q", "").strip()
    pdfs, words, outgoing, errors = [], [], [], []
    digits = order_digits(query)
    if query:
        # Each query has its own connection so one unavailable table does not hide other results.
        pattern = "%" + (digits or query).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        for table, destination in (("pdf_file_log", pdfs), ("word_file_log", words)):
            try:
                with db.engine.connect() as connection:
                    result = connection.execute(text(
                        f"SELECT * FROM {table} WHERE file_name ILIKE :pattern OR order_id ILIKE :pattern ORDER BY file_name LIMIT 200"
                    ), {"pattern": pattern}).mappings()
                    destination.extend(dict(row) for row in result)
            except Exception:
                current_app.logger.exception("Work order lookup failed: %s", table)
                errors.append(f"Could not load {'PDF' if table == 'pdf_file_log' else 'Word'} records.")
        if digits:
            try:
                with db.engine.connect() as connection:
                    result = connection.execute(text('''
                        SELECT DISTINCT "WO/SO #", "Customer", "Invoice#", "Outgoing Form#", "Invoice Date"
                        FROM public.combined_wo_outgoing_form_filing
                        WHERE "WO/SO #" ~* :pattern
                        ORDER BY "Outgoing Form#", "Invoice#"
                    '''), {"pattern": r"(^|[^A-Za-z0-9])SO[[:space:]]*-[[:space:]]*" + digits + r"([^A-Za-z0-9]|$)"}).mappings()
                    outgoing.extend(dict(row) for row in result)
                if not find_outgoing_files(outgoing):
                    errors.append("The outgoing PDF folder is unavailable. Mapping records are shown below.")
            except Exception:
                current_app.logger.exception("Outgoing mapping lookup failed")
                errors.append("Could not load outgoing mappings or scan the outgoing PDF folder.")
        for word in words:
            details = word.get("product_details")
            try:
                if isinstance(details, str):
                    details = json.loads(details)
                if isinstance(details, dict):
                    details = [details]
                word["details"] = [item for item in (details or []) if isinstance(item, dict)]
            except (TypeError, ValueError):
                word["details"] = []
    return render_template("work_orders.html", query=query, digits=digits, pdfs=pdfs,
                           words=words, outgoing=outgoing, errors=errors)


@work_orders_bp.get("/document/<kind>/<int:record_id>")
def document(kind, record_id):
    table = {"pdf": "pdf_file_log", "word": "word_file_log"}.get(kind)
    if not table:
        abort(404)
    with db.engine.connect() as connection:
        path = connection.execute(text(f"SELECT file_path FROM {table} WHERE id = :id"), {"id": record_id}).scalar()
    if not path or not os.path.isfile(path):
        abort(404)
    if not path.lower().endswith(".pdf" if kind == "pdf" else ".docx"):
        abort(404)
    return send_file(path, as_attachment=(kind == "word"))


@work_orders_bp.get("/outgoing-pdf")
def outgoing_pdf():
    relative = request.args.get("path", "")
    base = os.path.realpath(OUTGOING_DIR)
    path = os.path.realpath(os.path.join(base, relative))
    try:
        allowed = os.path.commonpath([base, path]) == base
    except ValueError:
        allowed = False
    if not allowed or not path.lower().endswith(".pdf") or _is_pl_pdf(path) or not os.path.isfile(path):
        abort(404)
    return send_file(path, as_attachment=False)
