"""Configured systems: parent QuickBooks item + child component rows.

Packing PDFs are mocked text, databases are the transactional fake; no DDL.
"""
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from openpyxl import Workbook, load_workbook
from sqlalchemy import Column, Integer, String

from functions.receiving_import import import_data, read_upload
from functions.receiving_shipment import (
    description_text, generate, parse_bom, parse_packing, read_serials,
)
from functions.receiving_workspace import (
    WorkspaceStore, load_database, public_state, save_database, search_invoice,
)
from test_receiving_workspace import FakeEngine, metadata

# Mirrors the real 8003757 layout: "INV NO:" without a period, totals on the
# TOTAL line, a whole-number net weight and a configured SEMIL system.
PACKING = '''Packing List
Neousys Technology Inc. INV NO: 8003757
CARTON No MODEL NAME / Description QTY Net Weight Gross Weight Dimension (CM)
1 Cblkit-FP-NRU 2 13 14.45 40 X 36 X 40
NRU front panel cable kit, including: 1x Cbl-TpCPlug-UTpCF-50CM, 5x Cbl-
M12X8M-RJ45F-100CM
Customer PO No.: POD-1
2-3 SEMIL-1708-i7OCG9-FF08-64 2 12.34 15.80 42 X 35 X 24
SEMIL-1708-FF, including i7-9700E, 2x DDR5-32GB-56WT-SM, 4x Cbl-MHF4-
SMAF-WP-15CM
Customer PO No.: POD-261225
TOTAL 3 CTNS 4 25.34 30.25 KG'''


def qb(part, qty):
    return {'part': part, 'qty': qty, 'kind': 'Physical item', 'line': 0, 'page': 1, 'item': part,
            'cost': Decimal(1), 'amount': Decimal(qty), 'customer': ''}


def pdf_mock(text):
    pdf = MagicMock()
    pdf.pages = [MagicMock()]
    pdf.pages[0].extract_text.return_value = text
    context = MagicMock()
    context.__enter__.return_value = pdf
    return context


def hierarchy_table():
    table = metadata()
    for column in (Column('item_role', String), Column('ordering_model', String), Column('parent_id', Integer)):
        table.append_column(column)
    return table


