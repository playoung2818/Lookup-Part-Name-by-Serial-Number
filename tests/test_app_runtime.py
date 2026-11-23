"""Single-copy guard and /health share check (no real shares or ports used)."""
import socket
import unittest
from unittest.mock import patch

import app as app_module
from app import already_running, create_app, serve


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'x', 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                               'REQUIRED_SHARES': [r'\\server\share']})
        self.client = self.app.test_client()

    def test_health_reports_share_access_of_this_process(self):
        with patch.object(app_module, 'share_reachable', return_value=True):
            body = self.client.get('/health').json
        self.assertEqual((body['ok'], body['shares']), (True, {r'\\server\share': True}))
        with patch.object(app_module, 'share_reachable', return_value=False):
            response = self.client.get('/health')
        self.assertFalse(response.json['ok'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_second_copy_refuses_to_start(self):
        with patch.object(app_module, 'already_running', return_value=True), \
             patch.object(self.app, 'run') as run, self.assertRaises(SystemExit):
            serve(self.app)
        run.assert_not_called()

    def test_first_copy_starts_and_warns_without_share(self):
        with patch.object(app_module, 'already_running', return_value=False), \
             patch.object(app_module, 'share_reachable', return_value=False), \
             patch.object(self.app, 'run') as run, self.assertLogs(level='WARNING') as logs:
            serve(self.app)
        run.assert_called_once()
        self.assertIn(r'\\server\share', ''.join(logs.output))

    def test_already_running_detects_a_listener(self):
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0))  # throwaway local port for the test only
            server.listen()
            port = server.getsockname()[1]
            self.assertTrue(already_running('127.0.0.1', port))
        self.assertFalse(already_running('127.0.0.1', port))


if __name__ == '__main__':
    unittest.main()
