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
    const validateSerialPaste = (rows, changes) => {
        const values = new Map(changes.map(change => [change.row_id, change.serial_number]));
        const duplicates = duplicateIds(rows.map(row => ({...row,
            serial_number: values.has(row.row_id) ? values.get(row.row_id) : row.serial_number})));
        if (changes.some(change => duplicates.has(change.row_id))) {
            throw Error('Paste contains duplicate serials, or a serial already exists in this invoice. Nothing was pasted.');
        }
    };
    const canScanRow = row => Boolean(row && row.db_id != null &&
        !row.serial_number.trim());
    const nextBlankRow = (rows, currentId, eligible) => {
        const index = rows.findIndex(row => row.row_id === currentId), current = rows[index];
        if (!current) return null;
        for (let i = index + 1; i < rows.length; i++) {
            const row = rows[i];
            if (['box_number', 'pod_number', 'part_number'].every(field => row[field] === current[field]) &&
                !row.serial_number.trim() && eligible(row)) return row;
        }
        return null;
    };
    if (typeof module !== 'undefined' && module.exports) module.exports = {parseColumn, duplicateIds, nextBlankRow, canScanRow, validateSerialPaste};
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
    const state = JSON.parse(document.getElementById('receiving-state').textContent);
    const csrf = host.dataset.csrf, table = document.getElementById('entry-table');
    const tableRows = [...table.tBodies[0].rows];
    // O(1) lookups. Large invoices previously rescanned every row on each keystroke.
    const trById = new Map(tableRows.map(tr => [tr.dataset.rowId, tr]));
    const inputs = new Map(tableRows.map(tr => [tr.dataset.rowId, tr.querySelector('.sn-input')]));
    const rowById = new Map(state.rows.map(row => [row.row_id, row]));
    // Table order never changes; row objects are updated in place after each save.
    const ordered = tableRows.map(tr => rowById.get(tr.dataset.rowId)).filter(Boolean);
    const pending = new Map(), errors = new Map();
    const message = document.getElementById('entry-message');
    const search = document.getElementById('entry-search'), blankOnly = document.getElementById('only-blank');
    const unsavedOnly = document.getElementById('only-unsaved');
    let queue = Promise.resolve(), inFlightId = null, cellGrid = null, visible = 0, countFrame = 0;
    const showMessage = (text, error = false) => {
        message.textContent = text;
        message.className = `small mb-2 ${error ? 'entry-error' : 'entry-success'}`;
    };
    // Incremental duplicate index: normalized SN -> IDs of rows currently holding it.
    const serialIndex = new Map(), keyById = new Map();
    const isDuplicate = id => { const key = keyById.get(id); return Boolean(key) && serialIndex.get(key).size > 1; };
    const indexSerial = id => {
        // Re-indexes one row; returns the rows whose duplicate status may have changed.
        const before = keyById.get(id) || '', normalized = normalizeSN(inputs.get(id).value);
        const after = normalized && normalized !== 'NA' ? normalized : '';
        if (before === after) return [id];
        const affected = new Set([id]);
        if (before) {
            const holders = serialIndex.get(before);
            holders.delete(id);
            holders.forEach(other => affected.add(other));
            if (!holders.size) serialIndex.delete(before);
        }
        if (after) {
            if (!serialIndex.has(after)) serialIndex.set(after, new Set());
            const holders = serialIndex.get(after);
            holders.forEach(other => affected.add(other));
            holders.add(id);
            keyById.set(id, after);
        } else keyById.delete(id);
        return [...affected];
    };
    const updateCount = () => {
        countFrame = 0;
        let blanks = 0;
        for (const id of rowById.keys()) if (inputs.has(id) && !inputs.get(id).value.trim()) blanks++;
        document.getElementById('entry-count').textContent = `${visible} / ${state.rows.length} database rows · ${blanks} blank SN · ${pending.size} waiting / error`;
    };
    // Coalesce counter updates: a 2,000-row paste recounts once, not 2,000 times.
    const scheduleCount = () => {
        if (!countFrame) countFrame = (root.requestAnimationFrame || (fn => setTimeout(fn, 16)))(updateCount);
    };
    const updateForms = () => {
        for (const id of ['shipment-upload-form', 'invoice-search-form']) {
            const form = document.getElementById(id);
            if (form) { form.elements.workspace_id.value = state.id; form.elements.revision.value = state.revision; }
        }
    };
    const renderRow = id => {
        const tr = trById.get(id), row = rowById.get(id), input = inputs.get(id);
        if (!tr || !row) return;
        const dirty = pending.has(id), duplicate = isDuplicate(id);
        const status = tr.querySelector('.row-save-status'), button = tr.querySelector('.row-save');
        tr.classList.toggle('db-pending', dirty); tr.classList.toggle('db-saved', !dirty);
        tr.classList.toggle('sn-duplicate', duplicate);
        input.setAttribute('aria-invalid', duplicate || errors.has(id) ? 'true' : 'false');
        status.textContent = duplicate ? 'Duplicate SN' :
            errors.has(id) ? `Error · #${row.db_id}` : inFlightId === id ? `Saving · #${row.db_id}` :
            dirty ? `Changed · #${row.db_id}` : `Saved · #${row.db_id}`;
        status.title = errors.get(id) || '';
        const label = input.readOnly ? 'Correct' : 'Save';
        button.textContent = label;
        button.setAttribute('aria-label', `${label} SN for database row ${row.db_id}`);
    };
    const renderRows = ids => { for (const id of ids) renderRow(id); scheduleCount(); };
    // Full pass over all rows: only for filter changes and the initial load.
    const refresh = () => {
        if (cellGrid) cellGrid.clear();
        const query = search.value.trim().toUpperCase();
        visible = 0;
        for (const tr of tableRows) {
            const id = tr.dataset.rowId, row = rowById.get(id);
            if (!row) { tr.hidden = true; continue; }
            const input = inputs.get(id), blank = !input.value.trim(), dirty = pending.has(id);
            const text = [row.box_number, row.pod_number, row.part_number, input.value, row.Reference, row.invoice_number, row.item_role, row.ordering_model].join(' ').toUpperCase();
            tr.hidden = !text.includes(query) || (blankOnly.checked && !blank) || (unsavedOnly.checked && !dirty && !errors.has(id));
            if (!tr.hidden) visible++;
        }
        updateCount();
        updateForms();
    };
    // /receiving/row returns only the saved row plus workspace metadata.
    const applySaved = result => {
        Object.assign(state, result.workspace);
        const saved = result.row, row = rowById.get(saved.row_id);
        if (!row) return;
        Object.assign(row, saved);
        const input = inputs.get(saved.row_id);
        if (!pending.has(saved.row_id)) input.value = row.serial_number;
        for (const cell of trById.get(saved.row_id).querySelectorAll('[data-field]')) cell.textContent = row[cell.dataset.field] ?? '';
        renderRows(indexSerial(saved.row_id));
        updateForms();
    };
    const postRow = async (id, edit) => {
        const response = await fetch('/receiving/row', {method: 'POST', credentials: 'same-origin', headers: {
            'Content-Type': 'application/json', 'X-CSRF-Token': csrf
        }, body: JSON.stringify({workspace_id: state.id, row_id: id, serial_number: edit.value, row_version: edit.version})});
        let result;
        try { result = await response.json(); } catch (_) { throw Error('Database response interrupted. Retry this row.'); }
        if (!response.ok) throw Error(result.error || 'Row save failed.');
        if (!result.row || result.row.row_id !== id) throw Error('The server did not confirm this row. Refresh before retrying.');
        return result;
    };
    const flush = (onlyId = null) => {
        queue = queue.catch(() => {}).then(async () => {
            const failed = new Set();
            while (true) {
                const id = [...pending.keys()].find(key => !failed.has(key) && (!onlyId || key === onlyId));
                if (!id) break;
                if (isDuplicate(id)) {
                    errors.set(id, 'Duplicate SN. Correct the highlighted values before saving.'); failed.add(id);
                    renderRow(id); continue;
                }
                const edit = {...pending.get(id)};
                inFlightId = id; renderRow(id);
                try {
                    const result = await postRow(id, edit);
                    const latest = pending.get(id);
                    if (latest && latest.value === edit.value) pending.delete(id);
                    else if (latest) latest.version = result.row.row_version;
                    errors.delete(id);
                    if (!pending.has(id)) inputs.get(id).readOnly = true;
                    applySaved(result);
                    showMessage(`SN saved directly to database row #${result.row.db_id}.`);
                } catch (error) {
                    errors.set(id, error.message); failed.add(id); showMessage(error.message, true);
                } finally { inFlightId = null; renderRow(id); scheduleCount(); }
            }
            if (errors.size) showMessage('Some rows were not saved. Hover their Error status for details; correct or retry each row. Refresh to see external database changes.', true);
        });
        return queue;
    };
    const changed = input => {
        const id = input.closest('tr').dataset.rowId, row = rowById.get(id);
        const existing = pending.get(id);
        if (input.value.trim() === row.serial_number && inFlightId !== id) { pending.delete(id); errors.delete(id); }
        else pending.set(id, {value: input.value, version: existing ? existing.version : row.row_version});
        errors.delete(id);
        renderRows(indexSerial(id));
        showMessage('Correction entered. Press Enter or Save, or leave the cell to save it.');
    };
    const focusInput = input => { if (input) { input.focus(); input.select(); input.scrollIntoView({block: 'nearest', inline: 'nearest'}); } };
    for (const [id, input] of inputs) {
        input.addEventListener('focus', () => {
            const row = rowById.get(id);
            if (input.disabled || inFlightId === id || pending.has(id)) return;
            if (input.readOnly && canScanRow(row) && !input.value.trim()) {
                input.readOnly = false;
                renderRow(id);
                showMessage('Ready to scan into this blank row. Enter saves and moves to the next blank row in this group.');
            }
        });
        input.addEventListener('input', () => { if (!input.readOnly) changed(input); });
        input.addEventListener('blur', () => { if (pending.has(id)) flush(id); });
        let advancing = false;
        input.addEventListener('keydown', async event => {
            if (event.key !== 'Enter') return;
            event.preventDefault();
            if (advancing || input.disabled) return;
            advancing = true;
            const wasEditable = !input.readOnly;
            input.readOnly = true;
            try {
                if (pending.has(id)) await flush(id);
                if (pending.has(id) || errors.has(id)) {
                    input.readOnly = !wasEditable;
                    focusInput(input);
                    return;
                }
                const next = nextBlankRow(ordered, id, row => {
                    const target = inputs.get(row.row_id);
                    return target && !target.disabled && !trById.get(row.row_id).hidden &&
                        !target.value.trim() && !pending.has(row.row_id) && !errors.has(row.row_id);
                });
                if (next) {
                    const target = inputs.get(next.row_id);
                    target.readOnly = false;
                    renderRow(next.row_id);
                    focusInput(target);
                } else {
                    showMessage('No more visible blank SN rows in this carton / POD / product group. Choose another group to continue.');
                }
            } finally { advancing = false; renderRow(id); scheduleCount(); }
        });
        trById.get(id).querySelector('.row-save').addEventListener('click', () => {
            if (input.readOnly) { input.readOnly = false; renderRow(id); focusInput(input); return; }
            if (!pending.has(id) && input.value.trim() !== rowById.get(id).serial_number) changed(input);
            if (pending.has(id)) flush(id);
            else { input.readOnly = true; renderRow(id); }
        });
    }
    if (root.ReceivingGrid) cellGrid = root.ReceivingGrid.attach({
        table,
        getRows: () => tableRows.filter(tr => !tr.hidden).map(tr => [tr.querySelector('.sn-cell')]),
        validate: root.ReceivingGrid.validateValue,
        canEdit: input => {
            const id = input.closest('tr').dataset.rowId;
            return inFlightId !== id && (!input.readOnly || canScanRow(rowById.get(id)));
        },
        applyPaste: prepared => {
            const changes = prepared.map(({input, value}) => ({
                row_id: input.closest('tr').dataset.rowId, serial_number: value
            }));
            validateSerialPaste(state.rows.map(row => ({...row,
                serial_number: inputs.get(row.row_id).value})), changes);
            // All destinations and values are validated before changing any input.
            for (const {input, value} of prepared) { input.readOnly = false; input.value = value; }
            for (const {input} of prepared) changed(input);
            flush();
        },
        onMessage: showMessage
    });
    search.addEventListener('input', () => refresh());
    blankOnly.addEventListener('change', () => refresh()); unsavedOnly.addEventListener('change', () => refresh());
    document.getElementById('show-metadata').addEventListener('change', event => table.classList.toggle('show-metadata', event.target.checked));
    document.getElementById('refresh-database').addEventListener('click', () => {
        if (!pending.size || window.confirm('Reload from database? Unconfirmed corrections on this page will be discarded.')) location.reload();
    });
    document.addEventListener('keydown', event => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); flush(); }
    });
    window.addEventListener('beforeunload', event => {
        if (pending.size || inFlightId) { event.preventDefault(); event.returnValue = ''; }
    });
    for (const button of document.querySelectorAll('[data-download]')) button.addEventListener('click', async () => {
        await flush();
        if (pending.size) { showMessage('Resolve unsaved corrections before downloading.', true); return; }
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
        if (pending.size) { showMessage('Resolve unsaved corrections before generating the next shipment.', true); return; }
        if (!window.confirm('Generate a new draft template? No database records will be written until you review and save it.')) return;
        event.target.elements.workspace_id.value = state.id; event.target.elements.revision.value = state.revision;
        event.target.submit();
    });
    const invoiceSearch = document.getElementById('invoice-search-form');
    if (invoiceSearch) invoiceSearch.addEventListener('submit', async event => {
        event.preventDefault(); await flush();
        if (pending.size) { showMessage('Resolve unsaved corrections before switching invoices.', true); return; }
        invoiceSearch.elements.workspace_id.value = state.id;
        invoiceSearch.elements.revision.value = state.revision;
        invoiceSearch.submit();
    });
    // Initial load: index all serials once, render every row once, then filter.
    for (const id of rowById.keys()) if (inputs.has(id)) indexSerial(id);
    for (const id of rowById.keys()) renderRow(id);
    refresh();
})(globalThis);
