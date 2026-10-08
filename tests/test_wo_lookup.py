import unittest
from unittest.mock import patch
from app import create_app
from functions.wo_lookup import display_record


def record(source='legacy_word', serial='Q3800118', notes=''):
    return display_record({'id':'test', 'sales_order':'SO-20261234', 'record_source':source,
        'legacy_word_id':10 if source == 'legacy_word' else None, 'release_number':-10 if source == 'legacy_word' else 1,
        'Document #':None if source == 'legacy_word' else 'WO-2610-0123',
        'items':[dict(item='RAM', quantity=8, serials=[serial], notes=notes)]})


class WoLookupTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SECRET_KEY':'test', 'SQLALCHEMY_DATABASE_URI':'sqlite:///:memory:'})
        self.client = self.app.test_client()

    def test_details_preserve_unknown_qty_and_have_no_path(self):
        value = record()
        self.assertIsNone(value['file_path'])
        self.assertEqual(value['details'][0]['sn'], 'Q3800118')
        value = display_record(dict(id='x', sales_order='SO-20261234', items=[dict(item='RAM', quantity=None, legacy_quantity_text='unknown', serials=['Q1'], notes='Keep')]))
        self.assertEqual(value['details'][0]['qty'], 'unknown')
        self.assertEqual(value['details'][0]['notes'], 'Keep')

    def test_so_search_shows_both_sources_without_word_download(self):
        with patch('routes.Work_Order_Routes.find_work_orders', return_value=[record(), record('mes')]):
            response = self.client.get('/work-orders/?q=SO-20261234')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Legacy Word history #10', response.data)
        self.assertIn(b'MES', response.data)
        self.assertIn(b'Q3800118', response.data)
        self.assertNotIn(b'/document/word/', response.data)

    def test_serial_lookup_checks_serial_not_notes(self):
        with patch('routes.Index_Routes.find_by_serial', return_value=[record(), record('mes', serial='OTHER', notes='Q3800118')]):
            response = self.client.post('/', data={'word_serial_query':'Q3800118'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Legacy Word history #10', response.data)
        self.assertNotIn(b'WO-2610-0123', response.data)
        self.assertNotIn(b'DOCX', response.data)

    def test_old_word_api_is_retired(self):
        self.assertEqual(self.client.get('/api/word-files').status_code, 404)


if __name__ == '__main__':
    unittest.main()
