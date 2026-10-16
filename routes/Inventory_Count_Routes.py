"""Item-only, read-only inventory lookup. All calculations stay in MRP."""
import math
import requests
from flask import Blueprint, current_app, request, render_template, jsonify, abort

inventory_count_bp = Blueprint('inventory_count', __name__)


def mrp_get(path, params):
    base = current_app.config['MRP_BASE_URL'].rstrip('/')
    response = requests.get(base + path, params=params, timeout=(3, 20))
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get('ok') is not True:
        raise ValueError('MRP lookup response unavailable')
    return payload


def inventory_data(item, reload=False):
    params = {'item': item}
    if reload:
        params['reload'] = '1'
    data = mrp_get('/api/inventory-lookup', params)
    if data.get('schema_version') != 1:
        raise ValueError('MRP inventory API v1 is required')
    for key in ('on_hand', 'on_hand_wip'):
        if key not in data or (data[key] is not None and
                (not isinstance(data[key], (int, float)) or isinstance(data[key], bool) or not math.isfinite(data[key]))):
            raise ValueError('Invalid MRP inventory metric')
    for prefix in ('so', 'receiving', 'inv_status'):
        if not isinstance(data.get(prefix + '_columns'), list) or not isinstance(data.get(prefix + '_rows'), list):
            raise ValueError('Invalid MRP inventory table')
        if any(not isinstance(column, str) for column in data[prefix + '_columns']) or any(not isinstance(row, dict) for row in data[prefix + '_rows']):
            raise ValueError('Invalid MRP inventory rows')
    return data


@inventory_count_bp.get('/inventory_count')
@inventory_count_bp.get('/inventory-count')
def index():
    item = request.args.get('item', '').strip()
    if len(item) > 200:
        abort(400)
    data, error, status = None, None, 200
    try:
        data = inventory_data(item, request.args.get('reload') == '1')
    except (requests.RequestException, ValueError, KeyError) as exc:
        current_app.logger.warning('MRP inventory lookup unavailable: %s', type(exc).__name__)
        error = 'MRP inventory data is unavailable. Check that the updated MRP website is running, then retry.'
        status = 503
    return render_template('inventory_count.html', item=item, data=data, error=error), status


@inventory_count_bp.get('/inventory_count/item-suggest')
def item_suggest():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify(ok=True, items=[])
    if len(query) > 200:
        abort(400)
    try:
        data = mrp_get('/api/item_suggest', {'q': query})
        if not isinstance(data.get('items'), list) or any(not isinstance(item, str) for item in data['items']):
            raise ValueError('Invalid MRP suggestions')
        return jsonify(ok=True, items=data['items'][:20])
    except (requests.RequestException, ValueError, KeyError) as exc:
        current_app.logger.warning('MRP inventory suggestions unavailable: %s', type(exc).__name__)
        return jsonify(ok=False, items=[]), 503
