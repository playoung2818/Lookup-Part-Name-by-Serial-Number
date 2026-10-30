import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from app import create_app
from flask import render_template


class SidebarLookupTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
        self.client = self.app.test_client()

    def test_search_routes_only_to_serial_or_so(self):
        for query, path, parameter, expected in [
            ('SN&123', '/', 'serial_number', 'SN&123'),
            ('SO-20261526', '/work-orders/', 'q', 'SO-20261526'),
            ('20261526', '/work-orders/', 'q', 'SO-20261526'),
            ('DDR4-16GB', '/', 'serial_number', 'DDR4-16GB'),
        ]:
            with self.subTest(query=query):
                response = self.client.get('/lookup', query_string={'q': query})
                self.assertEqual(response.status_code, 302)
                destination = urlparse(response.location)
                self.assertEqual(destination.path, path)
                self.assertEqual(parse_qs(destination.query), {parameter: [expected]})

    def test_empty_and_overlong_search(self):
        self.assertEqual(self.client.get('/lookup?q=').location, '/')
        self.assertEqual(self.client.get('/lookup?q=' + 'A' * 256).status_code, 400)
        self.assertEqual(self.client.get('/lookup?q=' + 'A' * 255).status_code, 302)

    def test_serial_lookup_supports_sidebar_get_and_existing_post(self):
        record = SimpleNamespace(part_number='TEST-PART', entry_date=None,
                                 invoice_number='INV-1', pod_number='POD-1')
        with patch('routes.Index_Routes.ReceivingLog') as model, \
             patch('routes.Index_Routes.find_by_serial', return_value=[]) as history:
            model.query.filter_by.return_value.first.return_value = record
            for method in ['get', 'post']:
                response = (self.client.get('/?serial_number=SN-1') if method == 'get'
                            else self.client.post('/', data={'serial_number': 'SN-1'}))
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'TEST-PART', response.data)
                model.query.filter_by.assert_called_with(serial_number='SN-1')
            self.assertEqual(history.call_count, 2)

    def test_sidebar_has_one_search_without_module_selector(self):
        for path in ['/', '/work-orders/', '/inventory-count', '/receiving/']:
            with self.app.test_request_context(path):
                html = render_template('brand_header.html', query='<script>', item='<script>', serial_number='<script>')
                self.assertNotIn('sidebar-lookup-module', html)
                self.assertNotIn('name="module"', html)
                self.assertIn('placeholder="Serial / SO number"', html)
                self.assertIn('action="/lookup"', html)
                self.assertNotIn('value="<script>"', html)
                self.assertLess(html.index('>SN# &amp; SO LOOKUP</div>'), html.index('class="sidebar-search"'))
                self.assertLess(html.index('class="sidebar-search"'), html.index('>WAREHOUSE ACTIONS</div>'))
                self.assertNotIn('sidebar-reload', html)
                self.assertNotIn('aria-labelledby="lookup-nav-label"', html)
                self.assertNotIn('Browse all inventory', html)
                self.assertNotIn('Reload MRP data', html)

    def test_inventory_term_is_not_copied_into_sidebar_search(self):
        with self.app.test_request_context('/inventory-count?item=DDR4'):
            html = render_template('brand_header.html', item='DDR4')
            self.assertNotIn('value="DDR4"', html)


if __name__ == '__main__':
    unittest.main()
