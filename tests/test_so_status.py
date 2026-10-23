import unittest
from unittest.mock import patch

from app import create_app
from functions.so_status import find_so_status


def status_row(status='released_to_mes', **changes):
    row = dict(sales_order='SO-20261511', customer='Test customer',
               workflow_status=status, returned_from_mes=False, missing_source=False,
               reconciliation_required=False, production_date=None, is_finished_goods=False)
    row.update(changes)
    return row


class SOStatusTests(unittest.TestCase):
    def lookup(self, row):
        with patch('functions.so_status.db') as database:
            connection = database.engine.connect.return_value.__enter__.return_value
            connection.execute.return_value.mappings.return_value.first.return_value = row
            result = find_so_status('SO-20261511')
            statement, params = connection.execute.call_args.args
            self.assertEqual(params, {'so_number': 'SO-20261511'})
            sql = str(statement)
            self.assertIn('FROM public.sales_order_workflow a', sql)
            self.assertNotIn('approved_work_orders', sql)
            self.assertIn('LEFT JOIN public.production_overrides', sql)
            self.assertIn("to_jsonb(a) ->> 'source_present'", sql)
            self.assertIn("to_jsonb(a) ->> 'google_present'", sql)
            self.assertNotIn('a.google_present', sql)
            self.assertEqual(sql.split('WHERE')[1].strip(), 'a.sales_order = :so_number')
            return result

    def test_status_labels_and_owners(self):
        for status, owner, label in [
            ('needs_material_review', 'MRP', 'Needs Material Review'),
            ('needs_production_planning', 'MRP', 'Needs Production Planning'),
            ('released_to_mes', 'MES', 'Released to MES'),
            ('closed', 'Neither / closed', 'Closed / excluded'),
        ]:
            with self.subTest(status=status):
                result = self.lookup(status_row(status))
                self.assertEqual((result['owner'], result['status_label']), (owner, label))
        self.assertIsNone(self.lookup(None))
        self.assertEqual(self.lookup(status_row('future_status'))['owner'], 'Unknown')

    def page(self, workflow=None, error=None):
        app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
        with patch('routes.Work_Order_Routes.find_so_status', return_value=workflow, side_effect=error) as lookup, \
             patch('routes.Work_Order_Routes.find_work_orders', return_value=[]), \
             patch('routes.Work_Order_Routes.db') as database:
            connection = database.engine.connect.return_value.__enter__.return_value
            connection.execute.return_value.mappings.return_value = []
            response = app.test_client().get('/work-orders/?q=20261511')
            lookup.assert_called_once_with('SO-20261511')
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_closed_record_is_compact_without_system_link(self):
        row = self.lookup(status_row('closed', missing_source=True,
                                    returned_from_mes=True, reconciliation_required=True))
        html = self.page(row)
        for label in ['Closed / excluded', 'Neither / closed']:
            self.assertIn(label, html)
        for label in ['Open in MES', 'Open in MRP', 'Missing from current source',
                      'Returned from MES', 'Current production date']:
            self.assertNotIn(label, html)
        self.assertNotIn('<section class="card mb-3 result-card" aria-label="SO workflow status">', html)

    def test_owner_specific_links(self):
        for status, owner, path, config in [
            ('released_to_mes', 'MES', '/so/SO-20261511', 'MES_BASE_URL'),
            ('needs_material_review', 'MRP', '/sales_orders/SO-20261511', 'MRP_BASE_URL'),
            ('needs_production_planning', 'MRP', '/sales_orders/SO-20261511', 'MRP_BASE_URL'),
        ]:
            with self.subTest(status=status):
                from config import Config
                html = self.page(self.lookup(status_row(status)))
                self.assertIn(f'Open in {owner}', html)
                self.assertIn(getattr(Config, config).rstrip('/') + path, html)
                self.assertNotIn('Current production date', html)

    def test_missing_and_unavailable_are_distinguished(self):
        self.assertIn('No stored workflow record found', self.page())
        html = self.page(error=RuntimeError('unavailable'))
        self.assertIn('Workflow status is unavailable', html)
        self.assertNotIn('No stored workflow record found', html)
        self.assertIn('Outgoing PDFs', html)


if __name__ == '__main__':
    unittest.main()
