"""Workspace and DB-save tests. SQL metadata + a transactional fake, never DDL."""
from copy import deepcopy
from datetime import date
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from openpyxl import Workbook, load_workbook
from sqlalchemy import Column, Date, Float, Integer, MetaData, String, Table
from sqlalchemy.exc import SQLAlchemyError

from functions.receiving_workspace import (
    WorkspaceConflict, WorkspaceStore, public_state, save_database, update_serials,
    load_database, save_row,
)


def workbook(serials=('', '', ''), quantities=None):
    book = Workbook()
    book.active.title = 'Receiving Log'
    book.active.append(['Date', 'Inv#', 'Box #', 'POD#', 'Part#', 'SN#', 'Qty', 'Reference'])
    for index, serial in enumerate(serials):
        quantity = quantities[index] if quantities else 1
        book.active.append([date(2026, 11, 4), '80003610', '34--30', 'POD-1', 'CPU-1', serial, quantity, 'Customer_SO-1'])
    book.create_sheet('Read Me').append(['Field', 'Value'])
    book.create_sheet('Exceptions').append(['Type', 'Line', 'Part', 'Details'])
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def metadata():
    return Table('receiving_log', MetaData(), Column('id', Integer, primary_key=True),
                 Column('entry_date', Date), Column('invoice_number', String), Column('box_number', String),
                 Column('pod_number', String), Column('part_number', String), Column('serial_number', String),
                 Column('quantity', Float), Column('Reference', String), Column('other_note', String))


class Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def one(self):
        if len(self.rows) != 1:
            raise AssertionError('Expected one row')
        return deepcopy(self.rows[0])

    def __iter__(self):
        return iter(deepcopy(self.rows))


class FakeEngine:
    def __init__(self):
        self.rows = []
        self.next_id = 1
        self.writes = 0
        self.fail_commit = None

    def connect(self):
        return FakeConnection(self)


class FakeConnection:
    def __init__(self, engine):
        self.engine = engine
        self.rows = deepcopy(engine.rows)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement):
        if statement.is_select:
            params = statement.compile().params
            rows = self.rows
            if 'invoice_number_1' in params:
                rows = [row for row in rows if row['invoice_number'] == params['invoice_number_1']]
            return Result(sorted(rows, key=lambda row: row['id']))
        params = statement.compile().params
        self.engine.writes += 1
        if statement.is_insert:
            row = dict(params, id=self.engine.next_id)
            row.setdefault('Reference', None)
            row['other_note'] = 'keep me'
            self.engine.next_id += 1
            self.rows.append(row)
            return Result([row])
        if statement.is_update:
            row_id = params.pop('id_1')
            row = next(row for row in self.rows if row['id'] == row_id)
            if 'invoice_number_1' in params:
                assert row['invoice_number'] == params.pop('invoice_number_1')
            row.update(params)
            return Result([row])
        raise AssertionError('Unexpected statement; database deletes and schema changes are forbidden')

    def commit(self):
        failure = self.engine.fail_commit
        self.engine.fail_commit = None
        if failure == 'before':
            raise SQLAlchemyError('Commit failed before writing')
        self.engine.rows = deepcopy(self.rows)
        if failure == 'after':
            raise SQLAlchemyError('Commit response lost')

    def rollback(self):
        self.rows = deepcopy(self.engine.rows)


class ReceivingWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = WorkspaceStore(self.root, 'a' * 64)
        with self.store.locked():
            self.state = self.store.create(workbook())
        self.engine = FakeEngine()
        self.table = metadata()

    def tearDown(self):
        self.temp.cleanup()

    def save(self, persist=None):
        with patch('functions.receiving_workspace.lock_receiving'), \
             patch('functions.receiving_workspace.receiving_table', return_value=self.table):
            with self.store.locked():
                result = save_database(self.engine, self.state, persist or self.store.persist)
        return result

    def save_cell(self, index, value, version=None):
        row = self.state['rows'][index]
        with patch('functions.receiving_workspace.lock_receiving'), \
             patch('functions.receiving_workspace.receiving_table', return_value=self.table):
            return save_row(self.engine, self.state, row['row_id'], value,
                            version or row['db_snapshot'], self.store.persist)

    def reload_database(self):
        with patch('functions.receiving_workspace.lock_receiving'), \
             patch('functions.receiving_workspace.receiving_table', return_value=self.table):
            load_database(self.engine, self.state, self.store.persist)

    def test_database_load_overrides_file_cached_values_and_exports_all_fields(self):
        self.save()
        self.state['rows'][0]['serial_number'] = 'FILE-ONLY-VALUE'
        self.engine.rows[0]['serial_number'] = 'DATABASE-VALUE'
        self.engine.rows[0]['Reference'] = 'DATABASE-REFERENCE'
        self.engine.rows[0]['quantity'] = 7
        self.reload_database()
        self.assertEqual(self.state['rows'][0]['serial_number'], 'DATABASE-VALUE')
        book = load_workbook(BytesIO(self.store.export(self.state)), read_only=True)
        self.assertEqual(book['Receiving Log']['F2'].value, 'DATABASE-VALUE')
        self.assertEqual(book['Receiving Log']['G2'].value, 7)
        self.assertEqual(book['Receiving Log']['H2'].value, 'DATABASE-REFERENCE')
        book.close()

    def test_individual_row_save_only_updates_one_sn_and_retains_ids(self):
        self.save()
        ids = [row['id'] for row in self.engine.rows]
        old_version = self.state['rows'][0]['db_snapshot']
        self.save_cell(0, 'ONE-ROW')
        self.assertEqual([row['id'] for row in self.engine.rows], ids)
        self.assertEqual([row['serial_number'] for row in self.engine.rows], ['ONE-ROW', '', ''])
        self.assertTrue(all(row['other_note'] == 'keep me' for row in self.engine.rows))
        self.save_cell(1, 'SECOND-ROW')
        with self.assertRaises(WorkspaceConflict):
            self.save_cell(0, 'STALE', old_version)
        self.assertEqual(self.engine.rows[0]['serial_number'], 'ONE-ROW')

    def test_single_row_retry_after_lost_commit_does_not_update_twice(self):
        self.save()
        version = self.state['rows'][0]['db_snapshot']
        self.engine.fail_commit = 'after'
        with self.assertRaises(SQLAlchemyError):
            self.save_cell(0, 'COMMITTED-BUT-RESPONSE-LOST', version)
        writes = self.engine.writes
        self.save_cell(0, 'COMMITTED-BUT-RESPONSE-LOST', version)
        self.assertEqual(self.engine.writes, writes)
        self.assertEqual(self.engine.rows[0]['serial_number'], 'COMMITTED-BUT-RESPONSE-LOST')
        self.assertEqual(len(self.engine.rows), 3)

    def test_deleted_row_is_not_rendered_or_reinserted_by_individual_edit(self):
        self.save()
        del self.engine.rows[0]
        with self.assertRaisesRegex(WorkspaceConflict, 'deleted'):
            self.save_cell(0, 'DO-NOT-REINSERT')
        self.reload_database()
        public = public_state(self.state)
        self.assertEqual(len(public['rows']), 2)
        self.assertEqual(public['missing_ids'], [1])
        self.assertEqual(len(self.engine.rows), 2)

    def test_single_row_duplicate_rejected_and_blank_bulk_allowed(self):
        self.save()
        self.save_cell(0, 'UNIQUE-SN')
        with self.assertRaisesRegex(WorkspaceConflict, 'already exists'):
            self.save_cell(1, 'unique-sn')
        self.save_cell(0, '')
        self.assertEqual(self.engine.rows[0]['serial_number'], '')

    def edit(self, index, value):
        update_serials(self.state, [{'row_id': self.state['rows'][index]['row_id'], 'serial_number': value}])
        self.store.persist(self.state)

    def test_blank_units_saved_once_then_serial_edits_update_same_ids(self):
        counts = self.save()
        self.assertEqual(counts['inserted'], 3)
        ids = [r['db_id'] for r in self.state['rows']]
        self.assertEqual(len(set(ids)), 3)
        self.assertTrue(all(r['serial_number'] == '' for r in self.engine.rows))
        self.assertTrue(all(r['Reference'] == 'Customer_SO-1' for r in self.engine.rows))
        counts = self.save()
        self.assertEqual((counts['inserted'], counts['updated'], counts['unchanged']), (0, 0, 3))
        self.edit(1, 'SCAN-2')
        counts = self.save()
        self.assertEqual((counts['inserted'], counts['updated']), (0, 1))
        self.assertEqual(len(self.engine.rows), 3)
        self.assertEqual([r['db_id'] for r in self.state['rows']], ids)
        self.assertEqual(self.engine.rows[1]['serial_number'], 'SCAN-2')
        self.assertTrue(all(r['other_note'] == 'keep me' for r in self.engine.rows))
        self.edit(1, '')
        self.save()
        self.assertEqual(self.engine.rows[1]['serial_number'], '')
        self.assertEqual(len(self.engine.rows), 3)

    def test_bulk_serial_can_be_entered_updated_and_exported_without_changing_qty(self):
        with self.store.locked():
            self.state = self.store.create(workbook(quantities=(5, 1, 1)), self.state['id'], self.state['revision'])
        self.edit(0, 'BULK-SN-1')
        counts = self.save()
        self.assertEqual(counts['inserted'], 3)
        row_id = self.state['rows'][0]['db_id']
        self.assertEqual(self.engine.rows[0]['serial_number'], 'BULK-SN-1')
        self.assertEqual(self.engine.rows[0]['quantity'], 5)
        self.edit(0, 'BULK-SN-UPDATED')
        counts = self.save()
        self.assertEqual((counts['inserted'], counts['updated']), (0, 1))
        self.assertEqual(self.state['rows'][0]['db_id'], row_id)
        self.assertEqual(self.engine.rows[0]['quantity'], 5)
        book = load_workbook(BytesIO(self.store.export(self.state)), read_only=True)
        self.assertEqual(book['Receiving Log']['F2'].value, 'BULK-SN-UPDATED')
        self.assertEqual(book['Receiving Log']['G2'].value, 5)
        book.close()

    def test_duplicate_sn_blocks_every_write_but_draft_is_retained(self):
        self.edit(0, 'same')
        self.edit(1, ' SAME ')
        with self.assertRaisesRegex(WorkspaceConflict, 'Duplicate SN'):
            self.save()
        self.assertEqual(self.engine.rows, [])
        self.assertEqual(self.engine.writes, 0)
        self.assertEqual(self.store.active()['rows'][0]['serial_number'], 'same')

    def test_existing_receipts_are_linked_without_reinserting(self):
        self.save()
        with self.store.locked():
            self.state = self.store.create(workbook(), self.state['id'], self.state['revision'])
        counts = self.save()
        self.assertEqual((counts['inserted'], counts['linked']), (0, 3))
        self.assertEqual(len(self.engine.rows), 3)

    def test_regeneration_cannot_reinsert_units_with_previously_entered_serials(self):
        self.edit(0, 'ENTERED-IN-OLD-WORKSPACE')
        self.save()
        with self.store.locked():
            self.state = self.store.create(workbook(), self.state['id'], self.state['revision'])
        writes = self.engine.writes
        with self.assertRaisesRegex(WorkspaceConflict, 'different serials'):
            self.save()
        self.assertEqual(len(self.engine.rows), 3)
        self.assertEqual(self.engine.writes, writes)

    def test_existing_blank_receipt_can_be_linked_and_given_sn(self):
        self.save()
        with self.store.locked():
            self.state = self.store.create(workbook(), self.state['id'], self.state['revision'])
        self.edit(0, 'ASSIGNED-AFTER-GENERATION')
        counts = self.save()
        self.assertEqual((counts['inserted'], counts['updated'], counts['linked']), (0, 1, 2))
        self.assertEqual(len(self.engine.rows), 3)

    def test_external_change_or_unrelated_serial_blocks_saving(self):
        self.save()
        self.engine.rows[0]['other_note'] = 'external change'
        writes = self.engine.writes
        self.edit(1, 'NEW-SN')
        with self.assertRaisesRegex(WorkspaceConflict, 'changed outside'):
            self.save()
        self.assertEqual(self.engine.writes, writes)

    def test_serial_in_another_receipt_is_not_overwritten(self):
        self.save()
        unrelated = deepcopy(self.engine.rows[0])
        unrelated.update(id=99, serial_number='TAKEN', invoice_number='OTHER-INVOICE')
        self.engine.rows.append(unrelated)
        self.edit(0, 'TAKEN')
        writes = self.engine.writes
        with self.assertRaisesRegex(WorkspaceConflict, 'another database receipt'):
            self.save()
        self.assertEqual(self.engine.writes, writes)

    def test_lost_commit_response_recovers_without_duplicates(self):
        self.engine.fail_commit = 'after'
        with self.assertRaises(SQLAlchemyError):
            self.save()
        self.assertEqual(len(self.engine.rows), 3)
        self.state = self.store.active()
        self.assertTrue(self.state['pending'])
        self.assertTrue(self.save()['recovered'])
        self.assertEqual(len(self.engine.rows), 3)
        self.assertTrue(all(r['db_id'] for r in self.state['rows']))
        self.assertIsNone(self.state['pending'])

    def test_failed_commit_recovers_and_retries_insert_safely(self):
        self.engine.fail_commit = 'before'
        with self.assertRaises(SQLAlchemyError):
            self.save()
        self.assertEqual(self.engine.rows, [])
        self.state = self.store.active()
        self.assertTrue(self.state['pending'])
        counts = self.save()
        self.assertEqual(counts['inserted'], 3)
        self.assertEqual(len(self.engine.rows), 3)

    def test_failure_after_commit_before_file_finalize_is_recoverable(self):
        count = 0
        def persist(state):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('Disk temporarily unavailable')
            self.store.persist(state)
        with self.assertRaises(OSError):
            self.save(persist)
        self.assertEqual(len(self.engine.rows), 3)
        self.state = self.store.active()
        self.assertTrue(self.state['pending'])
        self.assertTrue(self.save()['recovered'])
        self.assertEqual(len(self.engine.rows), 3)

    def test_pending_journal_prevents_edits_or_replacement(self):
        self.engine.fail_commit = 'after'
        with self.assertRaises(SQLAlchemyError):
            self.save()
        self.state = self.store.active()
        with self.assertRaisesRegex(WorkspaceConflict, 'recovery'):
            self.edit(0, 'DO-NOT-LOSE')
        with self.assertRaisesRegex(WorkspaceConflict, 'pending'):
            self.store.create(workbook(), self.state['id'], self.state['revision'])

    def test_draft_survives_store_recreation_and_exports_current_values(self):
        self.edit(0, 'SCAN-RELOAD')
        reopened = WorkspaceStore(self.root, 'a' * 64)
        current = reopened.active()
        self.assertEqual(current['rows'][0]['serial_number'], 'SCAN-RELOAD')
        content = reopened.export(current)
        book = load_workbook(BytesIO(content), read_only=True)
        self.assertEqual(book['Receiving Log']['F2'].value, 'SCAN-RELOAD')
        self.assertIsNone(book['Receiving Log']['F3'].value)
        self.assertIn('Entry Status', book.sheetnames)
        book.close()
        public = public_state(current)
        self.assertNotIn('db_snapshot', public['rows'][0])
        self.assertNotIn('original', public['rows'][0])

    def test_wrong_owner_stale_revision_and_invalid_serials(self):
        self.assertIsNone(WorkspaceStore(self.root, 'b' * 64).active())
        with self.assertRaises(WorkspaceConflict):
            self.store.require(self.state['id'], 999)
        for value in ('=BAD()', 'NAN', 'a\nb', 'x' * 256):
            with self.subTest(value=value[:20]), self.assertRaises(ValueError):
                self.edit(0, value)
        self.assertEqual(self.state['rows'][0]['serial_number'], '')


if __name__ == '__main__':
    unittest.main()
