import unittest
from datetime import date, timedelta
from werkzeug.datastructures import MultiDict

from app import create_app
from models.models import db, WarehouseBorrowLog


class BorrowLogTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite://', 'SECRET_KEY': 'test-only'})
        self.context = self.app.app_context()
        self.context.push()
        WarehouseBorrowLog.__table__.create(db.engine)
        self.client = self.app.test_client()
        self.client.get('/warehouse-borrow-log/new', follow_redirects=True)
        with self.client.session_transaction() as session:
            self.token = session['borrow_csrf']
        self.form = dict(borrower='Test borrower', item_number='PART-1', serial_number='SN-1',
                         borrowed_qty='3', warehouse='WH01S', purpose='Testing',
                         borrow_date='2026-09-01', returned_qty='0', return_date='',
                         issued_by='Warehouse', csrf_token=self.token)

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()

    def test_excel_calculations(self):
        r = WarehouseBorrowLog(id=7, borrow_date=date.today() - timedelta(days=61), borrowed_qty=3, returned_qty=0)
        self.assertEqual(r.status, 'BORROWED')
        self.assertEqual(r.duration_days, 61)
        self.assertTrue(r.borrow_id.endswith('-007'))
        r.returned_qty = 1
        self.assertEqual(r.status, 'PARTIAL RETURN')
        r.returned_qty = 3
        r.return_date = r.borrow_date + timedelta(days=5)
        self.assertEqual(r.status, 'RETURNED')
        self.assertEqual(r.duration_days, 5)
        r.returned_qty = 4
        self.assertEqual(r.status, 'ERROR')

    def test_default_entry_opens_grid(self):
        response = self.client.get('/warehouse-borrow-log/new', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="batch-rows"', response.data)
        self.assertIn(b'Save all entries', response.data)

    def test_create_return_search_and_stale_edit(self):
        self.assertEqual(self.client.post('/warehouse-borrow-log/new', data=self.form).status_code, 303)
        r = db.session.execute(db.select(WarehouseBorrowLog)).scalar_one()
        self.assertEqual(r.borrow_id, 'BR-260901-001')
        url = f'/warehouse-borrow-log/{r.id}/edit'
        partial = dict(self.form, returned_qty='1', version=str(r.version))
        self.assertEqual(self.client.post(url, data=partial).status_code, 303)
        db.session.expire_all()
        self.assertEqual(r.status, 'PARTIAL RETURN')
        self.assertEqual(self.client.post(url, data=partial).status_code, 409)
        full = dict(self.form, returned_qty='3', return_date='2026-09-05', version=str(r.version))
        self.assertEqual(self.client.post(url, data=full).status_code, 303)
        page = self.client.get('/warehouse-borrow-log/?q=SN-1&status=RETURNED')
        self.assertIn(b'Test borrower', page.data)
        self.assertIn(b'<strong>0</strong>', page.data)
        self.assertIn(b'<strong>3</strong>', page.data)
        self.assertNotIn(b'Test borrower', self.client.get('/warehouse-borrow-log/?status=BORROWED').data)

    def test_invalid_inputs_and_csrf_do_not_write(self):
        for changes in [dict(borrowed_qty='0'), dict(returned_qty='-1'), dict(borrowed_qty='1.5'),
                        dict(borrower=''), dict(return_date='2026-08-01'), dict(borrow_date='invalid'),
                        dict(csrf_token='wrong')]:
            with self.subTest(changes=changes):
                self.assertEqual(self.client.post('/warehouse-borrow-log/new', data=dict(self.form, **changes)).status_code, 400)
        self.assertEqual(db.session.query(WarehouseBorrowLog).count(), 0)

    def test_error_status_and_escaped_content(self):
        form = dict(self.form, returned_qty='4', purpose='<script>alert(1)</script>')
        self.assertEqual(self.client.post('/warehouse-borrow-log/new', data=form).status_code, 303)
        page = self.client.get('/warehouse-borrow-log/?status=ERROR')
        self.assertIn(b'status-error', page.data)
        self.assertIn(b'&lt;script&gt;', page.data)
        self.assertNotIn(b'<script>', page.data)

    def test_serial_lookup(self):
        # Only lookup columns are needed; the production model has a PostgreSQL
        # composite primary key that SQLite cannot autoincrement.
        db.session.execute(db.text('CREATE TABLE receiving_log (serial_number TEXT, part_number TEXT)'))
        db.session.execute(db.text("INSERT INTO receiving_log VALUES ('Q1600095', 'NRU-161V-AWP'), ('DUP', 'A'), ('DUP', 'B')"))
        db.session.commit()
        for serial in ['Q1600095', ' q1600095 ', 'S/N Q1600095']:
            result = self.client.get('/warehouse-borrow-log/lookup-item', query_string={'serial_number': serial})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json['item_name'], 'NRU-161V-AWP')
        for serial in ['', 'NA', 'MISSING', 'Q160', '%']:
            result = self.client.get('/warehouse-borrow-log/lookup-item', query_string={'serial_number': serial})
            self.assertFalse(result.json['found'])
        self.assertEqual(self.client.get('/warehouse-borrow-log/lookup-item?serial_number=DUP').status_code, 409)

    def test_lookup_unavailable(self):
        with self.assertLogs(self.app.logger, level='ERROR'):
            result = self.client.get('/warehouse-borrow-log/lookup-item?serial_number=Q1600095')
        self.assertEqual(result.status_code, 503)
        self.assertFalse(result.json['found'])

    def batch_data(self, rows):
        data = MultiDict([('csrf_token', self.token)])
        for row in rows:
            for key, value in row.items():
                if key not in ('csrf_token', 'returned_qty', 'return_date', 'issued_by'):
                    data.add(key, value)
        return data

    def test_batch_save_and_ignore_unused_rows(self):
        blank = dict(self.form, serial_number='', item_number='')
        rows = [self.form, dict(self.form, serial_number='SN-2', item_number='PART-2'), blank]
        response = self.client.post('/warehouse-borrow-log/new-multiple', data=self.batch_data(rows), follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Saved 2 borrow records.', response.data)
        records = db.session.execute(db.select(WarehouseBorrowLog).order_by(WarehouseBorrowLog.id)).scalars().all()
        self.assertEqual([r.serial_number for r in records], ['SN-1', 'SN-2'])
        self.assertNotEqual(records[0].borrow_id, records[1].borrow_id)
        self.assertTrue(all(r.returned_qty == 0 and r.return_date is None and r.issued_by == '' for r in records))

    def test_batch_entry_columns(self):
        response = self.client.get('/warehouse-borrow-log/new-multiple')
        page = response.get_data(as_text=True)
        names = ['serial_number', 'item_number', 'borrowed_qty', 'warehouse', 'purpose', 'borrower', 'borrow_date']
        positions = [page.index(f'name="{name}"') for name in names]
        self.assertEqual(positions, sorted(positions))
        for name in ('returned_qty', 'return_date', 'issued_by'):
            self.assertNotIn(f'name="{name}"', page)

    def test_invalid_batch_saves_nothing_and_preserves_input(self):
        rows = [self.form, dict(self.form, borrowed_qty='-1', serial_number='SN-2')]
        response = self.client.post('/warehouse-borrow-log/new-multiple', data=self.batch_data(rows))
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'Row 2:', response.data)
        self.assertIn(b'value="SN-1"', response.data)
        self.assertIn(b'value="SN-2"', response.data)
        self.assertEqual(db.session.query(WarehouseBorrowLog).count(), 0)

    def test_batch_empty_csrf_and_limits(self):
        blank = dict(self.form, serial_number='', item_number='')
        self.assertEqual(self.client.post('/warehouse-borrow-log/new-multiple', data=self.batch_data([blank])).status_code, 400)
        bad_token = self.batch_data([self.form]); bad_token['csrf_token'] = 'invalid'
        self.assertEqual(self.client.post('/warehouse-borrow-log/new-multiple', data=bad_token).status_code, 400)
        self.assertEqual(self.client.post('/warehouse-borrow-log/new-multiple', data=self.batch_data([self.form] * 101)).status_code, 400)
        malformed = self.batch_data([self.form]); malformed.add('borrower', 'Extra')
        self.assertEqual(self.client.post('/warehouse-borrow-log/new-multiple', data=malformed).status_code, 400)
        self.assertEqual(db.session.query(WarehouseBorrowLog).count(), 0)


if __name__ == '__main__':
    unittest.main()
