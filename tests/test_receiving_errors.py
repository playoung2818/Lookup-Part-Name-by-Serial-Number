"""Receiving AJAX failures must not hide behind HTML/JSON parsing errors."""
import unittest

from flask import Flask

from routes.Receiving_Routes import receiving_bp


class ReceivingErrorTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SECRET_KEY='test-only', TESTING=True)
        self.app.register_blueprint(receiving_bp)
        self.client = self.app.test_client()

    def test_expired_csrf_returns_json_without_database_access(self):
        response = self.client.post('/receiving/save', json={'workspace_id': 'a' * 64})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.is_json)
        self.assertIn('session verification failed', response.json['error'])
        self.assertIn('draft is retained', response.json['error'])

    def test_unhandled_ajax_error_returns_json(self):
        self.app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)
        # Force a failure before workspace/database access.
        from unittest.mock import patch
        with patch('routes.Receiving_Routes.require_csrf', side_effect=RuntimeError('private detail')):
            with self.assertLogs(self.app.logger, level='ERROR'):
                response = self.client.post('/receiving/save', json={})
        self.assertEqual(response.status_code, 500)
        self.assertTrue(response.is_json)
        self.assertIn('HTTP 500', response.json['error'])
        self.assertNotIn('private detail', response.json['error'])


if __name__ == '__main__':
    unittest.main()
