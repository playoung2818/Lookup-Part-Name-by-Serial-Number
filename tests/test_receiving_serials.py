"""Atomic group-scoped serial entry. Transactional fake only, no production DB/DDL."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from openpyxl import load_workbook
from sqlalchemy.exc import SQLAlchemyError

from functions.receiving_workspace import (
    WorkspaceConflict, WorkspaceStore, fill_serials, load_database, save_database,
)
from test_receiving_workspace import FakeEngine, FakeConnection, metadata, workbook


class SerialFillTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = WorkspaceStore(Path(self.temp.name), 'a' * 64)
        book = load_workbook(BytesIO(workbook(('IMPORTED', '', '', '', '', ''), (1, 1, 1, 1, 3, 1))))
        book['Receiving Log']['E7'] = 'OTHER-PART'
        content = BytesIO()
        book.save(content)
        book.close()
        self.state = self.store.create(content.getvalue())
        self.engine = FakeEngine()
        for target, options in (
            ('functions.receiving_workspace.lock_receiving', {}),
            ('functions.receiving_workspace.receiving_table', {'return_value': metadata()}),
        ):
            patcher = patch(target, **options)
            patcher.start()
            self.addCleanup(patcher.stop)
        save_database(self.engine, self.state, self.store.persist)
        self.group = {field: self.state['rows'][0][field] for field in ('box_number', 'pod_number', 'part_number')}

    def changes(self, values=('ABC000127', 'ABC000128'), indexes=(1, 2)):
        return [dict(row_id=self.state['rows'][index]['row_id'],
                     row_version=self.state['rows'][index]['db_snapshot'], serial_number=value)
                for index, value in zip(indexes, values)]

    def fill(self, changes=None, group=None, persist=None):
        return fill_serials(self.engine, self.state, self.group if group is None else group,
                            self.changes() if changes is None else changes, persist or self.store.persist)

    def test_fill_only_selected_blank_rows_preserves_every_other_field(self):
        before = deepcopy(self.engine.rows)
        self.assertEqual(self.fill(), 2)
        expected = deepcopy(before)
        expected[1]['serial_number'] = 'ABC000127'
        expected[2]['serial_number'] = 'ABC000128'
        self.assertEqual(self.engine.rows, expected)
        self.assertEqual(self.store.active()['rows'][1]['saved_serial'], 'ABC000127')
        self.assertEqual(len(self.engine.rows), 6)

    def test_invoice_fill_crosses_groups_and_retries_exact_slots(self):
        changes = self.changes(('SEQ001', 'SEQ002', 'SEQ003', 'SEQ004'), (1, 2, 3, 5))
        before = deepcopy(self.engine.rows)
        self.assertEqual(fill_serials(self.engine, self.state, None, changes, self.store.persist), 4)
        self.assertEqual([row['serial_number'] for row in self.engine.rows],
                         ['IMPORTED', 'SEQ001', 'SEQ002', 'SEQ003', '', 'SEQ004'])
        self.assertEqual(self.engine.rows[4], before[4], 'bulk row remains unchanged')
        writes = self.engine.writes
        fill_serials(self.engine, self.state, None, changes, self.store.persist)
        self.assertEqual(self.engine.writes, writes)

    def test_invoice_fill_still_rejects_moved_rows_and_changed_destinations(self):
        changes = self.changes(('SEQ001', 'SEQ002'), (1, 5))
        original = deepcopy(self.engine.rows)
        for modifications in ({'invoice_number': 'OTHER'}, {'part_number': 'CHANGED'}, {'quantity': 3}):
            self.engine.rows = deepcopy(original)
            self.engine.rows[5].update(modifications)
            before = deepcopy(self.engine.rows)
            with self.subTest(modifications=modifications), self.assertRaises(WorkspaceConflict):
                fill_serials(self.engine, self.state, None, changes, self.store.persist)
            self.assertEqual(self.engine.rows, before)

    def test_duplicate_with_other_invoice_or_within_batch_rejects_every_write(self):
        other = dict(self.engine.rows[0], id=100, invoice_number='OTHER', serial_number='abc000128')
        self.engine.rows.append(other)
        before, writes = deepcopy(self.engine.rows), self.engine.writes
        with self.assertRaisesRegex(WorkspaceConflict, 'already exists'):
            self.fill()
        self.assertEqual(self.engine.rows, before)
        self.assertEqual(self.engine.writes, writes)
        with self.assertRaisesRegex(ValueError, 'Duplicate SN'):
            self.fill(self.changes(('same', ' SAME ')))
        self.assertEqual(self.engine.writes, writes)

    def test_never_overwrites_populated_row_or_na_placeholder(self):
        for occupied in ('IMPORTED', 'NA'):
            self.engine.rows[0]['serial_number'] = occupied
            with self.subTest(occupied=occupied), self.assertRaisesRegex(WorkspaceConflict, 'no longer blank'):
                self.fill(self.changes(('NEW',), (0,)))
            self.assertEqual(self.engine.rows[0]['serial_number'], occupied)

    def test_stale_second_row_blocks_first_update(self):
        self.engine.rows[2]['other_note'] = 'Changed externally'
        before, writes = deepcopy(self.engine.rows), self.engine.writes
        with self.assertRaisesRegex(WorkspaceConflict, 'changed since selection'):
            self.fill()
        self.assertEqual(self.engine.rows, before)
        self.assertEqual(self.engine.writes, writes)

    def test_deleted_moved_changed_group_or_bulk_rows_are_rejected(self):
        cases = [({'invoice_number': 'OTHER'}, 1), ({'box_number': 'OTHER'}, 1),
                 ({'pod_number': 'OTHER'}, 1), ({'part_number': 'OTHER'}, 1),
                 ({'quantity': 2}, 1), ({}, 4), ({}, 5)]
        original = deepcopy(self.engine.rows)
        for modifications, index in cases:
            self.engine.rows = deepcopy(original)
            self.engine.rows[index].update(modifications)
            with self.subTest(modifications=modifications, index=index), self.assertRaises(WorkspaceConflict):
                self.fill(self.changes(('NEW',), (index,)))
            self.assertEqual(self.engine.rows[index]['serial_number'], '')
        self.engine.rows = deepcopy(original)
        del self.engine.rows[1]
        with self.assertRaisesRegex(WorkspaceConflict, 'deleted'):
            self.fill()

    def test_invalid_payloads_do_not_write(self):
        valid = self.changes()
        cases = [[], None, 'bad', [valid[0], valid[0]],
                 [dict(valid[0], row_id='UNKNOWN')], [dict(valid[0], row_version='bad')],
                 [dict(valid[0], quantity=2)], [dict(valid[0], row_id=[])]]
        writes = self.engine.writes
        for changes in cases:
            if changes is None:
                # None is the local helper's default; call the actual function.
                with self.assertRaises(ValueError):
                    fill_serials(self.engine, self.state, self.group, None, self.store.persist)
            else:
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    self.fill(changes)
        for serial in ('', 'NA', 'NAN', '=BAD()', 'a\nb', 'x' * 256, None):
            with self.subTest(serial=serial), self.assertRaises(ValueError):
                self.fill(self.changes((serial,), (1,)))
        for group in ({}, dict(self.group, quantity=1), dict(self.group, box_number=1)):
            with self.subTest(group=group), self.assertRaises(ValueError):
                self.fill(group=group)
        self.assertEqual(self.engine.writes, writes)

    def test_initialized_legacy_workspace_without_mode_can_fill(self):
        del self.state['mode']
        self.assertEqual(self.fill(), 2)

    def test_draft_or_pending_save_cannot_fill(self):
        self.state['mode'] = 'draft'
        with self.assertRaises(WorkspaceConflict):
            self.fill()
        self.state['mode'] = 'entry'
        self.state['pending'] = {'unresolved': True}
        with self.assertRaises(WorkspaceConflict):
            self.fill()

    def test_lost_commit_response_retry_is_read_only_and_does_not_fill_next_slots(self):
        changes = self.changes()
        self.engine.fail_commit = 'after'
        with self.assertRaises(SQLAlchemyError):
            self.fill(changes)
        # A refresh can update file metadata before the original request is retried.
        load_database(self.engine, self.state, self.store.persist)
        writes = self.engine.writes
        self.assertEqual(self.fill(changes), 2)
        self.assertEqual(self.engine.writes, writes)
        self.assertEqual([row['serial_number'] for row in self.engine.rows],
                         ['IMPORTED', 'ABC000127', 'ABC000128', '', '', ''])

    def test_persistence_failure_after_commit_can_retry_same_slots(self):
        changes = self.changes()
        with self.assertRaises(OSError):
            self.fill(changes, persist=lambda state: (_ for _ in ()).throw(OSError('Disk unavailable')))
        writes = self.engine.writes
        self.state = self.store.active()
        self.fill(changes)
        self.assertEqual(self.engine.writes, writes)

    def test_commit_failure_or_second_update_failure_rolls_back_whole_batch(self):
        before = deepcopy(self.engine.rows)
        self.engine.fail_commit = 'before'
        with self.assertRaises(SQLAlchemyError):
            self.fill()
        self.assertEqual(self.engine.rows, before)
        execute = FakeConnection.execute
        updates = 0

        def fail_second(connection, statement):
            nonlocal updates
            if statement.is_update:
                updates += 1
                if updates == 2:
                    raise SQLAlchemyError('Second update failed')
            return execute(connection, statement)

        with patch.object(FakeConnection, 'execute', new=fail_second), self.assertRaises(SQLAlchemyError):
            self.fill()
        self.assertEqual(self.engine.rows, before)
        self.assertEqual(self.store.active()['rows'][1]['serial_number'], '')


if __name__ == '__main__':
    unittest.main()
