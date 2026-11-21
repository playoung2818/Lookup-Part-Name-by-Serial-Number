"""Work order viewer using the existing document and outgoing mapping tables."""
import json
import os
import re
from urllib.parse import quote

from flask import Blueprint, abort, current_app, render_template, request, send_file
from sqlalchemy import text

from models.models import db
from functions.wo_lookup import find_work_orders
from functions.so_status import find_so_status
from routes.Index_Routes import _is_pl_pdf


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
    base = current_app.config["OUTGOING_DIR"]
    if not base or not os.path.isdir(base):
        return False
    for root, _, names in os.walk(base):
        for name in sorted(names):
            if not name.lower().endswith(".pdf") or _is_pl_pdf(name):
                continue
            for row in mappings:
                if any(filename_matches(name, row.get(key)) for key in ("Outgoing Form#", "Invoice#")):
                    row["files"].append({"name": name, "path": os.path.relpath(os.path.join(root, name), base)})
    for row in mappings:
        row["files"].sort(key=lambda f: f["path"].lower())
    return True


@work_orders_bp.route("/", methods=["GET", "POST"])
def index():
    query = (request.form if request.method == "POST" else request.args).get("q", "").strip()
    pdfs, words, outgoing, errors = [], [], [], []
    digits = order_digits(query)
    workflow, workflow_error = None, None
    if digits:
        try:
            workflow = find_so_status(f'SO-{digits}')
            if workflow:
                owner = workflow['owner']
                if owner in ('MRP', 'MES'):
                    base = current_app.config[f'{owner}_BASE_URL'].rstrip('/')
                    path = ('/sales_orders/' + quote(workflow['sales_order'], safe='')
                            if owner == 'MRP' else '/production_planning')
                    workflow['system_url'] = base + path
        except Exception:
            current_app.logger.exception('SO workflow status lookup failed')
            workflow_error = 'Workflow status is unavailable. Other lookup results are shown below.'
    if query:
        # Each query has its own connection so one unavailable table does not hide other results.
        pattern = "%" + (digits or query).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        for table, destination in (("pdf_file_log", pdfs),):
            try:
                with db.engine.connect() as connection:
                    result = connection.execute(text(
                        f"SELECT * FROM {table} WHERE file_name ILIKE :pattern OR order_id ILIKE :pattern ORDER BY file_name LIMIT 200"
                    ), {"pattern": pattern}).mappings()
                    destination.extend(dict(row) for row in result)
            except Exception:
                current_app.logger.exception("Work order lookup failed: %s", table)
                errors.append(f"Could not load {'PDF' if table == 'pdf_file_log' else 'Word'} records.")
        try:
            words = find_work_orders(pattern)
        except Exception:
            current_app.logger.exception('wo_details lookup failed')
            errors.append('Could not load work-order details.')
        if digits:
            try:
                with db.engine.connect() as connection:
                    result = connection.execute(text('''
                        SELECT DISTINCT "WO/SO #", "Customer", "Invoice#", "Outgoing Form#", "Invoice Date"
                        FROM public.outgoing_records
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
                           words=words, outgoing=outgoing, errors=errors,
                           workflow=workflow, workflow_error=workflow_error)


SHARE_ERRORS = {5: "access is denied", 53: "the network path was not found",
                67: "the network name was not found", 1326: "the sign-in was rejected",
                1219: "conflicting credentials are already in use"}


def share_root(path):
    """'\\\\server\\share\\a\\b.pdf' -> '\\\\server\\share'; None for local paths."""
    drive = os.path.splitdrive(path)[0]
    return drive if drive.startswith(("\\\\", "//")) else None


def unavailable_reason(path):
    """Why a file cannot be served: None, 'share', 'folder' or 'file', plus detail."""
    if os.path.isfile(path):
        return None, ""
    root = share_root(path)
    if root:
        try:
            os.listdir(root)
        except OSError as exc:
            code = getattr(exc, "winerror", None) or exc.errno
            return "share", SHARE_ERRORS.get(code, exc.strerror or str(exc))
    if not os.path.isdir(os.path.dirname(path)):
        return "folder", "folder not found"
    return "file", "file not found in folder"


def document_error(status, title, message, path=None, hint=None):
    response = render_template("document_error.html", status=status, title=title, message=message, hint=hint,
                               file_name=os.path.basename(path) if path else None,
                               location=os.path.dirname(path) if path else None)
    return response, status, {"Cache-Control": "no-store"}


def unavailable_response(path, label):
    reason, detail = unavailable_reason(path)
    current_app.logger.warning("%s unavailable (%s: %s): %s", label, reason, detail, path)
    if reason == "share":
        return document_error(
            503, "File share unavailable",
            f"The web server cannot open the network share {share_root(path)} ({detail}). "
            "The document record exists; the file itself could not be reached.", path,
            "The web app must run under a Windows sign-in that has access to this share "
            "(see scripts/install_startup_task.ps1). Ask the administrator to check the server; retry afterwards.")
    if reason == "folder":
        return document_error(503, "Document folder unavailable",
                              "The folder recorded for this document is not reachable from the web server.", path,
                              "The folder may have been renamed or moved, or a mapped drive may be disconnected.")
    return document_error(404, "Document file not found",
                          "The document record exists, but the file is no longer in its folder. "
                          "It may have been renamed, moved or deleted.", path)


@work_orders_bp.get("/document/<kind>/<int:record_id>")
def document(kind, record_id):
    table = {"pdf": "pdf_file_log"}.get(kind)
    if not table:
        abort(404)
    try:
        with db.engine.connect() as connection:
            path = connection.execute(text(f"SELECT file_path FROM {table} WHERE id = :id"), {"id": record_id}).scalar()
    except Exception:
        current_app.logger.exception("Document record lookup failed: %s #%s", table, record_id)
        return document_error(503, "Document lookup unavailable",
                              "The document list could not be read from the database. Retry shortly.")
    if not path:
        return document_error(404, "Document not found", f"There is no PDF document record #{record_id}.")
    if not path.lower().endswith(".pdf" if kind == "pdf" else ".docx"):
        abort(404)
    if not os.path.isfile(path):
        return unavailable_response(path, f"Document #{record_id}")
    return send_file(path, as_attachment=(kind == "word"))


@work_orders_bp.get("/outgoing-pdf")
def outgoing_pdf():
    relative = request.args.get("path", "")
    configured = current_app.config["OUTGOING_DIR"]
    if not configured:
        abort(404)  # never fall back to the working directory
    if not os.path.isdir(configured):
        reason, detail = unavailable_reason(os.path.join(configured, "x.pdf"))
        current_app.logger.warning("Outgoing PDF folder unavailable (%s: %s): %s", reason, detail, configured)
        return document_error(503, "Outgoing folder unavailable",
                              f"The outgoing PDF folder is not reachable from the web server ({detail}).",
                              hint="Check that the OneDrive / shared folder is available to the account running the web app.")
    base = os.path.realpath(configured)
    path = os.path.realpath(os.path.join(base, relative))
    try:
        allowed = os.path.commonpath([base, path]) == base
    except ValueError:
        allowed = False
    if not allowed or not path.lower().endswith(".pdf") or _is_pl_pdf(path) or not os.path.isfile(path):
        abort(404)
    return send_file(path, as_attachment=False)
