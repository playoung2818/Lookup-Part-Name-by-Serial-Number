"""Read MES and historical detail records from the shared WO Details table."""
import json
from sqlalchemy import text
from models.models import db


def display_record(row):
    result = dict(row)
    items = result.get('items') or []
    if isinstance(items, str):
        items = json.loads(items)
    details = []
    for item in items:
        serials = item.get('serials') or []
        if isinstance(serials, str):
            serials = [serials]
        details.append(dict(product_number=item.get('item', ''),
                            qty=item.get('quantity') if item.get('quantity') is not None else item.get('legacy_quantity_text', ''),
                            sn='\n'.join(str(serial) for serial in serials), notes=item.get('notes', '')))
    result.update(order_id=result['sales_order'], details=details, product_details=details,
                  file_name=result.get('Document #') or result['sales_order'], file_path=None)
    return result


def find_work_orders(pattern):
    with db.engine.connect() as connection:
        rows = connection.execute(text('''SELECT * FROM "WO Details"
            WHERE sales_order ILIKE :pattern OR "Document #" ILIKE :pattern
               OR CAST(items AS text) ILIKE :pattern
            ORDER BY CASE WHEN record_source = 'mes' THEN 0 ELSE 1 END,
                     sales_order DESC, release_number DESC LIMIT 200'''), {'pattern': pattern}).mappings().all()
    return [display_record(row) for row in rows]


def find_by_serial(variants):
    # Narrow candidates in SQL; the route checks actual serial fields exactly.
    params, clauses = {}, []
    for index, variant in enumerate(variants):
        key = f'serial_{index}'
        params[key] = '%' + variant.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        clauses.append(f'CAST(items AS text) ILIKE :{key}')
    if not clauses:
        return []
    with db.engine.connect() as connection:
        rows = connection.execute(text('SELECT * FROM "WO Details" WHERE (' + ' OR '.join(clauses) + ") ORDER BY CASE WHEN record_source = 'mes' THEN 0 ELSE 1 END, sales_order DESC, release_number DESC").bindparams(**params)).mappings().all()
    return [display_record(row) for row in rows]
