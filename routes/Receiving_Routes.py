"""Review a generated draft, commit explicitly, then reopen invoices for SN entry."""
import secrets
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from flask import (Blueprint, abort, current_app, jsonify, redirect, render_template,
                   request, send_file, session, url_for)
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import RequestEntityTooLarge

from models.models import db
from functions.receiving_workspace import (
    WorkspaceConflict, WorkspaceStore, identifier, load_database, public_state,
    save_database, save_row, update_template, search_invoice,
)

receiving_bp = Blueprint('receiving', __name__)


@receiving_bp.before_request
def prepare_receiving():
    request.max_content_length = (32 if request.endpoint == 'receiving.generate_shipment' else 10) * 1024 * 1024
    session.setdefault('receiving_csrf', secrets.token_hex(32))
    session.setdefault('receiving_owner', secrets.token_hex(32))
    session.permanent = True


def store():
    return WorkspaceStore(Path(current_app.instance_path) / 'receiving_workspaces', session['receiving_owner'])


def require_csrf():
    expected = session.get('receiving_csrf', '')
    supplied = request.headers.get('X-CSRF-Token', '') if request.is_json else request.form.get('csrf_token', '')
    if not expected or not supplied.isascii() or not secrets.compare_digest(supplied, expected):
        abort(400)


def database_state(workspace, active):
    if active is None:
        return None
    workspace.migrate_database_mode(active)
    if active.get('mode') != 'draft' or active.get('pending'):
        load_database(db.engine, active, workspace.persist)
    result = public_state(active)
    result['generated_count'] = len(active['rows'])
    if result['needs_initialization'] and result['mode'] != 'draft':
        result['rows'] = []  # Never present uncommitted file data as database rows.
    return result


def render_receiving(error=None, status=200):
    try:
        with store().locked() as workspace:
            state = database_state(workspace, workspace.active())
    except (SQLAlchemyError, OSError, WorkspaceConflict):
        current_app.logger.exception('Receiving database read failed')
        state = None
        error = 'Cannot load the receiving table from the database. No cached table is displayed. Retry when the connection is restored.'
        status = 503
    response = current_app.make_response((render_template('receiving.html', shipment=state, error=error), status))
    response.headers['Cache-Control'] = 'no-store'
    return response


@receiving_bp.errorhandler(RequestEntityTooLarge)
def oversized_upload(error):
    if request.is_json:
        return jsonify(error='Request too large.'), 413
    return render_receiving('Upload too large: 10 MB per file, 32 MB per shipment request.', 413)


@receiving_bp.route('/receiving', methods=['GET'])
def index():
    return render_receiving()


def save_upload(directory, name, extensions, required=True):
    upload = request.files.get(name)
    if not upload or not upload.filename:
        if required:
            raise ValueError(f'Choose a {name} file.')
        return None
    suffix = Path(upload.filename).suffix.lower()
    if suffix not in extensions:
        raise ValueError(f'Invalid {name} file type. Allowed: ' + ', '.join(extensions))
    content = upload.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise ValueError(f'{name} must be smaller than 10 MB.')
    if not content:
        raise ValueError(f'{name} file is empty.')
    path = Path(directory) / f'{name}{suffix}'
    path.write_bytes(content)
    return path


@receiving_bp.route('/receiving/generate', methods=['POST'])
def generate_shipment():
    require_csrf()
    staged = False
    try:
        from functions.receiving_shipment import generate
        expected_id = request.form.get('workspace_id', '')
        revision = request.form.get('revision', '')
        expected_revision = int(revision) if revision.isdigit() else None
        with TemporaryDirectory(prefix='receiving_upload_') as directory:
            receipt = save_upload(directory, 'receipt', ('.pdf',))
            packing = save_upload(directory, 'packing', ('.pdf',))
            serials = save_upload(directory, 'serials', ('.xlsx', '.xlsm'))
            references = None
            configured = current_app.config.get('RECEIVING_REFERENCE_PATH')
            if configured and Path(configured).is_file():
                references = Path(configured)
            workbook = generate(receipt, packing, serials, reference_path=references)
            output = BytesIO()
            workbook.save(output)
            workbook.close()
            with store().locked() as workspace:
                state = workspace.create(output.getvalue(), expected_id, expected_revision)
                staged = True
        return redirect(url_for('receiving.index'), code=303)
    except WorkspaceConflict as exc:
        return render_receiving(str(exc), 409)
    except ValueError as exc:
        return render_receiving(str(exc), 400)
    except (SQLAlchemyError, OSError):
        current_app.logger.exception('Receiving template generation or persistence failed')
        return render_receiving('Could not generate or retain the template. No database records were written by generation. Reload and retry.', 503)
    except Exception:
        current_app.logger.exception('Shipment generation failed')
        text = ('Generated template could not be retained. Reload to check its status; no database records were written.' if staged else
                'Unable to parse shipment files. Check layouts, headers and invoice numbers. The previous table is unchanged.')
        return render_receiving(text, 400)


