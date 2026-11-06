"""Isolated browser fixture. Uses a transactional fake DB; never creates tables.
Run with --instance TEMP_PATH --port 5019, then open /browser-check.
"""
import argparse
from io import BytesIO
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from app import create_app
from openpyxl import load_workbook
from functions.receiving_workspace import save_database, save_row, load_database
from test_receiving_workspace import FakeEngine, metadata, workbook


def fixture_workbook(*args, **kwargs):
    book = load_workbook(BytesIO(workbook(('EXPORT-1', '', '', '', '', ''))))
    sheet = book['Receiving Log']
    sheet['E6'] = 'Cbl-Bulk'
    sheet['G6'] = 3
    sheet['E7'] = 'Other-Unit'
    return book


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instance', required=True)
    parser.add_argument('--port', type=int, default=5019)
    args = parser.parse_args()
    app = create_app({'TESTING': True, 'SECRET_KEY': 'browser-fixture-only',
                      'SQLALCHEMY_DATABASE_URI': 'sqlite://', 'RECEIVING_REFERENCE_PATH': ''})
    app.instance_path = args.instance
    engine = FakeEngine()
    table = metadata()

    @app.get('/browser-check')
    def browser_check():
        return (ROOT / 'tests' / 'receiving_entry.browser.html').read_text(encoding='utf-8')

    @app.get('/fixture-db')
    def fixture_db():
        return {'rows': engine.rows, 'writes': engine.writes}

    def fixture_save(ignored_engine, state, persist):
        return save_database(engine, state, persist)

    with patch('functions.receiving_shipment.generate', side_effect=fixture_workbook), \
         patch('functions.receiving_workspace.lock_receiving'), \
         patch('functions.receiving_workspace.receiving_table', return_value=table), \
         patch('routes.Receiving_Routes.save_database', side_effect=fixture_save), \
         patch('routes.Receiving_Routes.save_row', side_effect=lambda ignored, *args: save_row(engine, *args)), \
         patch('routes.Receiving_Routes.load_database', side_effect=lambda ignored, state, persist: load_database(engine, state, persist)):
        app.run(host='0.0.0.0', port=args.port, debug=False, use_reloader=False)
