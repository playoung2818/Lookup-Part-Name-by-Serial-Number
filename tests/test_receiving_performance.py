"""Receiving scaling safeguards: scoped reads, row-level locks, reflection cache.

Uses SQL metadata, a transactional fake and a throwaway SQLite file. Never
touches production records and never runs DDL against a configured database.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, text

from functions.receiving_import import clear_receiving_table_cache, lock_receiving, receiving_table
from functions.receiving_workspace import WorkspaceStore, save_database, save_row
from test_receiving_workspace import FakeEngine, metadata, workbook


class RecordingEngine(FakeEngine):
    def __init__(self):
        super().__init__()
        self.selects = []

    def connect(self):
        connection = super().connect()
        execute = connection.execute

        def recording(statement):
            if statement.is_select:
                self.selects.append(statement)
            return execute(statement)
        connection.execute = recording
        return connection


class ScopedSaveTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = WorkspaceStore(Path(self.temp.name), 'c' * 64)
        with self.store.locked():
            self.state = self.store.create(workbook(serials=('SN-A', '', '')))
        self.engine = RecordingEngine()
        self.table = metadata()

    def tearDown(self):
        self.temp.cleanup()

    def patched(self):
        return (patch('functions.receiving_workspace.lock_receiving'),
                patch('functions.receiving_workspace.receiving_table', return_value=self.table))

    def test_template_commit_reads_only_scoped_rows(self):
        lock, table = self.patched()
        with lock, table, self.store.locked():
            save_database(self.engine, self.state, self.store.persist)
        select = self.engine.selects[0]
        self.assertIsNotNone(select.whereclause, 'save_database must not read the whole receiving_log table')
        sql = str(select.compile(compile_kwargs={'literal_binds': True})).lower()
        self.assertIn("trim(receiving_log.invoice_number) in ('80003610')", sql)
        self.assertIn("in ('sn-a')", sql.lower())

    def test_row_save_uses_row_lock_mode_and_for_update(self):
        lock, table = self.patched()
        with lock as lock_mock, table, self.store.locked():
            save_database(self.engine, self.state, self.store.persist)
            row = self.state['rows'][1]
            self.engine.selects.clear()
            save_row(self.engine, self.state, row['row_id'], ' sn-b ', row['db_snapshot'], self.store.persist)
        self.assertEqual(lock_mock.call_args.kwargs, {'serials': ['SN-B']})
        self.assertIsNotNone(self.engine.selects[0]._for_update_arg)
        self.assertEqual(self.engine.rows[1]['serial_number'], 'sn-b')


class LockModeTests(unittest.TestCase):
    def connection(self):
        connection = MagicMock()
        connection.dialect.name = 'postgresql'
        return connection

    def sql(self, connection):
        return [(str(call.args[0]), call.args[1] if len(call.args) > 1 else None)
                for call in connection.execute.call_args_list]

    def test_batch_mode_keeps_table_lock(self):
        connection = self.connection()
        lock_receiving(connection)
        statements = [sql for sql, _ in self.sql(connection)]
        self.assertIn('LOCK TABLE receiving_log IN SHARE ROW EXCLUSIVE MODE', statements)

    def test_row_mode_allows_concurrent_rows_and_serializes_same_serial(self):
        connection = self.connection()
        lock_receiving(connection, serials=['sn-2', ' SN-1', '', 'na', 'SN-2'])
        executed = self.sql(connection)
        statements = [sql for sql, _ in executed]
        self.assertIn('LOCK TABLE receiving_log IN ROW EXCLUSIVE MODE', statements)
        self.assertNotIn('LOCK TABLE receiving_log IN SHARE ROW EXCLUSIVE MODE', statements)
        keys = [params['key'] for sql, params in executed if 'pg_advisory_xact_lock' in sql]
        self.assertEqual(keys, ['SN-1', 'SN-2'])  # deduplicated, sorted, no blank/NA

    def test_row_mode_without_serial_takes_no_advisory_lock(self):
        connection = self.connection()
        lock_receiving(connection, serials=[''])
        self.assertFalse(any('pg_advisory' in sql for sql, _ in self.sql(connection)))

    def test_sqlite_row_mode_uses_begin_immediate(self):
        connection = MagicMock()
        connection.dialect.name = 'sqlite'
        lock_receiving(connection, serials=['SN-1'])
        connection.exec_driver_sql.assert_called_once_with('BEGIN IMMEDIATE')


class ReflectionCacheTests(unittest.TestCase):
    def setUp(self):
        clear_receiving_table_cache()
        self.addCleanup(clear_receiving_table_cache)

    def create(self, engine):
        with engine.begin() as connection:  # throwaway test database only
            connection.execute(text('CREATE TABLE receiving_log (id INTEGER PRIMARY KEY, entry_date DATE, '
                                    'invoice_number TEXT, box_number TEXT, pod_number TEXT, part_number TEXT, '
                                    'serial_number TEXT, quantity FLOAT)'))

    def test_file_database_reflects_once(self):
        with TemporaryDirectory() as directory:
            engine = create_engine(f"sqlite:///{Path(directory) / 'cache.db'}")
            try:
                self.create(engine)
                with engine.connect() as connection:
                    first = receiving_table(connection)
                with patch('functions.receiving_import.Table', side_effect=AssertionError('reflected again')):
                    with engine.connect() as connection:
                        self.assertIs(receiving_table(connection), first)
            finally:
                engine.dispose()

    def test_in_memory_databases_are_not_shared(self):
        engine = create_engine('sqlite://')
        with engine.connect() as connection:
            with self.assertRaises(Exception):
                receiving_table(connection)  # no table: must not reuse another engine's cache


if __name__ == '__main__':
    unittest.main()
