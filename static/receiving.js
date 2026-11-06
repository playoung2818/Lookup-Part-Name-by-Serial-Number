((root) => {
    const normalizeSN = value => value.trim().toUpperCase();
    const parseColumn = text => {
        const lines = text.replace(/\r\n?/g, '\n').replace(/\n$/, '').split('\n');
        if (lines.some(line => line.includes('\t'))) throw Error('Paste one SN column only (no tabs or extra columns).');
        if (lines.some(line => line.length > 255 || line.trim().startsWith('=') || normalizeSN(line) === 'NAN')) {
            throw Error('Serials must be values of at most 255 characters, not formulas or NAN.');
        }
        return lines.map(line => line.trim());
    };
    const duplicateIds = rows => {
        const seen = new Map(), duplicates = new Set();
        for (const row of rows) {
            const serial = normalizeSN(row.serial_number);
            if (!serial || serial === 'NA') continue;
            if (seen.has(serial)) { duplicates.add(seen.get(serial)); duplicates.add(row.row_id); }
            else seen.set(serial, row.row_id);
        }
        return duplicates;
    };
    if (typeof module !== 'undefined' && module.exports) module.exports = {parseColumn, duplicateIds};
    if (typeof document === 'undefined') return;
    const initialize = document.getElementById('initialize-database');
    if (initialize) initialize.addEventListener('click', async () => {
        initialize.disabled = true;
        const message = document.getElementById('initialize-message');
        message.textContent = 'Writing generated records to database…';
        try {
            const response = await fetch('/receiving/save', {method: 'POST', headers: {
                'Content-Type': 'application/json', 'X-CSRF-Token': initialize.dataset.csrf
            }, body: JSON.stringify({workspace_id: initialize.dataset.workspace})});
            const result = await response.json();
            if (!response.ok) throw Error(result.error || 'Database write failed.');
            location.reload();
        } catch (error) { message.textContent = error.message; initialize.disabled = false; }
    });
    const host = document.getElementById('receiving-workspace');
    if (!host) return;
    let state = JSON.parse(document.getElementById('receiving-state').textContent);
    const csrf = host.dataset.csrf, table = document.getElementById('entry-table');
    const tableRows = [...table.tBodies[0].rows];
    const inputs = new Map(tableRows.map(row => [row.dataset.rowId, row.querySelector('.sn-input')]));
    const pending = new Map(), errors = new Map();
    const message = document.getElementById('entry-message');
    const search = document.getElementById('entry-search'), blankOnly = document.getElementById('only-blank');
    const unsavedOnly = document.getElementById('only-unsaved');
    let timer, queue = Promise.resolve(), inFlightId = null, duplicates = new Set(), cellGrid = null;
    const showMessage = (text, error = false) => {
        message.textContent = text;
        message.className = `small mb-2 ${error ? 'entry-error' : 'entry-success'}`;
    };
    const refresh = (filter = true) => {
        if (filter && cellGrid) cellGrid.clear();
        const byId = new Map(state.rows.map(row => [row.row_id, row]));
        duplicates = duplicateIds(state.rows.map(row => ({...row, serial_number: inputs.get(row.row_id).value})));
        let visible = 0, blanks = 0;
        const query = search.value.trim().toUpperCase();
        for (const tr of tableRows) {
            const row = byId.get(tr.dataset.rowId);
            if (!row) { tr.hidden = true; continue; }
            const input = inputs.get(row.row_id), blank = !input.value.trim(), dirty = pending.has(row.row_id);
            blanks += blank;
            tr.classList.toggle('db-pending', dirty); tr.classList.toggle('db-saved', !dirty);
            tr.classList.toggle('sn-duplicate', duplicates.has(row.row_id));
            input.setAttribute('aria-invalid', duplicates.has(row.row_id) || errors.has(row.row_id) ? 'true' : 'false');
            tr.querySelector('.row-save-status').textContent = duplicates.has(row.row_id) ? 'Duplicate SN' :
                errors.has(row.row_id) ? `Error · #${row.db_id}` : inFlightId === row.row_id ? `Saving · #${row.db_id}` :
                dirty ? `Changed · #${row.db_id}` : `Saved · #${row.db_id}`;
            tr.querySelector('.row-save-status').title = errors.get(row.row_id) || '';
            if (filter) {
                const text = [row.box_number, row.pod_number, row.part_number, input.value, row.Reference, row.invoice_number].join(' ').toUpperCase();
                tr.hidden = !text.includes(query) || (blankOnly.checked && !blank) || (unsavedOnly.checked && !dirty && !errors.has(row.row_id));
            }
            if (!tr.hidden) visible++;
        }
        document.getElementById('entry-count').textContent = `${visible} / ${state.rows.length} database rows · ${blanks} blank SN · ${pending.size} waiting / error`;
        for (const id of ['shipment-upload-form', 'invoice-search-form']) {
            const form = document.getElementById(id);
            if (form) { form.elements.workspace_id.value = state.id; form.elements.revision.value = state.revision; }
        }
    };
    const sync = next => {
        state = next;
        for (const row of state.rows) {
            if (!inputs.has(row.row_id)) continue;
            if (!pending.has(row.row_id)) inputs.get(row.row_id).value = row.serial_number;
            const tr = inputs.get(row.row_id).closest('tr');
            for (const cell of tr.querySelectorAll('[data-field]')) cell.textContent = row[cell.dataset.field] ?? '';
        }
        refresh(false);
    };
    const postRow = async (id, edit) => {
        const response = await fetch('/receiving/row', {method: 'POST', credentials: 'same-origin', headers: {
            'Content-Type': 'application/json', 'X-CSRF-Token': csrf
        }, body: JSON.stringify({workspace_id: state.id, row_id: id, serial_number: edit.value, row_version: edit.version})});
        let result;
        try { result = await response.json(); } catch (_) { throw Error('Database response interrupted. Retry this row.'); }
        if (!response.ok) throw Error(result.error || 'Row save failed.');
        return result;
    };
    const flush = (onlyId = null) => {
        clearTimeout(timer);
        queue = queue.catch(() => {}).then(async () => {
            const failed = new Set();
            while (true) {
                const id = [...pending.keys()].find(key => !failed.has(key) && (!onlyId || key === onlyId));
                if (!id) break;
                refresh(false);
                if (duplicates.has(id)) {
                    errors.set(id, 'Duplicate SN. Correct the highlighted values before saving.'); failed.add(id); continue;
                }
                const edit = {...pending.get(id)};
                inFlightId = id; refresh(false);
                try {
                    const result = await postRow(id, edit);
                    const latest = pending.get(id);
                    if (latest && latest.value === edit.value) pending.delete(id);
                    else if (latest) latest.version = result.workspace.rows.find(row => row.row_id === id).row_version;
                    errors.delete(id); sync(result.workspace);
                    const saved = state.rows.find(row => row.row_id === id);
                    showMessage(`SN saved directly to database row #${saved.db_id}.`);
                } catch (error) {
                    errors.set(id, error.message); failed.add(id); showMessage(error.message, true);
                } finally { inFlightId = null; refresh(false); }
            }
            if (errors.size) showMessage('Some rows were not saved. Hover their Error status for details; correct or retry each row. Refresh to see external database changes.', true);
            refresh(false);
        });
        return queue;
    };
    const changed = input => {
        const id = input.closest('tr').dataset.rowId, row = state.rows.find(row => row.row_id === id);
        const existing = pending.get(id);
        if (input.value.trim() === row.serial_number && inFlightId !== id) { pending.delete(id); errors.delete(id); }
        else pending.set(id, {value: input.value, version: existing ? existing.version : row.row_version});
        errors.delete(id); refresh(false); showMessage('SN changed — saving this row to database…');
        clearTimeout(timer); timer = setTimeout(() => flush(), 700);
    };
    const visibleInputs = () => tableRows.filter(row => !row.hidden).map(row => inputs.get(row.dataset.rowId));
    const focusInput = input => { if (input) { input.focus(); input.select(); input.scrollIntoView({block: 'nearest', inline: 'nearest'}); } };
    for (const [id, input] of inputs) {
        input.addEventListener('input', () => changed(input));
        input.addEventListener('blur', () => { if (pending.has(id)) flush(id); });
        input.addEventListener('keydown', event => {
            if (!['Enter', 'ArrowDown', 'ArrowUp'].includes(event.key)) return;
            event.preventDefault();
            const visible = visibleInputs(), index = visible.indexOf(input);
            const next = visible[index + (event.shiftKey || event.key === 'ArrowUp' ? -1 : 1)];
            if (pending.has(id)) flush(id);
            refresh(); focusInput(next && !next.closest('tr').hidden ? next : null);
        });
        input.addEventListener('paste', event => {
            const text = event.clipboardData.getData('text/plain');
            if (!/[\r\n\t]/.test(text)) return;
            event.preventDefault();
            try {
                const values = parseColumn(text), visible = visibleInputs(), start = visible.indexOf(input);
                if (values.length > visible.length - start) throw Error('Not enough visible rows. Nothing changed.');
                values.forEach((value, index) => { const target = visible[start + index]; target.value = value; changed(target); });
                focusInput(visible[Math.min(start + values.length, visible.length - 1)]);
                flush();
            } catch (error) { showMessage(error.message, true); }
        });
        input.closest('tr').querySelector('.row-save').addEventListener('click', () => {
            if (!pending.has(id) && input.value.trim() !== state.rows.find(row => row.row_id === id).serial_number) changed(input);
            flush(id);
        });
    }
    search.addEventListener('input', () => refresh());
    blankOnly.addEventListener('change', () => refresh()); unsavedOnly.addEventListener('change', () => refresh());
    document.getElementById('show-metadata').addEventListener('change', event => table.classList.toggle('show-metadata', event.target.checked));
    document.getElementById('refresh-database').addEventListener('click', () => {
        if (!pending.size || window.confirm('Reload from database? Unconfirmed cell entries on this page will be discarded.')) location.reload();
    });
    document.addEventListener('keydown', event => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); flush(); }
    });
    window.addEventListener('beforeunload', event => {
        if (pending.size || inFlightId) { event.preventDefault(); event.returnValue = ''; }
    });
    for (const button of document.querySelectorAll('[data-download]')) button.addEventListener('click', async () => {
        await flush();
        if (pending.size) { showMessage('Resolve unsaved rows before downloading.', true); return; }
        try {
            const response = await fetch('/receiving/download', {method: 'POST', body: new URLSearchParams({
                csrf_token: csrf, workspace_id: state.id, format: button.dataset.download
            })});
            if (!response.ok) throw Error('Cannot download current database rows. Refresh and retry.');
            const url = URL.createObjectURL(await response.blob()), anchor = document.createElement('a');
            anchor.href = url; anchor.download = button.dataset.download === 'docx' ? 'Incoming_Receiving_DRAFT.docx' : `Receiving_Log_${state.rows[0].invoice_number}.xlsx`;
            anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 30000);
        } catch (error) { showMessage(error.message, true); }
    });
    document.getElementById('shipment-upload-form').addEventListener('submit', async event => {
        event.preventDefault(); await flush();
        if (pending.size) { showMessage('Resolve unsaved cell entries before generating the next shipment.', true); return; }
        if (!window.confirm('Generate a new draft template? No database records will be written until you review and save it.')) return;
        event.target.elements.workspace_id.value = state.id; event.target.elements.revision.value = state.revision;
        event.target.submit();
    });
    if (root.ReceivingGrid) cellGrid = root.ReceivingGrid.attach({
        table,
        getRows: () => tableRows.filter(row => !row.hidden).map(row => [row.querySelector('.sn-cell')]),
        validate: root.ReceivingGrid.validateValue,
        onMessage: showMessage
    });
    const invoiceSearch = document.getElementById('invoice-search-form');
    if (invoiceSearch) invoiceSearch.addEventListener('submit', async event => {
        event.preventDefault(); await flush();
        if (pending.size) { showMessage('Resolve unsaved serial numbers before switching invoices.', true); return; }
        invoiceSearch.elements.workspace_id.value = state.id;
        invoiceSearch.elements.revision.value = state.revision;
        invoiceSearch.submit();
    });
    refresh();
})(globalThis);
