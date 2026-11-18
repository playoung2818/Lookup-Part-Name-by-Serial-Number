"""Incoming form tests: Word in memory, mocked DB only, never schema setup."""
from datetime import date
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from docx import Document
from sqlalchemy.exc import SQLAlchemyError

from app import create_app
from functions.incoming_form import grouped_records, incoming_document, invoice_records, template_content, HEADERS
from test_receiving_workspace import metadata


def template():
    doc = Document()
    doc.add_paragraph('Original incoming form heading')
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def row(id, box='46--34', part='PA-1000W-MW', pod='POD-1', sn='', qty=1):
    return dict(id=id, invoice_number='8003593', box_number=box, part_number=part,
                pod_number=pod, serial_number=sn, quantity=qty)


class IncomingDocumentTests(unittest.TestCase):
    def test_grouping_sum_distinct_serials_and_stable_carton_range_sort(self):
        records = [row(1, sn=' SN1 '), row(2, box='2--1-2', part='OTHER', sn='A'),
                   row(3, sn='SN1', qty=3), row(4, sn='SN2'),
                   row(5, box='2--1', sn=None, qty=2), row(6, box='BOX-X', sn=''),
                   row(7, pod='OTHER-POD', sn='S3')]
        groups = grouped_records(records)
        self.assertEqual([g['box'] for g in groups], ['2--1', '2--1-2', '46--34', '46--34', 'BOX-X'])
        self.assertEqual(groups[2]['quantity'], 5)
        self.assertEqual(groups[2]['serials'], ['SN1', 'SN2'])
        self.assertEqual(groups[0]['serials'], ['NA'])
        self.assertEqual(groups[-1]['serials'], ['NA'])

    def test_template_preserved_headers_pass_and_result_format(self):
        content, count = incoming_document([row(1, sn='SN1'), row(2, sn='SN2')],
                                           '008003593', template(), True)
        doc = Document(content)
        self.assertEqual(count, 1)
        self.assertEqual(doc.paragraphs[0].text, 'Original incoming form heading')
        self.assertEqual([c.text for c in doc.tables[-1].rows[0].cells], HEADERS)
        self.assertEqual([c.text for c in doc.tables[-1].rows[1].cells],
                         ['PA-1000W-MW', '2', 'SN1, SN2', 'Neousys Technology', '008003593', 'PASS', ''])
        self.assertEqual(doc.paragraphs[-1].text, '[Receiving & Inspection Result: Pass]')
        self.assertTrue(doc.paragraphs[-1].runs[0].bold)
        self.assertEqual(doc.paragraphs[-1].runs[0].font.size.pt, 14)

    def test_pending_default_and_fractional_quantity_not_truncated(self):
        content, _ = incoming_document([row(1, qty=1.5)], '8003593', template())
        doc = Document(content)
        self.assertEqual(doc.tables[-1].rows[1].cells[1].text, '1.5')
        self.assertEqual(doc.tables[-1].rows[1].cells[5].text, 'Pending')
        self.assertIn('Pending', doc.paragraphs[-1].text)

    def test_exact_invoice_select_only(self):
        engine = MagicMock()
        connection = engine.connect.return_value.__enter__.return_value
        connection.execute.return_value.mappings.return_value = [row(1)]
        with patch('functions.incoming_form.receiving_table', return_value=metadata()):
            self.assertEqual(invoice_records(engine, '8003593'), [row(1)])
        statement = connection.execute.call_args.args[0]
        self.assertTrue(statement.is_select)
        self.assertEqual(statement.compile().params['invoice_number_1'], '8003593')
        connection.commit.assert_not_called()
        with self.assertRaises(ValueError):
            invoice_records(engine, '')

    def test_missing_invalid_and_configured_templates(self):
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            template_content(configured_path='missing-template.docx')
        from werkzeug.datastructures import FileStorage
        with self.assertRaisesRegex(ValueError, 'valid Word'):
            template_content(FileStorage(BytesIO(b'not a docx'), filename='bad.docx'))
        with self.assertRaisesRegex(ValueError, '.docx'):
            template_content(FileStorage(BytesIO(b'not docx'), filename='bad.txt'))
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'Incoming Form Template.docx'
            content = template()
            path.write_bytes(content)
            self.assertEqual(template_content(configured_path=str(path)), content)
            self.assertEqual(path.read_bytes(), content)


class IncomingRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test',
                               'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                               'RECEIVING_INCOMING_TEMPLATE_PATH': ''})
        self.app.instance_path = self.temp.name
        self.client = self.app.test_client()
        page = self.client.get('/receiving')
        self.assertIn(b'4. Generate incoming form', page.data)
        with self.client.session_transaction() as session:
            self.csrf = session['receiving_csrf']
        self.reader = patch('functions.incoming_form.invoice_records', return_value=[row(1)])
        self.read = self.reader.start()
        self.addCleanup(self.reader.stop)

    def post(self, **extra):
        data = {'csrf_token': self.csrf, 'invoice_number': '8003593',
                'template': (BytesIO(template()), 'Incoming Form Template.docx')}
        data.update(extra)
        return self.client.post('/receiving/incoming-form', data=data)

    def test_download_without_loaded_invoice_or_workspace_change(self):
        with self.client.session_transaction() as session:
            owner = session['receiving_owner']
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertIn(f'I{date.today():%m}-{date.today():%m%d%y}-TaiwanHQ-8003593.docx', response.headers['Content-Disposition'])
        self.assertEqual(response.headers['X-Incoming-Lines'], '1')
        self.assertEqual(Document(BytesIO(response.data)).tables[-1].rows[1].cells[5].text, 'Pending')
        self.assertFalse(list(Path(self.temp.name).rglob('active.json')))
        with self.client.session_transaction() as session:
            self.assertEqual(session['receiving_owner'], owner)

    def test_filename_uses_generation_date_and_month(self):
        with patch('routes.Receiving_Routes.date') as clock:
            clock.today.return_value = date(2027, 1, 2)
            response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertIn('I01-010227-TaiwanHQ-8003593.docx', response.headers['Content-Disposition'])

    def test_pass_requires_explicit_confirmation(self):
        response = self.post(inspection_passed='yes')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Document(BytesIO(response.data)).tables[-1].rows[1].cells[5].text, 'PASS')
        self.assertEqual(self.post(inspection_passed='invalid').status_code, 400)

    def test_errors_no_records_missing_template_csrf_and_db_failure(self):
        self.read.side_effect = ValueError('No receiving records found for invoice 8003593.')
        response = self.post()
        self.assertEqual(response.status_code, 400)
        self.assertIn('No receiving', response.json['error'])
        self.read.side_effect = None
        response = self.client.post('/receiving/incoming-form', data={
            'csrf_token': self.csrf, 'invoice_number': '8003593'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('template', response.json['error'].lower())
        self.read.reset_mock()
        self.assertEqual(self.post(csrf_token='bad').status_code, 400)
        self.read.assert_not_called()
        self.read.side_effect = SQLAlchemyError('offline')
        self.assertEqual(self.post().status_code, 503)


if __name__ == '__main__':
    unittest.main()
