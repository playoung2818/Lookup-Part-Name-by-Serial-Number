import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from sqlalchemy.exc import SQLAlchemyError

from app import create_app
from flask import render_template


class SearchAndSidebarTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                               'MRP_BASE_URL': 'http://mrp.test:5002'})
        self.client = self.app.test_client()

    def search(self, query, records=(), history=(), items=(), stock=None, workflow=None, orders=(),
               serial_error=False, mrp_error=False):
        record = lambda serial: SimpleNamespace(id=1, serial_number=serial, part_number='NUVO-PART', entry_date=None,
                                                invoice_number='8000613', pod_number='POD-1', box_number='B1')
        patches = [
            patch('routes.Index_Routes.find_receiving_serial',
                  side_effect=SQLAlchemyError('down') if serial_error else None,
                  return_value=[record(s) for s in records]),
            patch('routes.Index_Routes.used_history', return_value=list(history)),
            patch('routes.Index_Routes.suggest_items', return_value=list(items)),
            patch('routes.Inventory_Count_Routes.inventory_data',
                  side_effect=ValueError('mrp down') if mrp_error else None, return_value=stock),
            patch('functions.so_status.find_so_status', return_value=workflow),
            patch('functions.wo_lookup.find_work_orders', return_value=list(orders)),
        ]
        mocks = [x.start() for x in patches]
        for x in patches:
            self.addCleanup(x.stop)
        response = self.client.get('/lookup', query_string={'q': query})
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True), dict(zip(
            ['serial', 'history', 'items', 'stock', 'workflow', 'orders'], mocks))

    @staticmethod
    def section(html, heading_id):
        return html.split(f'aria-labelledby="{heading_id}"', 1)[1].split('</section>', 1)[0]

    def test_one_page_shows_all_three_sections(self):
        html, mocks = self.search('nuvo-9006de-poe-ul', records=['NUVO-9006DE-POE-UL'],
                                  history=[{'order_id': 'SO-20260295', 'record_source': 'mes', 'outgoing_info': []}],
                                  items=['Nuvo-9006DE-PoE-UL', 'Nuvo-9006DE-PoE-UL-X'],
                                  stock={'on_hand': 9, 'on_hand_wip': 7, 'so_rows': [{}, {}]})
        self.assertIn('Results for <span class="results-query">nuvo-9006de-poe-ul</span>', html)
        for heading in ['>Serial number</h2>', '>SO number</h2>', '>Inventory item</h2>']:
            self.assertEqual(html.count(heading), 1)
        self.assertLess(html.index('>Serial number</h2>'), html.index('>SO number</h2>'))
        self.assertLess(html.index('>SO number</h2>'), html.index('>Inventory item</h2>'))
        serial = self.section(html, 'serial-heading')
        self.assertIn('NUVO-PART', serial)
        self.assertIn('SO-20260295', serial)
        self.assertIn('href="/?serial_number=nuvo-9006de-poe-ul">Full serial details', serial)
        self.assertIn('Not an SO number', self.section(html, 'so-heading'))
        item = self.section(html, 'item-heading')
        self.assertIn('>9</strong>', item)
        self.assertIn('>7</strong>', item)
        self.assertIn('Nuvo-9006DE-PoE-UL-X', item)  # other matching items
        self.assertIn('href="/inventory-count?item=Nuvo-9006DE-PoE-UL">Full stock details', item)
        mocks['stock'].assert_called_once_with('Nuvo-9006DE-PoE-UL')  # exact item, canonical case
        mocks['workflow'].assert_not_called()
        self.assertIn('value="nuvo-9006de-poe-ul"', html)  # query stays in the bar

    def test_so_number_section(self):
        workflow = {'owner': 'MRP', 'status_label': 'Released to MES', 'customer': 'Boston Scientific'}
        orders = [{'sales_order': 'SO-20260295', 'record_source': 'mes', 'release_number': 1, 'details': [{}]}]
        for query in ['SO-20260295', '20260295', 'WO26-20260295']:
            with self.subTest(query=query):
                html, mocks = self.search(query, workflow=workflow, orders=orders)
                so = self.section(html, 'so-heading')
                self.assertIn('Released to MES', so)
                self.assertIn('Boston Scientific', so)
                self.assertIn('href="/work-orders/?q=SO-20260295"', so)
                mocks['workflow'].assert_called_with('SO-20260295')
                mocks['items'].assert_not_called()  # SO numbers are not items
                mocks['serial'].assert_not_called()  # nor serial numbers
                mocks['history'].assert_not_called()
                self.assertIn('SO numbers are not serial numbers', self.section(html, 'serial-heading'))
                self.assertIn('SO numbers are not inventory items', self.section(html, 'item-heading'))

    def test_nothing_found_and_partial_failures(self):
        html, _ = self.search('zzzz-nothing')
        self.assertIn('Nothing found in any section', html)
        self.assertEqual(html.count('class="lookup-section is-empty"'), 3)
        html, _ = self.search('7443', items=['7443P', '7443P-1'])
        self.assertIn('href="/inventory-count?item=7443P-1"', self.section(html, 'item-heading'))
        self.assertNotIn('Nothing found', html)
        # One source failing does not hide the others.
        html, _ = self.search('7443P', serial_error=True, items=['7443P'], mrp_error=True)
        self.assertIn('Receiving records are unavailable', self.section(html, 'serial-heading'))
        item = self.section(html, 'item-heading')
        self.assertIn('Stock quantities are unavailable', item)
        self.assertIn('>7443P</a>', item)

    def test_empty_and_overlong_search(self):
        self.assertEqual(self.client.get('/lookup?q=').location, '/')
        self.assertEqual(self.client.get('/lookup?q=' + 'A' * 256).status_code, 400)
        html, _ = self.search('A' * 255)
        self.assertIn('Nothing found', html)
        html, mocks = self.search('NA')
        self.assertIn('Blank / NA placeholders', html)
        mocks['serial'].assert_not_called()

    def test_serial_results_and_no_results_with_item_suggestions(self):
        record = SimpleNamespace(id=1, serial_number='SN-1', part_number='TEST-PART', entry_date=None,
                                 invoice_number='INV-1', pod_number='POD-1', box_number='B1')
        with patch('routes.Index_Routes.find_receiving_serial', return_value=[record]) as lookup, \
             patch('routes.Index_Routes.find_by_serial', return_value=[]) as history, \
             patch('routes.Index_Routes.suggest_items') as suggest:
            for method in ['get', 'post']:
                response = (self.client.get('/?serial_number=SN-1') if method == 'get'
                            else self.client.post('/', data={'serial_number': 'SN-1'}))
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'TEST-PART', response.data)
                self.assertIn(b'Results for <span class="results-query">SN-1</span>', response.data)
                lookup.assert_called_with('SN-1')
            self.assertEqual(history.call_count, 2)
            suggest.assert_not_called()
        with patch('routes.Index_Routes.find_receiving_serial', return_value=[]), \
             patch('routes.Index_Routes.find_by_serial', return_value=[]), \
             patch('routes.Index_Routes.suggest_items', return_value=['7443P', '7443P-1']):
            response = self.client.get('/?serial_number=7443')
        self.assertIn(b'No results for <strong>7443</strong>', response.data)
        self.assertIn(b'href="/inventory-count?item=7443P-1"', response.data)
        self.assertNotIn(b'Receiving record', response.data)

    def test_home_and_old_serial_search_url(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'global-search-home', response.data)
        self.assertIn(b'aria-labelledby="floor-map-heading"', response.data)
        self.assertIn(b'src="/static/floor-map-3d.html?embed=1"', response.data)
        self.assertIn(b'Interactive 3D warehouse floor map', response.data)
        self.assertIn(b'/static/home.css', response.data)
        self.assertNotIn(b'class="brand-header"', response.data)
        self.assertEqual(self.client.get('/serial-search').location, '/')

    def test_one_search_box_on_every_page(self):
        for path in ['/', '/work-orders/', '/inventory-count', '/lookup']:
            with self.app.test_request_context(path):
                html = render_template('brand_header.html', query='<script>', item='<script>', serial_number='<script>')
                self.assertEqual(html.count('role="search"'), 1)
                self.assertEqual(html.count('action="/lookup"'), 1)
                self.assertIn('id="global-search-input" name="q"', html)
                self.assertIn('placeholder="Scan or type a serial, SO or item number"', html)
                self.assertIn('data-suggest-url="/inventory_count/item-suggest"', html)
                self.assertIn('global_search.js', html)
                self.assertNotIn('value="<script>"', html)
                self.assertLess(html.index('</aside>'), html.index('class="global-search"'))

    def test_no_search_bar_on_warehouse_action_pages(self):
        for path in ['/receiving', '/warehouse-borrow-log/', '/warehouse-borrow-log/new-multiple']:
            with self.subTest(path=path), self.app.test_request_context(path):
                html = render_template('brand_header.html', serial_number='X', query='Y')
                self.assertNotIn('role="search"', html)
                self.assertNotIn('global-search-input', html)
                if path == '/receiving':
                    # Receiving renders its own header with the action bar.
                    self.assertNotIn('class="brand-header"', html)
                    self.assertIn('class="rcv-header"', self.client.get(path).get_data(as_text=True))
                else:
                    self.assertIn('class="brand-header"', html)  # page title still shown
                self.assertIn('>WAREHOUSE ACTIONS</div>', html)

    def test_sidebar_has_only_warehouse_actions(self):
        for path, active in [('/receiving', 'Receiving'), ('/warehouse-borrow-log/', 'Warehouse Borrow Log'),
                             ('/inventory-count', None), ('/work-orders/', None)]:
            with self.subTest(path=path), self.app.test_request_context(path):
                html = render_template('brand_header.html')
                sidebar = html.split('<aside', 1)[1].split('</aside>', 1)[0]
                self.assertIn('>WAREHOUSE ACTIONS</div>', sidebar)
                self.assertNotIn('LOOKUP', sidebar)
                self.assertEqual(sidebar.count('<nav'), 1)
                self.assertIn('href="/receiving"', sidebar)
                self.assertIn('href="/warehouse-borrow-log/"', sidebar)
                self.assertNotIn('href="/inventory-count"', sidebar)
                self.assertIn('class="sidebar-brand" href="/"', sidebar)
                self.assertEqual(sidebar.count('aria-current="page"'), 1 if active else 0)
                if active:
                    self.assertIn(f'<span>{active}</span>', sidebar.split('aria-current="page"', 1)[1].split('</a>', 1)[0])

    def test_autofocus_on_search_pages_and_values_prefilled(self):
        cases = [('/', {'serial_number': 'Q0700370'}, True, 'Q0700370'),
                 ('/work-orders/', {'query': 'SO-20260295'}, True, 'SO-20260295'),
                 ('/inventory-count', {'item': 'DDR4'}, True, 'DDR4'),
]
        for path, context, autofocus, value in cases:
            with self.subTest(path=path), self.app.test_request_context(path):
                html = render_template('brand_header.html', **context)
                self.assertEqual('data-autofocus' in html, autofocus)
                self.assertIn(f'value="{value}"', html)


if __name__ == '__main__':
    unittest.main()
