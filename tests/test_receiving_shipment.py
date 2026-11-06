import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from openpyxl import Workbook, load_workbook
from sqlalchemy.exc import SQLAlchemyError

from app import create_app
from functions.receiving_import import read_upload
from functions.receiving_shipment import generate, incoming_document, parse_packing, read_references, read_serials
from datetime import date


PACKING = '''Packing List
INV NO.:8003610
1-2 Model-A 2 1.00 2.00
A computer
Customer PO No.:POD-1
Cbl-Test 3 0.10
Cable
Customer PO No.:POD-2
Unknown-Part 2 0.10
No POD supplied
TOTAL 2 CTNS
7 2.00 3.00 KG'''


def make_excel(path, rows):
    book = Workbook()
    for row in rows:
        book.active.append(row)
    book.save(path)
    book.close()


def pdf_mock(text=PACKING):
    pdf = MagicMock()
    pdf.pages = [MagicMock()]
    pdf.pages[0].extract_text.return_value = text
    context = MagicMock()
    context.__enter__.return_value = pdf
    return context


class ShipmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.serials = self.directory / 'export.xlsx'
        self.references = self.directory / 'references.xlsx'
        make_excel(self.serials, [
            ['Customer PO No', 'Ordering Model', 'S/N', 'Invoice No'],
            ['POD-1', 'Model-A', 'SN-1', '8003610'],
            ['POD-1', 'Model-A', 'SN-2', '8003610']])
        make_excel(self.references, [
            ['POD', 'Reference'], ['POD-1', 'Customer A'], ['POD-1', 'Customer A_signed'],
            ['POD-2', 'Inventory']])
        self.receipt = {'date': date(2026, 11, 4), 'reference': '80003610', 'lines': []}

    def tearDown(self):
        self.temp.cleanup()

    def build(self, text=PACKING):
        with patch('functions.receiving_shipment.parse_receipt', return_value=self.receipt), \
             patch('functions.receiving_shipment.pdfplumber.open', return_value=pdf_mock(text)):
            return generate(self.directory / 'receipt.pdf', self.directory / 'packing.pdf',
                            self.serials, reference_path=self.references)

    def test_generation_preserves_cartons_serials_bulk_and_references(self):
        book = self.build()
        rows = list(book['Receiving Log'].iter_rows(min_row=2, values_only=True))
        self.assertEqual(len(rows), 3)
        self.assertEqual([r[5] for r in rows], ['SN-1', 'SN-2', ''])
        self.assertEqual([r[6] for r in rows], [1, 1, 3])
        self.assertTrue(all(r[1] == '80003610' and r[2] == '2--1-2' for r in rows))
        self.assertEqual([r[7] for r in rows], ['Customer A', 'Customer A', 'Inventory'])
        self.assertEqual(book['Exceptions'].max_row, 2)
        self.assertEqual(book['Exceptions']['C2'].value, 'Unknown-Part')
        content = io.BytesIO()
        book.save(content)
        records, errors, skipped = read_upload(content.getvalue())
        self.assertEqual((len(records), errors, skipped), (3, [], 0))
        self.assertEqual(records[2]['serial_number'], '')
        self.assertEqual(records[2]['Reference'], 'Inventory')

    def test_printed_packing_totals_must_match(self):
        with self.assertRaisesRegex(ValueError, 'quantity does not match'):
            self.build(PACKING.replace('7 2.00', '8 2.00'))

    def test_carton_carries_across_pages(self):
        context = pdf_mock()
        context.__enter__.return_value.pages = [MagicMock(), MagicMock()]
        context.__enter__.return_value.pages[0].extract_text.return_value = 'INV NO.:1\n1 Model-A 1 1.00\nCustomer PO No.:POD-1'
        context.__enter__.return_value.pages[1].extract_text.return_value = 'Packing List\nModel-B 1 1.00\nCustomer PO No.:POD-2\nTOTAL 1 CTNS\n2 2.00 3.00 KG'
        with patch('functions.receiving_shipment.pdfplumber.open', return_value=context):
            items, _, _, _ = parse_packing('test.pdf')
        self.assertEqual([item['box'] for item in items], ['1--1', '1--1'])

    def test_reference_first_exact_match(self):
        self.assertEqual(read_references(self.references)['POD-1'], 'Customer A')

    def test_serial_invoice_and_duplicates_block_generation(self):
        with self.assertRaisesRegex(ValueError, 'invoice mismatch'):
            read_serials(self.serials, 'OTHER')
        make_excel(self.serials, [
            ['Customer PO No', 'Ordering Model', 'S/N', 'Invoice No'],
            ['POD-1', 'Model-A', 'same', '8003610'],
            ['POD-1', 'Model-A', 'SAME', '8003610']])
        with self.assertRaisesRegex(ValueError, 'Duplicate serial'):
            read_serials(self.serials, '8003610')

    def test_generation_budget(self):
        text = PACKING.replace('Model-A 2', 'Model-A 20001').replace('7 2.00', '20006 2.00')
        with self.assertRaisesRegex(ValueError, '20,000'):
            self.build(text)

    def test_word_document_is_pending_not_pass(self):
        book = self.build()
        content = io.BytesIO()
        book.save(content)
        from docx import Document
        doc = Document(incoming_document(content.getvalue()))
        text = '\n'.join(p.text for p in doc.paragraphs)
        self.assertIn('Pending', text)
        self.assertNotIn('PASS', text)
        self.assertTrue(all(row.cells[-1].text == 'Pending' for row in doc.tables[0].rows[1:]))


