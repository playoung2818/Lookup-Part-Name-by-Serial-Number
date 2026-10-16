"""Two-step receiving import. Preview tokens are signed, expiring and session-bound."""
import secrets
from pathlib import Path

from flask import Blueprint, current_app, render_template, request, session, abort
from itsdangerous import URLSafeTimedSerializer, BadSignature
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import RequestEntityTooLarge

from models.models import db
from functions.receiving_import import read_upload, receiving_table, build_review, apply_review, KEYS

receiving_bp = Blueprint('receiving', __name__)


def signer():
    return URLSafeTimedSerializer(current_app.secret_key, salt='receiving-preview-v1')


@receiving_bp.before_request
def limit_upload():
    request.max_content_length = 10 * 1024 * 1024


@receiving_bp.errorhandler(RequestEntityTooLarge)
def oversized_upload(error):
    return render_template('receiving.html', error='Upload must be smaller than 10 MB.'), 413


@receiving_bp.route('/receiving', methods=['GET', 'POST'])
def index():
    csrf = session.setdefault('receiving_csrf', secrets.token_hex(32))
    context = {}
    status = 200
    if request.method == 'POST':
        if not secrets.compare_digest(request.form.get('csrf_token', ''), csrf):
            abort(400)
        try:
            if request.form.get('action') == 'import':
                try:
                    payload = signer().loads(request.form.get('preview_token', ''), max_age=1800)
                except BadSignature as exc:
                    raise ValueError('Preview expired or invalid. Upload the workbook again.') from exc
                if payload.get('csrf') != csrf:
                    abort(400)
                if payload.get('version') != 2:
                    raise ValueError('Please upload again to use the new conflict review.')
                counts = apply_review(db.engine, payload['review'],
                                      {str(i): request.form.get(f'choice_{i}', 'skip') for i in range(len(payload['review']))},
                                      request.form.get('allow_delete') == 'yes')
                context['message'] = (f"Review applied: {counts['inserted']} rows inserted; "
                                      f"{counts['updated']} updated; {counts['deleted']} deleted; "
                                      f"{counts['untouched']} serial groups left unchanged.")
            else:
                upload = request.files.get('file')
                if not upload or Path(upload.filename or '').suffix.lower() not in ('.xlsx', '.xlsm'):
                    raise ValueError('Choose an .xlsx or .xlsm file.')
                records, errors, blank_count = read_upload(upload.read())
                with db.engine.connect() as connection:
                    table = receiving_table(connection)
                    review, duplicate_count = build_review(connection, table, records)
                context.update(review=review, new_count=sum(g['kind'] == 'new' for g in review),
                               conflict_count=sum(g['kind'] == 'conflict' for g in review),
                               errors=errors[:100], error_count=len(errors), fields=KEYS,
                               skipped=blank_count + duplicate_count)
                if not errors and review:
                    signed_review = [{k: v for k, v in group.items() if k != 'existing'} for group in review]
                    context['preview_token'] = signer().dumps({'version': 2, 'csrf': csrf, 'review': signed_review})
        except ValueError as exc:
            context['error'] = str(exc)
            status = 400
        except SQLAlchemyError:
            current_app.logger.exception('Receiving database operation failed')
            context['error'] = 'Database operation failed. All changes were rolled back. Check the database connection and constraints, then preview again.'
            status = 503
        except Exception:
            current_app.logger.exception('Receiving workbook processing failed')
            context['error'] = 'Unable to process this workbook. No rows were imported. Check its format and try again.'
            status = 400
    return render_template('receiving.html', **context), status