@receiving_bp.route('/receiving/search', methods=['POST'])
def reload_invoice():
    require_csrf()
    try:
        revision = request.form.get('revision', '')
        with store().locked() as workspace:
            search_invoice(db.engine, workspace, request.form.get('invoice_number', ''),
                           request.form.get('workspace_id', ''), int(revision) if revision.isdigit() else None)
        return redirect(url_for('receiving.index'), code=303)
    except WorkspaceConflict as exc:
        return render_receiving(str(exc), 409)
    except ValueError as exc:
        return render_receiving(str(exc), 400)
    except (SQLAlchemyError, OSError):
        current_app.logger.exception('Receiving invoice search failed')
        return render_receiving('Cannot search the database. Retry when the connection is restored.', 503)


@receiving_bp.route('/receiving/template', methods=['POST'])
def edit_template():
    try:
        data = workspace_payload()
        with store().locked() as workspace:
            state = workspace.require(data['workspace_id'], data.get('revision'))
            if type(data.get('revision')) is not int:
                raise ValueError('Template revision is required.')
            update_template(state, data.get('rows'), workspace.persist)
            result = database_state(workspace, state)
        return jsonify(workspace=result)
    except WorkspaceConflict as exc:
        return jsonify(error=str(exc)), 409
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except OSError:
        return jsonify(error='Cannot save template draft. Keep this page open and retry.'), 503


@receiving_bp.route('/receiving/workspace', methods=['GET'])
def workspace_state():
    try:
        with store().locked() as workspace:
            result = database_state(workspace, workspace.active())
        response = jsonify(workspace=result)
        response.headers['Cache-Control'] = 'no-store'
        return response
    except (SQLAlchemyError, OSError, WorkspaceConflict):
        current_app.logger.exception('Receiving database read failed')
        return jsonify(error='Cannot retrieve the receiving rows from the database.'), 503


def workspace_payload():
    require_csrf()
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not identifier(data.get('workspace_id')):
        raise ValueError('Invalid workspace request.')
    return data


@receiving_bp.route('/receiving/row', methods=['POST'])
def save_receiving_row():
    try:
        data = workspace_payload()
        if set(data) != {'workspace_id', 'row_id', 'row_version', 'serial_number'}:
            raise ValueError('Only serial numbers can be edited in database entry mode.')
        if not isinstance(data.get('row_id'), str) or not isinstance(data.get('row_version'), str):
            raise ValueError('Row ID and database version are required.')
        with store().locked() as workspace:
            state = workspace.require(data['workspace_id'])
            save_row(db.engine, state, data['row_id'], data.get('serial_number'),
                     data['row_version'], workspace.persist)
            result = database_state(workspace, state)
        return jsonify(workspace=result)
    except WorkspaceConflict as exc:
        return jsonify(error=str(exc)), 409
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except (SQLAlchemyError, OSError):
        current_app.logger.exception('Receiving row save not confirmed')
        return jsonify(error='Database save was not confirmed. Keep the entered SN and retry this row; retries will not insert duplicate records.'), 503


@receiving_bp.route('/receiving/save', methods=['POST'])
def initialize_database():
    """Explicit one-time template commit, or safe recovery of a lost response."""
    try:
        data = workspace_payload()
        with store().locked() as workspace:
            state = workspace.require(data['workspace_id'])
            if state.get('mode') == 'draft' and not state.get('pending'):
                if type(data.get('revision')) is not int or data['revision'] != state['revision']:
                    raise WorkspaceConflict('Template changed. Reload before saving to the database.')
                state['template_commit'] = True
                workspace.persist(state)
            if state.get('pending') or any(row['db_id'] is None for row in state['rows']):
                save_database(db.engine, state, workspace.persist)
            result = database_state(workspace, state)
        return jsonify(workspace=result)
    except WorkspaceConflict as exc:
        return jsonify(error=str(exc)), 409
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except (SQLAlchemyError, OSError):
        current_app.logger.exception('Receiving initialization failed')
        return jsonify(error='Initial database write could not be confirmed. Retry safely; do not regenerate the shipment.'), 503


@receiving_bp.route('/receiving/download', methods=['POST'])
def download_shipment():
    require_csrf()
    try:
        with store().locked() as workspace:
            state = workspace.require(request.form.get('workspace_id', ''))
            if state.get('mode') != 'draft':
                load_database(db.engine, state, workspace.persist)
            if state.get('mode') != 'draft' and any(row['db_id'] is None or row.get('db_missing') for row in state['rows']):
                raise ValueError('Initialize the database or resolve deleted rows before downloading.')
            content = workspace.export(state)
        if request.form.get('format') == 'docx':
            from functions.receiving_shipment import incoming_document
            response = send_file(incoming_document(content), as_attachment=True,
                                 download_name='Incoming_Receiving_DRAFT.docx',
                                 mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        else:
            response = send_file(BytesIO(content), as_attachment=True, download_name='Receiving_Log.xlsx',
                                 mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response.headers['Cache-Control'] = 'no-store'
        return response
    except WorkspaceConflict as exc:
        return render_receiving(str(exc), 409)
    except ValueError as exc:
        return render_receiving(str(exc), 400)
    except (SQLAlchemyError, OSError):
        return render_receiving('Cannot download: database rows are unavailable.', 503)