class ShipmentRouteTests(ShipmentTests):
    def setUp(self):
        super().setUp()
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test', 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                               'RECEIVING_REFERENCE_PATH': ''})
        self.app.instance_path = str(self.directory / 'instance')
        from test_receiving_workspace import FakeEngine, metadata
        from functions.receiving_workspace import save_database, save_row, load_database, search_invoice
        self.engine = FakeEngine()
        table = metadata()
        for target, effect in (
            ('functions.receiving_workspace.lock_receiving', None),
            ('functions.receiving_workspace.receiving_table', lambda connection: table),
            ('routes.Receiving_Routes.search_invoice', lambda ignored, *args: search_invoice(self.engine, *args)),
            ('routes.Receiving_Routes.save_database', lambda ignored, state, persist: save_database(self.engine, state, persist)),
            ('routes.Receiving_Routes.save_row', lambda ignored, *args: save_row(self.engine, *args)),
            ('routes.Receiving_Routes.load_database', lambda ignored, state, persist: load_database(self.engine, state, persist)),
        ):
            patcher = patch(target, side_effect=effect)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = self.app.test_client()
        self.client.get('/receiving')
        with self.client.session_transaction() as session:
            self.csrf = session['receiving_csrf']

    def tearDown(self):
        from models.models import db
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        super().tearDown()

    def post_generate(self, commit=True):
        book = self.build()
        active = self.client.get('/receiving/workspace').json['workspace']
        with patch('functions.receiving_shipment.generate', return_value=book):
            response = self.client.post('/receiving/generate', data={
                'csrf_token': self.csrf, 'receipt': (io.BytesIO(b'pdf'), 'receipt.pdf'),
                'workspace_id': active['id'] if active else '', 'revision': active['revision'] if active else '',
                'packing': (io.BytesIO(b'pdf'), 'packing.pdf'),
                'serials': (io.BytesIO(self.serials.read_bytes()), 'export.xlsx')}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        state = self.client.get('/receiving/workspace').json['workspace']
        if commit:
            saved = self.client.post('/receiving/save', json={'workspace_id': state['id'], 'revision': state['revision']},
                                     headers={'X-CSRF-Token': self.csrf})
            self.assertEqual(saved.status_code, 200)
            state = saved.json['workspace']
        return response, state

    def row_payload(self, state, index, value):
        row = state['rows'][index]
        return {'workspace_id': state['id'], 'row_id': row['row_id'],
                'serial_number': value, 'row_version': row['row_version']}

    def test_reviewed_template_commit_and_row_edits_update_one_id(self):
        response, state = self.post_generate()
        self.assertEqual(len(self.engine.rows), 3)
        self.assertTrue(all(row['db_id'] for row in state['rows']))
        self.assertNotIn(b'Save draft now', response.data)
        self.assertNotIn(b'Save table to database', response.data)
        self.assertNotIn(b'Upload receiving workbook', response.data)
        ids = [row['id'] for row in self.engine.rows]
        response = self.client.post('/receiving/row', headers={'X-CSRF-Token': self.csrf},
                                    json=self.row_payload(state, 0, 'SCANNED-123'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['id'] for row in self.engine.rows], ids)
        self.assertEqual(self.engine.rows[0]['serial_number'], 'SCANNED-123')
        data = {'csrf_token': self.csrf, 'workspace_id': state['id']}
        download = self.client.post('/receiving/download', data=data)
        book = load_workbook(io.BytesIO(download.data), read_only=True)
        self.assertEqual(book['Receiving Log']['F2'].value, 'SCANNED-123')
        self.assertIsNone(book['Receiving Log']['F4'].value)
        book.close()
        self.assertEqual(self.client.post('/receiving/download', data=dict(data, format='docx')).status_code, 200)

    def test_refresh_uses_database_not_file_cached_values(self):
        _, state = self.post_generate()
        self.engine.rows[0]['serial_number'] = 'CHANGED-OUTSIDE-WEBSITE'
        self.engine.rows[0]['Reference'] = 'UPDATED-DB-REFERENCE'
        page = self.client.get('/receiving')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'CHANGED-OUTSIDE-WEBSITE', page.data)
        self.assertIn(b'UPDATED-DB-REFERENCE', page.data)
        with patch('routes.Receiving_Routes.load_database', side_effect=SQLAlchemyError('offline')):
            page = self.client.get('/receiving')
        self.assertEqual(page.status_code, 503)
        self.assertNotIn(b'CHANGED-OUTSIDE-WEBSITE', page.data)
        self.assertNotIn(b'class="sn-input"', page.data)

    def test_bulk_serial_saves_directly_without_changing_qty(self):
        response, state = self.post_generate()
        self.assertNotIn(b'disabled placeholder="Bulk row"', response.data)
        response = self.client.post('/receiving/row', headers={'X-CSRF-Token': self.csrf},
                                    json=self.row_payload(state, 2, 'BULK-SN'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.engine.rows[2]['serial_number'], 'BULK-SN')
        self.assertEqual(self.engine.rows[2]['quantity'], 3)
        self.assertIn(b'BULK-SN', self.client.get('/receiving').data)

    def test_download_csrf_tampering_and_cross_session(self):
        _, state = self.post_generate()
        self.assertEqual(self.client.post('/receiving/download', data={'workspace_id': state['id']}).status_code, 400)
        self.assertEqual(self.client.post('/receiving/download', data={'csrf_token': self.csrf, 'workspace_id': 'bad'}).status_code, 409)
        other = self.app.test_client()
        other.get('/receiving')
        with other.session_transaction() as session:
            other_csrf = session['receiving_csrf']
        self.assertEqual(other.post('/receiving/download', data={'csrf_token': other_csrf, 'workspace_id': state['id']}).status_code, 409)

    def test_stale_row_and_failed_upload_preserve_database(self):
        _, state = self.post_generate()
        data = self.row_payload(state, 0, 'SCANNED')
        self.assertEqual(self.client.post('/receiving/row', json=data).status_code, 400)
        self.assertEqual(self.client.post('/receiving/row', json=data, headers={'X-CSRF-Token': self.csrf}).status_code, 200)
        data['serial_number'] = 'STALE-OVERWRITE'
        self.assertEqual(self.client.post('/receiving/row', json=data, headers={'X-CSRF-Token': self.csrf}).status_code, 409)
        self.assertEqual(self.client.post('/receiving/generate', data={'csrf_token': self.csrf}).status_code, 400)
        page = self.client.get('/receiving')
        self.assertIn(b'SCANNED', page.data)
        self.assertIn(b'Expires=', page.headers.get('Set-Cookie', '').encode())
        self.assertEqual(self.client.get('/receiving/workspace').json['workspace']['id'], state['id'])

    def test_regeneration_cannot_overwrite_existing_invoice(self):
        _, state = self.post_generate()
        _, replacement = self.post_generate(commit=False)
        self.assertNotEqual(replacement['id'], state['id'])
        before = self.engine.writes
        response = self.client.post('/receiving/save', json={'workspace_id': replacement['id'], 'revision': replacement['revision']},
                                    headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.engine.writes, before)
        self.assertEqual(len(self.engine.rows), 3)

    def template_payload(self, state):
        fields = ('row_id', 'entry_date', 'box_number', 'pod_number', 'part_number', 'serial_number', 'quantity', 'Reference')
        return {'workspace_id': state['id'], 'revision': state['revision'],
                'rows': [{key: row.get(key, '') for key in fields} for row in state['rows']]}

    def test_generation_is_draft_and_review_edits_only_write_on_explicit_commit(self):
        page, state = self.post_generate(commit=False)
        self.assertEqual(self.engine.writes, 0)
        self.assertEqual(state['mode'], 'draft')
        self.assertEqual(len(state['rows']), 3)
        self.assertNotIn(b'name="references"', page.data)
        data = self.template_payload(state)
        data['rows'][0].update(part_number='REVIEWED-PART', quantity='2', Reference='Reviewed note')
        headers = {'X-CSRF-Token': self.csrf}
        result = self.client.post('/receiving/template', json=data, headers=headers)
        self.assertEqual(result.status_code, 200)
        reviewed = result.json['workspace']
        self.assertEqual(self.engine.writes, 0)
        self.assertEqual(self.client.post('/receiving/row', json=self.row_payload(reviewed, 0, 'SN'), headers=headers).status_code, 400)
        stale = self.client.post('/receiving/save', json={'workspace_id': state['id'], 'revision': state['revision']}, headers=headers)
        self.assertEqual(stale.status_code, 409)
        result = self.client.post('/receiving/save', json={'workspace_id': reviewed['id'], 'revision': reviewed['revision']}, headers=headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.engine.rows[0]['part_number'], 'REVIEWED-PART')
        self.assertEqual(self.engine.rows[0]['quantity'], 2)
        self.assertEqual(result.json['workspace']['mode'], 'entry')
        self.assertEqual(self.client.post('/receiving/template', json=self.template_payload(result.json['workspace']), headers=headers).status_code, 409)
        writes = self.engine.writes
        self.assertEqual(self.client.post('/receiving/save', json={'workspace_id': reviewed['id']}, headers=headers).status_code, 200)
        self.assertEqual(self.engine.writes, writes)

    def test_template_lost_commit_response_recovers_without_reinserting(self):
        _, state = self.post_generate(commit=False)
        self.engine.fail_commit = 'after'
        headers = {'X-CSRF-Token': self.csrf}
        response = self.client.post('/receiving/save', json={'workspace_id': state['id'], 'revision': state['revision']}, headers=headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(len(self.engine.rows), 3)
        recovered = self.client.get('/receiving/workspace').json['workspace']
        self.assertEqual(recovered['mode'], 'entry')
        writes = self.engine.writes
        response = self.client.post('/receiving/save', json={'workspace_id': state['id']}, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.engine.writes, writes)

    def test_moved_invoice_row_cannot_be_edited_even_on_idempotent_retry(self):
        _, state = self.post_generate()
        self.engine.rows[0]['invoice_number'] = 'MOVED-TO-OTHER'
        response = self.client.post('/receiving/row', json=self.row_payload(state, 0, self.engine.rows[0]['serial_number']),
                                    headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.engine.rows[0]['invoice_number'], 'MOVED-TO-OTHER')

    def test_template_invoice_tampering_and_invalid_rows_are_atomic(self):
        _, state = self.post_generate(commit=False)
        data = self.template_payload(state)
        data['rows'][0]['invoice_number'] = 'OTHER'
        headers = {'X-CSRF-Token': self.csrf}
        self.assertEqual(self.client.post('/receiving/template', json=data, headers=headers).status_code, 400)
        data = self.template_payload(state)
        data['rows'][0]['part_number'] = 'SHOULD-NOT-PERSIST'
        data['rows'][1]['quantity'] = '-1'
        self.assertEqual(self.client.post('/receiving/template', json=data, headers=headers).status_code, 400)
        current = self.client.get('/receiving/workspace').json['workspace']
        self.assertEqual(current['rows'][0]['part_number'], state['rows'][0]['part_number'])
        self.assertEqual(self.engine.writes, 0)

    def test_search_invoice_and_reject_cross_invoice_or_other_fields(self):
        _, state = self.post_generate()
        from copy import deepcopy
        other_record = deepcopy(self.engine.rows[0])
        other_record.update(id=900, invoice_number='OTHER-INV', serial_number='OTHER-SN')
        self.engine.rows.append(other_record)
        result = self.client.post('/receiving/search', data={'csrf_token': self.csrf, 'invoice_number': '80003610',
                                  'workspace_id': state['id'], 'revision': state['revision']}, follow_redirects=True)
        self.assertEqual(result.status_code, 200)
        current = self.client.get('/receiving/workspace').json['workspace']
        self.assertEqual(len(current['rows']), 3)
        self.assertEqual(current['mode'], 'entry')
        self.assertTrue(all(row['invoice_number'] == '80003610' for row in current['rows']))
        headers = {'X-CSRF-Token': self.csrf}
        data = self.row_payload(current, 0, 'OK')
        data['quantity'] = 100
        self.assertEqual(self.client.post('/receiving/row', json=data, headers=headers).status_code, 400)
        data = self.row_payload(current, 0, 'OK')
        data['row_id'] = state['rows'][0]['row_id']
        self.assertEqual(self.client.post('/receiving/row', json=data, headers=headers).status_code, 400)
        self.assertEqual(self.engine.rows[-1]['serial_number'], 'OTHER-SN')
        self.assertEqual(self.client.post('/receiving/row', json=self.row_payload(current, 0, 'OK'), headers=headers).status_code, 200)
        self.assertEqual(self.engine.rows[-1]['serial_number'], 'OTHER-SN')
        result = self.client.post('/receiving/search', data={'csrf_token': self.csrf, 'invoice_number': 'missing',
                                  'workspace_id': current['id'], 'revision': current['revision']})
        self.assertEqual(result.status_code, 400)

    def test_upload_validation_and_no_table_creation(self):
        response = self.client.post('/receiving/generate', data={'csrf_token': self.csrf})
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'Choose a receipt file', response.data)


if __name__ == '__main__':
    unittest.main()