class ParsingTests(unittest.TestCase):
    def test_real_layout_invoice_totals_and_integer_net_weight(self):
        with patch('functions.receiving_shipment.pdfplumber.open', return_value=pdf_mock(PACKING)):
            items, invoice, cartons, printed = parse_packing('packing.pdf')
        self.assertEqual((invoice, cartons, printed), ('8003757', 3, 4))
        self.assertEqual([(item['part'], item['qty'], item['box']) for item in items],
                         [('Cblkit-FP-NRU', 2, '3--1'), ('SEMIL-1708-i7OCG9-FF08-64', 2, '3--2-3')])

    def test_bom_parsing_repairs_wrapped_names_and_multipliers(self):
        lines = ['NRU-240S-AWP, including GC-AGXOrin64G-JetPack 6.2_NRU-230/240S,',
                 'M.280-SSD-1TB-PCIe44-TLC5WT-TD2, 4x Cbl-', 'MHF4- SMAF-WP-15CM, 4x DtC-SMA-WP']
        self.assertEqual(description_text(['A, 4x Cbl-', 'MHF4- SMAF']), 'A, 4x Cbl-MHF4-SMAF')
        self.assertEqual(parse_bom(lines), ('NRU-240S-AWP', [
            ('GC-Jetson-AGX64GB-Orin-Nvidia', 1), ('M.280-SSD-1TB-PCIe44-TLC5WT-TD2', 1),
            ('Cbl-MHF4-SMAF-WP-15CM', 4), ('DtC-SMA-WP', 4)]))
        # Descriptive sentences are not configured systems.
        self.assertIsNone(parse_bom(['NRU front panel cable kit, including: 1x Cbl-A']))
        self.assertIsNone(parse_bom(['Rugged Edge AI Computer with 4x PoE++']))

    def test_export_serial_with_embedded_model_prefix(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'export.xlsx'
            book = Workbook()
            book.active.append(['Customer PO No', 'Ordering Model', 'S/N', 'Invoice No'])
            book.active.append(['POD-1', 'M', 'SEMIL-1708-I7OCG9-FF08-64 S/N Q4600813', '8003757'])
            book.active.append(['POD-1', 'M', 'Q1', '8003757'])
            book.save(path)
            pool, _, _ = read_serials(path, '8003757')
        self.assertEqual(list(pool[('POD-1', 'M')]), ['Q4600813', 'Q1'])


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.export = self.directory / 'export.xlsx'
        book = Workbook()
        book.active.append(['Customer PO No', 'Ordering Model', 'S/N', 'Invoice No'])
        for serial in ('Q4600799', 'Q4600800'):
            book.active.append(['POD-261225', 'SEMIL-1708-i7OCG9-FF08-64', serial, '8003757'])
        book.save(self.export)
        self.lines = [qb('SEMIL-1708-FF', 2), qb('i7-9700E', 2), qb('DDR5-32GB-56WT-SM', 4),
                      qb('Cbl-MHF4-SMAF-WP-15CM', 8), qb('Cblkit-FP-NRU', 2)]

    def tearDown(self):
        self.temp.cleanup()

    def build(self, lines):
        receipt = {'date': date(2026, 11, 19), 'reference': '8003757', 'lines': lines}
        with patch('functions.receiving_shipment.parse_receipt', return_value=receipt), \
             patch('functions.receiving_shipment.pdfplumber.open', return_value=pdf_mock(PACKING)):
            return generate(self.directory / 'r.pdf', self.directory / 'p.pdf', self.export)

    def test_configured_system_becomes_parent_and_children_per_unit(self):
        book = self.build(self.lines)
        rows = list(book['Receiving Log'].iter_rows(min_row=2, values_only=True))
        layout = [(r[4], r[5], r[6], r[8], r[9], r[10]) for r in rows]
        unit = lambda parent_row, serial: [
            ('SEMIL-1708-FF', serial, 1, 'parent', 'SEMIL-1708-i7OCG9-FF08-64', None),
            ('i7-9700E', '', 1, 'child', None, parent_row),
            ('DDR5-32GB-56WT-SM', '', 1, 'child', None, parent_row),
            ('DDR5-32GB-56WT-SM', '', 1, 'child', None, parent_row),
            ('Cbl-MHF4-SMAF-WP-15CM', '', 4, 'child', None, parent_row)]  # bulk prefix keeps qty
        self.assertEqual(layout, [('Cblkit-FP-NRU', '', 2, None, None, None)] + unit(3, 'Q4600799') + unit(8, 'Q4600800'))
        self.assertTrue(all(r[2] == '3--2-3' and r[3] == 'POD-261225' for r in rows[1:]))
        recon = list(book['QB Reconciliation'].iter_rows(min_row=2, values_only=True))
        self.assertTrue(recon and all(r[3] == 'OK' for r in recon), recon)
        self.assertEqual([r[0] for r in book['Exceptions'].iter_rows(min_row=2, values_only=True)], [])
        content = BytesIO()
        book.save(content)
        records, errors, skipped = read_upload(content.getvalue())
        self.assertEqual((len(records), errors, skipped), (11, [], 0))
        self.assertEqual((records[2]['item_role'], records[2]['parent_row']), ('child', 3))

    def test_base_not_on_quickbooks_is_not_split_and_mismatch_reported(self):
        book = self.build([qb('i7-9700E', 2)])
        rows = list(book['Receiving Log'].iter_rows(min_row=2, values_only=True))
        self.assertEqual([r[4] for r in rows], ['Cblkit-FP-NRU'] + ['SEMIL-1708-i7OCG9-FF08-64'] * 2)
        self.assertTrue(all(r[8] is None for r in rows))
        kinds = {r[2]: r[3] for r in book['Exceptions'].iter_rows(min_row=2, values_only=True)}
        self.assertIn('QuickBooks 2', kinds['i7-9700E'])

    def test_parent_row_must_reference_an_earlier_parent(self):
        book = Workbook()
        book.active.append(['Date', 'Inv#', 'Box #', 'POD#', 'Part#', 'SN#', 'QTY', 'Role', 'Parent Row'])
        book.active.append([date(2026, 1, 1), 'I', 'B', 'P', 'CPU', '', 1, 'child', 3])
        book.active.append([date(2026, 1, 1), 'I', 'B', 'P', 'BASE', '', 1, 'parent', None])
        content = BytesIO()
        book.save(content)
        _, errors, _ = read_upload(content.getvalue())
        self.assertTrue(any('earlier parent row' in error for error in errors))


class StorageTests(GenerationTests):
    def setUp(self):
        super().setUp()
        self.store = WorkspaceStore(self.directory / 'ws', 'd' * 64)
        content = BytesIO()
        self.build(self.lines).save(content)
        with self.store.locked():
            self.state = self.store.create(content.getvalue())
        self.engine = FakeEngine()
        self.table = hierarchy_table()

    def patched(self, call, *args):
        with patch('functions.receiving_workspace.lock_receiving'), \
             patch('functions.receiving_workspace.receiving_table', return_value=self.table):
            return call(*args)

    def test_commit_links_children_to_parent_database_ids(self):
        state = self.state
        state['template_commit'] = True
        with self.store.locked():
            self.patched(save_database, self.engine, state, self.store.persist)
        db = {row['id']: row for row in self.engine.rows}
        parents = [row for row in self.engine.rows if row['item_role'] == 'parent']
        self.assertEqual([p['serial_number'] for p in parents], ['Q4600799', 'Q4600800'])
        self.assertEqual({p['ordering_model'] for p in parents}, {'SEMIL-1708-i7OCG9-FF08-64'})
        children = [row for row in self.engine.rows if row['item_role'] == 'child']
        self.assertEqual(len(children), 8)
        for child in children:
            parent = db[child['parent_id']]
            self.assertEqual(parent['item_role'], 'parent')
            self.assertLess(parent['id'], child['id'])
        standalone = self.engine.rows[0]
        self.assertEqual((standalone['item_role'], standalone.get('parent_id')), (None, None))
        public = public_state(state)['rows']
        self.assertEqual((public[2]['item_role'], public[2]['parent_number']), ('child', 2))

        # Reload by INV#: roles and links come back from the database.
        with self.store.locked():
            reloaded = self.patched(search_invoice, self.engine, self.store, '8003757', state['id'], state['revision'])
            self.patched(load_database, self.engine, reloaded, self.store.persist)
        public = public_state(reloaded)['rows']
        self.assertEqual([(r['part_number'], r['item_role'], r['parent_number']) for r in public[1:4]],
                         [('SEMIL-1708-FF', 'parent', None), ('i7-9700E', 'child', 2), ('DDR5-32GB-56WT-SM', 'child', 2)])
        self.assertEqual(public[2]['parent_id'], public[1]['db_id'])
        export = load_workbook(BytesIO(self.store.export(reloaded)), read_only=True)['Receiving Log']
        values = list(export.iter_rows(values_only=True))
        self.assertEqual(values[0][8:11], ('Role', 'Ordering Model', 'Parent Row'))
        self.assertEqual(values[3][8:11], ('child', None, 3))

    def test_database_without_columns_refuses_parent_child_rows(self):
        with self.assertRaisesRegex(ValueError, 'parent/child columns'):
            import_data(dict(self.state['rows'][1]), metadata())
        # Ordinary rows still save to an un-migrated table.
        self.assertNotIn('item_role', import_data(dict(self.state['rows'][0]), metadata()))


if __name__ == '__main__':
    unittest.main()
