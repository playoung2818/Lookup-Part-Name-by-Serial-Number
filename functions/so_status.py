"""Read-only SO workflow lookup from shared MRP/MES planning tables."""
from sqlalchemy import text
from models.models import db


STATUS_LABELS = {
    'needs_material_review': 'Needs Material Review',
    'needs_production_planning': 'Needs Production Planning',
    'released_to_mes': 'Released to MES',
    'closed': 'Closed / excluded',
}


def find_so_status(so_number):
    # Do not filter on source presence/is_active: search must retain missing-source
    # and closed orders, unlike the actionable planning queues.
    with db.engine.connect() as connection:
        row = connection.execute(text('''
            SELECT a.sales_order,
                   COALESCE(NULLIF(a.customer, ''),
                            a.latest_snapshot ->> 'customer',
                            a.approved_snapshot ->> 'customer',
                            a.previous_snapshot ->> 'customer') AS customer,
                   a.workflow_status, a.returned_from_mes,
                   NOT COALESCE(
                       (to_jsonb(a) ->> 'source_present')::boolean,
                       (to_jsonb(a) ->> 'google_present')::boolean,
                       FALSE
                   ) AS missing_source,
                   a.reconciliation_required,
                   p.production_date, p.is_finished_goods
            FROM public.sales_order_workflow a
            LEFT JOIN public.production_overrides p ON p.wo_number = a.sales_order
            WHERE a.sales_order = :so_number
        '''), {'so_number': so_number}).mappings().first()
    if row is None:
        return None
    result = dict(row)
    status = result['workflow_status']
    result['status_label'] = STATUS_LABELS.get(status, status or 'Unknown')
    result['owner'] = ('MRP' if status in ('needs_material_review', 'needs_production_planning')
                       else 'MES' if status == 'released_to_mes'
                       else 'Neither / closed' if status == 'closed' else 'Unknown')
    return result
