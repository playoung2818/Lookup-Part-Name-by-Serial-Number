"""Document links explain why a recorded file cannot be served (no real shares used)."""
import errno
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from app import create_app


class DocumentErrorTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test', 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
        self.client = self.app.test_client()

    def get(self, path_value, raise_lookup=False):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        if raise_lookup:
            connection.execute.side_effect = RuntimeError('database offline')
        else:
            connection.execute.return_value.scalar.return_value = path_value
        engine = MagicMock()
        engine.connect.return_value = connection
        with patch('routes.Work_Order_Routes.db', MagicMock(engine=engine)):
            return self.client.get('/work-orders/document/pdf/3385')

    def test_existing_file_is_served(self):
        pdf = Path(self.temp.name) / 'WO-1.pdf'
        pdf.write_bytes(b'%PDF-1.4 test')
        response = self.get(str(pdf))
        self.assertEqual((response.status_code, response.data), (200, b'%PDF-1.4 test'))
        response.close()

    def test_unknown_record(self):
        response = self.get(None)
        self.assertEqual(response.status_code, 404)
        self.assertIn(b'no PDF document record #3385', response.data)

    def test_unreachable_share_is_503_with_reason_and_logged(self):
        path = r'\\quickbook2024\d\Drive D\QuickBooks\WO-20261703.pdf'
        denied = OSError(errno.EACCES, 'Access is denied')
        denied.winerror = 5
        real_isfile, real_listdir = os.path.isfile, os.listdir

        def listdir(target):
            if str(target).startswith('\\\\quickbook2024'):
                raise denied
            return real_listdir(target)
        # Only the fake share is affected; Flask's own file checks stay real.
        with patch('os.path.isfile', side_effect=lambda p: False if str(p).startswith('\\\\') else real_isfile(p)), \
             patch('os.listdir', side_effect=listdir), \
             self.assertLogs(self.app.logger, 'WARNING') as logs:
            response = self.get(path)
        self.assertEqual(response.status_code, 503)
        self.assertIn(b'File share unavailable', response.data)
        self.assertIn(rb'\\quickbook2024\d (access is denied)', response.data)
        self.assertIn(b'WO-20261703.pdf', response.data)
        self.assertIn('share: access is denied', logs.output[0])

    def test_missing_folder_and_missing_file(self):
        response = self.get(str(Path(self.temp.name) / 'gone' / 'WO-2.pdf'))
        self.assertEqual(response.status_code, 503)
        self.assertIn(b'Document folder unavailable', response.data)
        response = self.get(str(Path(self.temp.name) / 'WO-3.pdf'))
        self.assertEqual(response.status_code, 404)
        self.assertIn(b'no longer in its folder', response.data)

    def test_database_failure_is_503_not_500(self):
        response = self.get(None, raise_lookup=True)
        self.assertEqual(response.status_code, 503)
        self.assertIn(b'could not be read from the database', response.data)

    def test_non_pdf_record_still_rejected(self):
        self.assertEqual(self.get(str(Path(self.temp.name) / 'x.docx')).status_code, 404)

    def test_outgoing_folder_unavailable_is_503_but_unset_stays_404(self):
        self.app.config['OUTGOING_DIR'] = str(Path(self.temp.name) / 'missing-share')
        response = self.client.get('/work-orders/outgoing-pdf?path=a.pdf')
        self.assertEqual(response.status_code, 503)
        self.assertIn(b'Outgoing folder unavailable', response.data)
        self.app.config['OUTGOING_DIR'] = ''
        self.assertEqual(self.client.get('/work-orders/outgoing-pdf?path=app.py').status_code, 404)


if __name__ == '__main__':
    unittest.main()
