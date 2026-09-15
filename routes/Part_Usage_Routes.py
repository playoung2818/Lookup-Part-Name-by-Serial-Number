import json

from flask import Blueprint, current_app, render_template, request
from sqlalchemy import bindparam, text

from models.models import db
from routes.Work_Order_Routes import order_digits


part_usage_bp = Blueprint('part_usage', __name__, url_prefix='/part-usage')


def matching_items(details, query):
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except (ValueError, TypeError):
            return []
    if isinstance(details, dict):
        details = [details]
    if not isinstance(details, list):
        return []
    return [item for item in details if isinstance(item, dict)
            and query.casefold() in str(item.get('product_number') or '').casefold()]


@part_usage_bp.get('/')
def index():
    query = request.args.get('q', '').strip()
    page = max(1, request.args.get('page', 1, type=int))
    rows, error = [], None
    if query:
        # Candidate filtering only; matching_items checks the product field specifically.
        pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        try:
            with db.engine.connect() as connection:
                candidates = connection.execute(text('''
                    SELECT id, order_id, file_name, product_details
                    FROM word_file_log
                    WHERE CAST(product_details AS text) ILIKE :pattern
                    ORDER BY file_name DESC, id DESC
                '''), {'pattern': pattern}).mappings()
                for document in candidates:
                    for item in matching_items(document['product_details'], query):
                        rows.append(dict(item, document_id=document['id'],
                                         file_name=document['file_name'], order_id=document['order_id'],
                                         so_digits=order_digits(document['order_id'] or '')))
        except Exception:
            current_app.logger.exception('Part usage lookup failed')
            error = 'Could not load part usage history. Please try again.'
            rows = []
    total = len(rows)
    pages = max(1, (total + 49) // 50)
    page = min(page, pages)
    visible_rows = rows[(page - 1) * 50:page * 50]
    description_warning = None
    if visible_rows:
        try:
            parts = sorted({str(row.get('product_number') or '').strip().lower() for row in visible_rows})
            with db.engine.connect() as connection:
                descriptions = connection.execute(text('''
                    SELECT "Part Name", "Description" FROM public."Item Info"
                    WHERE LOWER(TRIM("Part Name")) IN :parts
                    ORDER BY "Name"
                ''').bindparams(bindparam('parts', expanding=True)), {'parts': parts}).mappings()
                lookup = {}
                for item in descriptions:
                    key = item['Part Name'].strip().lower()
                    description = (item['Description'] or '').strip()
                    if description and description not in lookup.setdefault(key, []):
                        lookup[key].append(description)
            for row in visible_rows:
                row['description'] = '\n'.join(lookup.get(str(row.get('product_number') or '').strip().lower(), []))
        except Exception:
            current_app.logger.exception('Part description lookup failed')
            description_warning = 'Part descriptions are temporarily unavailable.'
    return render_template('part_usage.html', query=query, error=error, total=total,
                           description_warning=description_warning,
                           document_count=len({row['document_id'] for row in rows}),
                           rows=visible_rows, page=page, pages=pages)
