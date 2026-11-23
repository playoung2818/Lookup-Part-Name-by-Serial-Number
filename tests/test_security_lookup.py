"""Security, schema-safety, lookup and path tests. In-memory SQLite only."""
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import create_app
from models.models import db, ReceivingLog


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.invoices, self.outgoing = root / 'invoices', root / 'outgoing'
        self.invoices.mkdir()
        self.outgoing.mkdir()
        (root / 'secret-8003593.pdf').write_bytes(b'outside')
        (self.invoices / 'INVOICE_NTA_8003593.pdf').write_bytes(b'invoice')
        (self.outgoing / 'OUT-1.pdf').write_bytes(b'outgoing')
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test',
                               'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                               'INVOICE_DIR': str(self.invoices), 'OUTGOING_DIR': str(self.outgoing),
                               'SHEET_UPDATE_TOKEN': 'token-123'})
        self.client = self.app.test_client()
        self.context = self.app.app_context()
        self.context.push()
        self.addCleanup(self.context.pop)
        # Test-only in-memory table; the real database is never touched.
        ReceivingLog.__table__.create(db.engine)
        self.addCleanup(db.engine.dispose)
        self.addCleanup(db.session.remove)

    def add(self, **values):
        record = ReceivingLog(**values)
        db.session.add(record)
        db.session.commit()
        return record


class SecurityTests(AppTestCase):
    def test_arbitrary_path_word_routes_removed(self):
        for path in ['/word-preview?file_path=C:/x.docx', '/word-download?file_path=C:/x.docx']:
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_invoice_download_confined_to_configured_folder(self):
        ok = self.client.get('/invoice-download?invoice_number=8003593')
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.data, b'invoice')
        ok.close()
        for bad in ['..\\secret', '../secret', 'C:secret', '..']:
            self.assertEqual(self.client.get('/invoice-download', query_string={'invoice_number': bad}).status_code, 400)

    def test_missing_folders_return_clear_503(self):
        self.app.config['INVOICE_DIR'] = str(Path(self.temp.name) / 'missing')
        self.app.config['OUTGOING_DIR'] = ''
        self.assertEqual(self.client.get('/invoice-download?invoice_number=8003593').status_code, 503)
        self.assertEqual(self.client.get('/outgoing-invoice?invoice_number=OUT-1').status_code, 503)
        # An unset folder must not fall back to the working directory.
        self.assertEqual(self.client.get('/work-orders/outgoing-pdf?path=app.py').status_code, 404)

    def test_outgoing_invoice_uses_configured_folder(self):
        response = self.client.get('/outgoing-invoice?invoice_number=OUT-1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'outgoing')
        response.close()

    def post_sheet(self, data, token='token-123'):
        headers = {'Authorization': f'Bearer {token}'} if token else {}
        return self.client.post('/api/sheet-update', json=data, headers=headers)

    def test_sheet_update_requires_configured_token(self):
        self.assertEqual(self.post_sheet({'serial_number': 'SN1'}, token=None).status_code, 401)
        self.assertEqual(self.post_sheet({'serial_number': 'SN1'}, token='wrong').status_code, 401)
        self.app.config['SHEET_UPDATE_TOKEN'] = ''
        self.assertEqual(self.post_sheet({'serial_number': 'SN1'}).status_code, 403)
        self.assertEqual(ReceivingLog.query.count(), 0)

    def test_sheet_update_whitelists_validates_and_upserts(self):
        self.assertEqual(self.post_sheet({'serial_number': 'SN1', 'id': 99}).status_code, 400)
        self.assertEqual(self.post_sheet({'serial_number': 'SN1', 'quantity': 'x'}).status_code, 400)
        self.assertEqual(self.post_sheet({'serial_number': 'SN1', 'entry_date': '11/18/2026'}).status_code, 400)
        self.assertEqual(self.post_sheet({'serial_number': 'NA'}).status_code, 400)
        self.assertEqual(ReceivingLog.query.count(), 0)
        created = self.post_sheet({'serial_number': ' SN1 ', 'part_number': 'P1', 'quantity': 1,
                                   'entry_date': '2026-11-18'})
        self.assertEqual(created.json['result'], 'created')
        updated = self.post_sheet({'serial_number': 'sn1', 'part_number': 'P2'})
        self.assertEqual(updated.json['result'], 'updated')
        record = ReceivingLog.query.one()
        self.assertEqual((record.serial_number, record.part_number, record.entry_date), ('SN1', 'P2', date(2026, 11, 18)))

    def test_sheet_update_rejects_ambiguous_serial(self):
        self.add(serial_number='DUP', part_number='A')
        self.add(serial_number='dup ', part_number='B')
        self.assertEqual(self.post_sheet({'serial_number': 'DUP', 'part_number': 'C'}).status_code, 409)
        self.assertEqual(sorted(r.part_number for r in ReceivingLog.query), ['A', 'B'])


class LookupTests(AppTestCase):
    def test_lookup_ignores_case_and_spaces_and_returns_all_matches(self):
        self.add(serial_number=' abc123 ', part_number='OLD', invoice_number='1')
        self.add(serial_number='ABC123', part_number='NEW', invoice_number='2')
        self.add(serial_number='OTHER', part_number='X')
        response = self.client.get('/api/lookup?serial_number=Abc123')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['part_name'], 'NEW')  # newest first
        self.assertEqual(response.json['match_count'], 2)
        self.assertEqual([m['part_name'] for m in response.json['matches']], ['NEW', 'OLD'])
        with patch('routes.Index_Routes.find_by_serial', return_value=[]):
            page = self.client.get('/?serial_number=abc123')
        self.assertIn(b'2 receiving records match', page.data)
        self.assertIn(b'OLD', page.data)
        self.assertIn(b'NEW', page.data)

    def test_placeholders_and_missing(self):
        self.add(serial_number='NA', part_number='BULK')
        self.assertEqual(self.client.get('/api/lookup?serial_number=na').status_code, 400)
        self.assertEqual(self.client.get('/api/lookup?serial_number=NOPE').status_code, 404)
        self.assertEqual(self.client.get('/api/lookup?serial_number=' + 'A' * 256).status_code, 400)


class SchemaSafetyTests(unittest.TestCase):
    def test_model_identity_and_startup_never_create_tables(self):
        self.assertEqual([c.name for c in ReceivingLog.__table__.primary_key.columns], ['id'])
        import app as app_module
        with patch.object(app_module, 'create_app') as factory, \
             patch.object(app_module, 'already_running', return_value=False), \
             patch.object(db, 'create_all') as create_all:
            app_module.main()
        factory.return_value.run.assert_called_once()
        create_all.assert_not_called()

    def test_create_db_reports_only_without_confirmation(self):
        import create_db
        with patch('create_db.create_app') as factory, \
             patch('create_db.missing_tables', return_value=['warehouse_borrow_log']), \
             patch.object(db.metadata, 'create_all') as create_all:
            factory.return_value.app_context.return_value.__enter__.return_value = None
            self.assertEqual(create_db.main([]), 0)
            with self.assertRaises(SystemExit):
                create_db.main(['--create', 'warehouse_borrow_log'])
            with self.assertRaises(SystemExit):
                create_db.main(['--create', 'receiving_log', '--confirm'])
        create_all.assert_not_called()

    def test_folders_default_relative_to_home(self):
        import os
        from config import Config
        for name in ('INVOICE_DIR', 'OUTGOING_DIR', 'RECEIVING_INCOMING_TEMPLATE_PATH'):
            if name not in os.environ:
                self.assertTrue(Path(getattr(Config, name)).is_relative_to(Path.home()), name)


if __name__ == '__main__':
    unittest.main()
