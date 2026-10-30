import unittest
from unittest.mock import patch, Mock
import requests
from app import create_app


def payload():
    return dict(ok=True, schema_version=1, loaded_at='2026-10-08T15:00:00', item='RAM', canonical_item='RAM',
        on_hand=20, on_hand_wip=13,
        so_columns=['QB Num','Item','Qty(-)','Picked'], so_rows=[{'QB Num':'SO-20261234','Item':'RAM','Qty(-)':'10','Picked':'Partial'}],
        receiving_columns=['Date','Inv#','Qty'], receiving_rows=[{'Date':'2026-10-08','Inv#':'123','Qty':'2'}],
        inv_status_columns=['Part_Number','On Hand','On Hand - WIP'], inv_status_rows=[{'Part_Number':'RAM','On Hand':'20','On Hand - WIP':'13'}])


class InventoryLookupTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING':True, 'SECRET_KEY':'test', 'SQLALCHEMY_DATABASE_URI':'sqlite:///:memory:', 'MRP_BASE_URL':'http://mrp.test:5002'})
        self.client = self.app.test_client()

    def response(self, value=None):
        response = Mock()
        response.json.return_value = value or payload()
        return response

    def test_item_lookup_is_read_only_and_item_only(self):
        with patch('routes.Inventory_Count_Routes.requests.get', return_value=self.response()) as get:
            response = self.client.get('/inventory_count?item=RAM&so=SO-OTHER')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'13', response.data)
        self.assertIn(b'SO-20261234', response.data)
        self.assertIn(b'Receiving records', response.data)
        self.assertNotIn(b'name="so"', response.data)
        self.assertNotIn(b'physical_qty', response.data)
        self.assertNotIn(b'Save count', response.data)
        self.assertEqual(get.call_args.args[0], 'http://mrp.test:5002/api/inventory-lookup')
        self.assertEqual(get.call_args.kwargs['params'], {'item':'RAM'})
        self.assertEqual(self.client.post('/inventory_count', data={}).status_code, 405)

    def test_home_opens_all_inventory(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/inventory-count')
        with patch('routes.Inventory_Count_Routes.requests.get', return_value=self.response()) as get:
            response = self.client.get('/', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Inventory status', response.data)
        self.assertIn(b'item=RAM', response.data)
        self.assertEqual(get.call_args.kwargs['params'], {'item': ''})

    def test_initial_page_lists_items(self):
        with patch('routes.Inventory_Count_Routes.requests.get', return_value=self.response()):
            response = self.client.get('/inventory_count')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Inventory status', response.data)
        self.assertIn(b'item=RAM', response.data)

    def test_operational_quantity_columns_are_hidden(self):
        hidden = ['Awaiting Pick Qty', 'Physically Shipped Qty', 'Source Outstanding Qty']
        data = payload()
        data['so_columns'].extend(['Picked (WIP)', 'On Hand - WIP'])
        data['so_rows'][0].update({'Picked (WIP)': 'WIP_VISIBLE', 'On Hand - WIP': 'SO_STOCK_HIDDEN'})
        for prefix in ['so', 'inv_status']:
            data[prefix + '_columns'].extend(hidden)
            data[prefix + '_rows'][0].update({column: 'HIDDEN_VALUE' for column in hidden})
        with patch('routes.Inventory_Count_Routes.requests.get', return_value=self.response(data)):
            for url in ['/inventory_count', '/inventory_count?item=RAM']:
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                for column in hidden:
                    self.assertNotIn(column.encode(), response.data)
                self.assertNotIn(b'HIDDEN_VALUE', response.data)
                self.assertIn(b'RAM', response.data)
                if 'item=' in url:
                    self.assertIn(b'<th scope="col">Picked (WIP)</th>', response.data)
                    self.assertIn(b'WIP_VISIBLE', response.data)
                    self.assertNotIn(b'<th scope="col">On Hand - WIP</th>', response.data)
                    self.assertNotIn(b'SO_STOCK_HIDDEN', response.data)
                else:
                    self.assertIn(b'<th scope="col">On Hand - WIP</th>', response.data)

    def test_reload_preserves_item_and_requests_mrp_refresh(self):
        with patch('routes.Inventory_Count_Routes.requests.get', return_value=self.response()) as get:
            self.client.get('/inventory_count?item=RAM&reload=1')
        self.assertEqual(get.call_args.kwargs['params'], {'item':'RAM','reload':'1'})

    def test_upstream_failure_never_shows_zero_stock(self):
        with patch('routes.Inventory_Count_Routes.requests.get', side_effect=requests.ConnectionError('offline')):
            response = self.client.get('/inventory_count?item=RAM')
        self.assertEqual(response.status_code, 503)
        self.assertIn(b'MRP inventory data is unavailable', response.data)
        self.assertNotIn(b'metric-value', response.data)

    def test_null_quantities_are_not_recalculated(self):
        data = payload()
        data['on_hand_wip'] = None
        with patch('routes.Inventory_Count_Routes.requests.get', return_value=self.response(data)):
            response = self.client.get('/inventory_count?item=RAM')
        self.assertEqual(response.status_code, 200)
        self.assertIn('—'.encode(), response.data)
        self.assertIn(b'Missing values are not treated as zero', response.data)

    def test_item_suggestions_are_mrp_only(self):
        with patch('routes.Inventory_Count_Routes.requests.get', return_value=self.response({'ok':True,'items':['RAM','RAM-2']})) as get:
            response = self.client.get('/inventory_count/item-suggest?q=RA')
        self.assertEqual(response.json, {'ok':True,'items':['RAM','RAM-2']})
        self.assertEqual(get.call_args.args[0], 'http://mrp.test:5002/api/item_suggest')

    def test_html_is_escaped(self):
        data = payload()
        data['so_rows'][0]['Item'] = '<script>alert(1)</script>'
        with patch('routes.Inventory_Count_Routes.requests.get', return_value=self.response(data)):
            response = self.client.get('/inventory_count?item=RAM')
        self.assertIn(b'&lt;script&gt;', response.data)
        self.assertNotIn(b'<script>alert(1)</script>', response.data)

    def test_invalid_contract_is_rejected(self):
        data = payload()
        data['schema_version'] = 99
        with patch('routes.Inventory_Count_Routes.requests.get', return_value=self.response(data)):
            self.assertEqual(self.client.get('/inventory_count?item=RAM').status_code, 503)

    def test_inventory_search_and_reload_stay_outside_sidebar(self):
        with patch('routes.Inventory_Count_Routes.requests.get', return_value=self.response()):
            response = self.client.get('/inventory_count')
        sidebar = response.data.split(b'<aside class="app-sidebar"', 1)[1].split(b'</aside>', 1)[0]
        self.assertNotIn(b'Reload MRP data', sidebar)
        self.assertNotIn(b'name="item"', sidebar)
        self.assertIn(b'Reload MRP data', response.data)
        self.assertIn(b'name="item"', response.data)
        self.assertNotIn(b'Inventory count</span>', response.data)


if __name__ == '__main__':
    unittest.main()
