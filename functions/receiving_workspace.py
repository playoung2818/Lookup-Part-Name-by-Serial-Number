"""Durable per-browser receiving workspaces, with no database schema changes.

JSON state and the source workbook live under instance/receiving_workspaces.
A cross-process owner lock serializes edits/replacement/save. A write-ahead
journal bridges DB commit and file persistence so retries cannot reinsert rows.
"""
from contextlib import contextmanager
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import secrets
import time

from openpyxl import Workbook, load_workbook
from sqlalchemy import select, func, or_

from functions.receiving_import import (
    clean, import_data, keyed_receipts, lock_receiving, read_upload,
    receiving_table, serial_key, signature, snapshot,
)


class WorkspaceConflict(ValueError):
    """Stale tab, externally changed DB row, or ambiguous retry."""


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def identifier(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def atomic_json(path, data):
    temporary = path.with_name(f'.{path.name}.{secrets.token_hex(8)}.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, default=str)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class WorkspaceStore:
    def __init__(self, root, owner):
        if not identifier(owner):
            raise ValueError('Invalid receiving workspace owner.')
        self.path = Path(root) / owner
        self.path.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def locked(self):
        # OS byte/file locks cover threads and workers and release after crashes.
        path = self.path / '.lock'
        with path.open('a+b') as stream:
            stream.seek(0, os.SEEK_END)
            if not stream.tell():
                stream.write(b'0')
                stream.flush()
            deadline = time.monotonic() + 15
            while True:
                try:
                    stream.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except (OSError, BlockingIOError):
                    if time.monotonic() >= deadline:
                        raise WorkspaceConflict('Receiving is busy saving in another tab. Retry shortly.')
                    time.sleep(.05)
            try:
                yield self
            finally:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_UN)

    def active(self):
        pointer = self.path / 'active.json'
        if not pointer.is_file():
            return None
        workspace_id = json.loads(pointer.read_text(encoding='utf-8'))['id']
        if not identifier(workspace_id):
            raise ValueError('Invalid receiving workspace pointer.')
        return json.loads((self.path / f'{workspace_id}.json').read_text(encoding='utf-8'))

    def persist(self, state):
        if not identifier(state['id']):
            raise ValueError('Invalid receiving workspace.')
        atomic_json(self.path / f"{state['id']}.json", state)

    def migrate_database_mode(self, state):
        if state.get('database_mode'):
            return
        backup = self.path / f"{state['id']}.before_database.json"
        if not backup.exists():
            atomic_json(backup, state)
        state['database_mode'] = True
        self.persist(state)

    def require(self, workspace_id, revision=None):
        state = self.active()
        if state is None or state['id'] != workspace_id:
            raise WorkspaceConflict('This shipment was replaced or is not active in this browser. Reload Receiving.')
        if revision is not None and (type(revision) is not int or revision != state['revision']):
            raise WorkspaceConflict('This table changed in another tab. Reload before editing or saving again.')
        return state

    def create(self, content, expected_id='', expected_revision=None):
        current = self.active()
        if (current['id'] if current else '') != expected_id:
            raise WorkspaceConflict('Another shipment is now active. Reload before replacing it.')
        if current and current['revision'] != expected_revision:
            raise WorkspaceConflict('The active table changed while you uploaded. Reload before replacing it.')
        if current and current.get('pending'):
            raise WorkspaceConflict('Resolve the pending database save before replacing this shipment.')
        records, errors, skipped = read_upload(content)
        if errors or skipped or not records:
            raise ValueError('Generated data needs correction: ' + '; '.join(errors[:20]))
        original_keys = list(keyed_receipts(records))
        rows = []
        for key, record in original_keys:
            rows.append(dict(record, row_id=secrets.token_hex(12), original=deepcopy(record),
                             original_key=key, db_id=None, db_snapshot=None, saved_serial=None))
        book = load_workbook(BytesIO(content), read_only=True, data_only=True)
        try:
            state = {'id': secrets.token_hex(32), 'database_mode': True, 'revision': 1, 'created_at': now(),
                     'draft_saved_at': now(), 'database_saved_at': None, 'pending': None,
                     'mode': 'draft', 'invoice_scope': single_invoice(rows),
                     'rows': rows, 'summary': list(book['Read Me'].values)[1:],
                     'exceptions': list(book['Exceptions'].values)[1:]}
        finally:
            book.close()
        (self.path / f"{state['id']}.xlsx").write_bytes(content)
        self.persist(state)
        atomic_json(self.path / 'active.json', {'id': state['id']})
        return state

    def export(self, state):
        book = load_workbook(self.path / f"{state['id']}.xlsx")
        sheet = book['Receiving Log']
        fields = ('entry_date', 'invoice_number', 'box_number', 'pod_number',
                  'part_number', 'serial_number', 'quantity', 'Reference')
        for number, row in enumerate(state['rows'], 2):
            for column, key in enumerate(fields, 1):
                value = row.get(key)
                cell = sheet.cell(number, column)
                cell.value = None if value == '' else value
                if isinstance(cell.value, str):
                    cell.data_type = 's'
        status = book.create_sheet('Entry Status')
        status.append(['Receiving Row', 'Database ID', 'SN', 'Status'])
        for number, row in enumerate(state['rows'], 2):
            status.append([number, row['db_id'], row['serial_number'] or None, row_status(row)])
        output = BytesIO()
        book.save(output)
        book.close()
        return output.getvalue()


def single_invoice(rows):
    invoices = {clean(row['invoice_number']) for row in rows}
    if len(invoices) != 1 or not next(iter(invoices)):
        raise ValueError('Exactly one nonblank INV# is required per receiving transaction.')
    return next(iter(invoices))


def update_template(state, changes, persist):
    """Validate the entire draft before changing any server-side values."""
    if state.get('mode') != 'draft' or state.get('pending'):
        raise WorkspaceConflict('This template is closed or has a pending database write.')
    fields = ('entry_date', 'box_number', 'pod_number', 'part_number',
              'serial_number', 'quantity', 'Reference')
    if not isinstance(changes, list) or len(changes) != len(state['rows']):
        raise ValueError('Submit all template rows; adding/deleting rows is not supported.')
    by_id = {row['row_id']: row for row in state['rows']}
    book = Workbook()
    book.active.append(['Date', 'Inv#', 'Box #', 'POD#', 'Part#', 'SN#', 'QTY', 'Reference'])
    seen = set()
    for change in changes:
        if not isinstance(change, dict) or set(change) != {'row_id', *fields}:
            raise ValueError('Invalid template fields. INV# cannot be changed.')
        row_id = change['row_id']
        if not isinstance(row_id, str) or row_id not in by_id or row_id in seen:
            raise ValueError('Unknown or repeated template row.')
        seen.add(row_id)
        values = [change[key] for key in fields]
        if any(not isinstance(value, (str, int, float)) or isinstance(value, bool) for value in values):
            raise ValueError('Invalid template value.')
        if any(any(c in str(value) for c in '\r\n\t') for value in values):
            raise ValueError('Template cells must contain single values.')
        book.active.append([change['entry_date'], state['invoice_scope'], change['box_number'],
                            change['pod_number'], change['part_number'], change['serial_number'],
                            change['quantity'], change['Reference']])
    output = BytesIO()
    book.save(output)
    book.close()
    records, errors, skipped = read_upload(output.getvalue())
    if errors or skipped or len(records) != len(changes):
        raise ValueError('Invalid template: ' + '; '.join(errors[:20]))
    serials = [serial_key(row['serial_number']) for row in records if serial_key(row['serial_number']) not in ('', 'NA')]
    if len(serials) != len(set(serials)):
        raise ValueError('Duplicate serial numbers in template.')
    for change, record in zip(changes, records):
        row = by_id[change['row_id']]
        for key in fields:
            row[key] = record.get(key, '')
    state['revision'] += 1
    state['draft_saved_at'] = now()
    persist(state)


def search_invoice(engine, workspace, invoice, expected_id, revision):
    invoice = clean(invoice)
    if not invoice or len(invoice) > 255:
        raise ValueError('Enter an exact INV# (including any leading zeros).')
    with engine.connect() as connection:
        table = receiving_table(connection)
        records = [dict(row) for row in connection.execute(
            select(table).where(table.c.invoice_number == invoice).order_by(table.c.id)).mappings()
                   if clean(row['invoice_number']) == invoice]
    if not records:
        raise ValueError('No receiving records found for this exact INV#.')
    ids = [row.get('id') for row in records]
    if None in ids or len(set(ids)) != len(ids):
        raise ValueError('Receiving IDs must be unique and non-null.')
    book = Workbook()
    book.active.title = 'Receiving Log'
    fields = ('entry_date', 'invoice_number', 'box_number', 'pod_number', 'part_number', 'serial_number', 'quantity', 'Reference')
    book.active.append(['Date', 'Inv#', 'Box #', 'POD#', 'Part#', 'SN#', 'QTY', 'Reference'])
    for record in records:
        book.active.append([record.get(key) for key in fields])
    book.create_sheet('Read Me').append(['Field', 'Value'])
    book.create_sheet('Exceptions').append(['Type', 'Line', 'Part', 'Details'])
    content = BytesIO()
    book.save(content)
    book.close()
    state = workspace.create(content.getvalue(), expected_id, revision)
    for row, record in zip(state['rows'], records):
        row.update(db_id=record['id'], db_snapshot=snapshot([record]), saved_serial=clean(record['serial_number']))
    state['mode'] = 'entry'
    workspace.persist(state)
    return state


def row_status(row):
    if row['db_id'] is None:
        return 'Not saved to database'
    return 'Saved' if row['serial_number'] == row['saved_serial'] else 'SN changed - save to database'


def public_state(state):
    return {'id': state['id'], 'revision': state['revision'],
            'mode': state.get('mode', 'entry'), 'invoice_scope': state.get('invoice_scope', ''),
            'created_at': state['created_at'], 'draft_saved_at': state['draft_saved_at'],
            'database_saved_at': state['database_saved_at'], 'pending': bool(state.get('pending')),
            'needs_initialization': any(row['db_id'] is None for row in state['rows']),
            'missing_ids': [row['db_id'] for row in state['rows'] if row.get('db_missing')],
            'summary': state['summary'], 'exceptions': state['exceptions'],
            'rows': [dict({key: row.get(key, '') for key in (
                'row_id', 'entry_date', 'invoice_number', 'box_number', 'pod_number',
                'part_number', 'serial_number', 'quantity', 'Reference', 'db_id', 'saved_serial')},
                          row_version=row.get('db_snapshot'))
                     for row in state['rows'] if not row.get('db_missing')]}


def update_serials(state, changes):
    if state.get('pending'):
        raise WorkspaceConflict('A database save needs recovery. Click Save to database before editing again.')
    if not isinstance(changes, list) or len(changes) > 20000:
        raise ValueError('Invalid serial edits.')
    by_id = {row['row_id']: row for row in state['rows']}
    edited = set()
    validated = []
    for change in changes:
        if not isinstance(change, dict) or set(change) != {'row_id', 'serial_number'}:
            raise ValueError('Only serial numbers can be edited.')
        row_id, value = change['row_id'], change['serial_number']
        if not isinstance(row_id, str) or row_id not in by_id or row_id in edited:
            raise ValueError('Unknown or repeated receiving row.')
        if not isinstance(value, str) or len(value) > 255 or any(c in value for c in '\r\n\t'):
            raise ValueError('Serial numbers must be a single value, at most 255 characters.')
        value = value.strip()
        if value.startswith('=') or value.upper() == 'NAN':
            raise ValueError('Enter a serial value, not a formula or NAN placeholder.')
        validated.append((by_id[row_id], value))
        edited.add(row_id)
    for row, value in validated:
        row['serial_number'] = value
    if validated:
        state['revision'] += 1
        state['draft_saved_at'] = now()


def finalize_pending(state, persist):
    pending = state['pending']
    by_id = {row['row_id']: row for row in state['rows']}
    for binding in pending['bindings']:
        row = by_id[binding['row_id']]
        after = binding['after']
        row['db_id'] = after['id']
        row['db_snapshot'] = snapshot([after])
        row['saved_serial'] = clean(after['serial_number'])
    state['mode'] = 'entry'
    state['database_saved_at'] = pending['saved_at']
    state['pending'] = None
    state['revision'] += 1
    persist(state)


def recover_pending(state, existing, persist):
    """Resolve a lost commit response using all-before/all-after DB snapshots."""
    if not state.get('pending'):
        return False
    bindings = state['pending']['bindings']
    def matches(actual, expected):
        return actual is None if expected is None else actual is not None and snapshot([actual]) == snapshot([expected])
    if all(matches(existing.get(b['after']['id']), b['after']) for b in bindings):
        finalize_pending(state, persist)
        return True
    if all(matches(existing.get(b['after']['id']), b['before']) for b in bindings):
        state['pending'] = None
        persist(state)
        return False
    raise WorkspaceConflict('The previous database save has an unexpected result or was changed externally. Nothing new saved; contact the administrator before retrying.')


def load_database(engine, state, persist):
    """Read every visible value from DB; never render a cached row on DB failure."""
    ids = {row['db_id'] for row in state['rows'] if row['db_id'] is not None}
    pending = state.get('pending')
    if pending:
        ids.update(binding['after']['id'] for binding in pending['bindings'])
    if not ids:
        return
    with engine.connect() as connection:
        if pending:
            lock_receiving(connection)
        table = receiving_table(connection)
        actual = {row['id']: dict(row) for row in connection.execute(
            select(table).where(table.c.id.in_(ids))).mappings()}
        if pending:
            recover_pending(state, actual, persist)
            connection.rollback()
    changed = False
    for row in state['rows']:
        if row['db_id'] is None:
            continue
        current = actual.get(row['db_id'])
        if current is not None and state.get('invoice_scope') and clean(current['invoice_number']) != state['invoice_scope']:
            raise WorkspaceConflict('A database row moved to another invoice. Search for the INV# again.')
        if current is None:
            changed |= not row.get('db_missing', False)
            row['db_missing'] = True
            continue
        changed |= row.get('db_missing', False) or row['db_snapshot'] != snapshot([current])
        row['db_missing'] = False
        for key in ('invoice_number', 'box_number', 'pod_number', 'part_number', 'serial_number', 'Reference'):
            row[key] = clean(current.get(key))
        day = current['entry_date']
        row['entry_date'] = day.isoformat() if hasattr(day, 'isoformat') else clean(day)
        row['quantity'] = current['quantity']
        row['saved_serial'] = row['serial_number']
        row['db_snapshot'] = snapshot([current])
    if changed:
        state['revision'] += 1
        persist(state)


def save_row(engine, state, row_id, value, expected_version, persist):
    """Commit one SN only. A retry of an already-committed value is read-only."""
    if state.get('mode') == 'draft':
        raise WorkspaceConflict('Review and save the template before entering database serial numbers.')
    row = next((row for row in state['rows'] if row['row_id'] == row_id), None)
    if row is None or row['db_id'] is None:
        raise ValueError('This row has not been initialized in the database.')
    if state.get('pending'):
        raise WorkspaceConflict('Resolve the pending generation save before editing rows.')
    temporary = {'rows': [deepcopy(row)], 'revision': 0, 'pending': None}
    update_serials(temporary, [{'row_id': row_id, 'serial_number': value}])
    value = temporary['rows'][0]['serial_number']
    with engine.connect() as connection:
        try:
            lock_receiving(connection)
            table = receiving_table(connection)
            key = serial_key(value)
            condition = table.c.id == row['db_id']
            if key not in ('', 'NA'):
                condition = or_(condition, func.upper(func.trim(table.c.serial_number)) == key)
            current_rows = [dict(record) for record in connection.execute(select(table).where(condition)).mappings()]
            current = next((record for record in current_rows if record['id'] == row['db_id']), None)
            if current is None:
                raise WorkspaceConflict('This database row was deleted. Reload the table; no replacement row was inserted.')
            scope = state.get('invoice_scope') or single_invoice(state['rows'])
            if clean(current['invoice_number']) != scope or clean(row['invoice_number']) != scope:
                raise WorkspaceConflict('This row does not belong to the selected INV#. Nothing changed.')
            # Safe idempotent retry after a lost commit response, with no update.
            if clean(current['serial_number']) != value:
                if not isinstance(expected_version, str) or snapshot([current]) != expected_version:
                    raise WorkspaceConflict('This row changed in the database. Reload to see its current value before editing again.')
                if key not in ('', 'NA') and any(serial_key(record['serial_number']) == key
                                                and record['id'] != current['id'] for record in current_rows):
                    raise WorkspaceConflict(f'SN {value} already exists in another receiving row. Nothing changed.')
                current = dict(connection.execute(table.update().where(table.c.id == current['id'], table.c.invoice_number == scope)
                               .values(serial_number=value).returning(table)).mappings().one())
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    # Once committed, DB is the source of truth even if this metadata write fails.
    row['serial_number'] = clean(current['serial_number'])
    row['saved_serial'] = row['serial_number']
    row['db_snapshot'] = snapshot([current])
    row['db_missing'] = False
    state['database_saved_at'] = now()
    state['revision'] += 1
    persist(state)
    return row['db_id']


def save_database(engine, state, persist):
    """Upsert workspace rows by stable IDs; no deletes, no schema changes.

    Caller holds the workspace lock. Every row is validated before writes. DB
    snapshots reject external edits. Bindings are journaled before DB commit.
    """
    counts = {'inserted': 0, 'updated': 0, 'unchanged': 0, 'linked': 0}
    with engine.connect() as connection:
        try:
            lock_receiving(connection)
            table = receiving_table(connection)
            if 'id' not in table.c:
                raise ValueError('receiving_log.id is required for incremental saving.')
            existing_rows = [dict(row) for row in connection.execute(select(table).order_by(table.c.id)).mappings()]
            existing = {row['id']: row for row in existing_rows}
            if len(existing) != len(existing_rows) or None in existing:
                raise ValueError('Receiving IDs must be unique and non-null.')
            if recover_pending(state, existing, persist):
                connection.rollback()
                return dict(counts, recovered=True)
            if state.get('template_commit'):
                scope = state['invoice_scope']
                if single_invoice(state['rows']) != scope:
                    raise WorkspaceConflict('Template rows must belong to the generated INV#.')
                if any(clean(row['invoice_number']) == scope for row in existing_rows):
                    raise WorkspaceConflict('This INV# already exists. Use Reload by INV# for serial-only entry; existing receipts were not changed.')
            groups, existing_serials = {}, {}
            for key, row in keyed_receipts(existing_rows):
                groups.setdefault(key, []).append(row)
                existing_serials.setdefault(serial_key(row['serial_number']), []).append(row)
            current_keys = dict((row['row_id'], key) for key, row in keyed_receipts(state['rows']))
            serials, used_ids, plans = {}, set(), []
            for number, row in enumerate(state['rows'], 1):
                serial = serial_key(row['serial_number'])
                if serial and serial != 'NA':
                    if serial in serials:
                        raise WorkspaceConflict(f'Duplicate SN {row["serial_number"]} in rows {serials[serial]} and {number}. Correct the table and save again.')
                    serials[serial] = number
                actual = None
                if row['db_id'] is not None:
                    actual = existing.get(row['db_id'])
                    if actual is None or snapshot([actual]) != row['db_snapshot']:
                        raise WorkspaceConflict(f'Row {number} (DB #{row["db_id"]}) changed outside this workspace. Nothing saved; contact the administrator.')
                else:
                    original = row['original']
                    candidates = [candidate for candidate in groups.get(row['original_key'], [])
                                  if signature(candidate) == signature(original)]
                    if not candidates:
                        candidates = [candidate for candidate in groups.get(current_keys[row['row_id']], [])
                                      if signature(candidate) == signature(row)]
                    if len(candidates) > 1:
                        raise WorkspaceConflict(f'Row {number} has multiple matching database receipts. Resolve them before saving.')
                    if candidates:
                        actual = candidates[0]
                if actual is not None:
                    if actual['id'] in used_ids:
                        raise WorkspaceConflict(f'Row {number} maps to a database row already used by another unit.')
                    used_ids.add(actual['id'])
                if serial and serial != 'NA':
                    other = [candidate for candidate in existing_serials.get(serial, [])
                             if actual is None or candidate['id'] != actual['id']]
                    if other:
                        raise WorkspaceConflict(f'Row {number}: SN {row["serial_number"]} already exists in another database receipt. Nothing saved.')
                data = import_data(row, table)
                changed = actual is None or any(
                    clean(actual.get(key)) != clean(value) for key, value in data.items())
                plans.append((row, actual, data, changed))
            # A regenerated workbook must not silently add a blank copy of a
            # unit whose SN was already entered in an older workspace. Without
            # a stored binding, changing serialization is ambiguous: stop rather
            # than guessing which existing physical unit to overwrite.
            def slot(record):
                event = signature(record)
                return (*event[:5], float(event[-1]))
            expected_counts = Counter(slot(row) for row in state['rows'])
            existing_counts = Counter(slot(row) for row in existing_rows)
            insert_counts = Counter(slot(row) for row, actual, _, _ in plans if actual is None)
            if any(count > max(expected_counts[key] - existing_counts[key], 0)
                   for key, count in insert_counts.items()):
                raise WorkspaceConflict('Matching shipment units already exist with different serials. Nothing inserted. Use the original workspace or reconcile those receipts before saving a regenerated table.')
            bindings = []
            for row, actual, data, changed in plans:
                before = deepcopy(actual)
                if actual is None:
                    actual = dict(connection.execute(table.insert().values(**data).returning(table)).mappings().one())
                    counts['inserted'] += 1
                elif changed:
                    actual = dict(connection.execute(table.update().where(table.c.id == actual['id']).values(**data).returning(table)).mappings().one())
                    counts['updated'] += 1
                else:
                    counts['unchanged' if row['db_id'] is not None else 'linked'] += 1
                bindings.append({'row_id': row['row_id'], 'before': before, 'after': actual})
            state['pending'] = {'bindings': bindings, 'saved_at': now()}
            persist(state)  # durable journal BEFORE the transaction can commit
            connection.commit()
            finalize_pending(state, persist)
            return counts
        except Exception:
            connection.rollback()
            # Keep any pending journal: a lost commit response is ambiguous.
            raise
