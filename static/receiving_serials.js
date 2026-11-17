/* Scan-first entry: fixed group + explicit blank row IDs, never a sheet-wide fill. */
((root) => {
    const fields = ['box_number', 'pod_number', 'part_number'];
    const groupKey = row => JSON.stringify(fields.map(field => row[field] || ''));
    const serialKey = value => value.trim().toUpperCase();
    const validateSerial = value => {
        if (typeof value !== 'string' || value.length > 255 || /[\r\n\t]/.test(value)) {
            throw Error('Enter one serial number of at most 255 characters.');
        }
        value = value.trim();
        if (!value || ['NA', 'NAN'].includes(serialKey(value)) || value.startsWith('=')) {
            throw Error('Enter an actual serial number, not a blank, placeholder or formula.');
        }
        return value;
    };
    const sequence = (first, count) => {
        first = validateSerial(first);
        count = Number(count);
        if (!Number.isInteger(count) || count < 1 || count > 20000) throw Error('Quantity must be from 1 to 20,000.');
        const match = /^(.*?)([0-9]+)$/.exec(first);
        if (!match) throw Error('The first serial must end with digits. Other formats need individual scans.');
        const [, prefix, digits] = match, start = BigInt(digits);
        const last = start + BigInt(count - 1);
        if (last.toString().length > digits.length) throw Error('This sequence changes the numeric width. Enter a smaller quantity.');
        return Array.from({length: count}, (_, index) => prefix + (start + BigInt(index)).toString().padStart(digits.length, '0'));
    };
    const groups = rows => {
        const result = new Map();
        for (const row of rows) {
            if (Number(row.quantity) !== 1 || row.db_id == null) continue;
            const key = groupKey(row);
            if (!result.has(key)) result.set(key, {key, group: Object.fromEntries(fields.map(field => [field, row[field] || ''])), rows: []});
            result.get(key).rows.push(row);
        }
        for (const group of result.values()) group.rows.sort((a, b) => a.db_id - b.db_id);
        return [...result.values()];
    };
    const plan = (state, key, values) => {
        const selected = groups(state.rows).find(group => group.key === key);
        if (!selected) throw Error('Choose a carton / POD / product group.');
        if (!values.length || values.length > 20000) throw Error('Fill between 1 and 20,000 serials.');
        const serials = values.map(validateSerial), seen = new Set();
        const existing = new Set(state.rows.map(row => serialKey(row.serial_number)));
        for (const serial of serials) {
            const normalized = serialKey(serial);
            if (seen.has(normalized)) throw Error(`Duplicate serial ${serial} in this fill.`);
            if (existing.has(normalized)) throw Error(`Serial ${serial} already exists in this invoice.`);
            seen.add(normalized);
        }
        const blanks = selected.rows.filter(row => !row.serial_number.trim());
        if (serials.length > blanks.length) throw Error(`Only ${blanks.length} blank unit slots remain in this group. Nothing changed.`);
        return {workspace_id: state.id, group: selected.group,
            rows: serials.map((serial, index) => ({row_id: blanks[index].row_id,
                row_version: blanks[index].row_version, serial_number: serial}))};
    };
    const attach = ({host, getState, sync, csrf, beforeSave, onBusy}) => {
        const find = id => host.querySelector(`#${id}`);
        const select = find('serial-group'), progress = find('serial-progress'), status = find('serial-status');
        const scan = find('serial-scan'), scanForm = find('serial-scan-form');
        const first = find('sequence-first'), count = find('sequence-count');
        const previewBox = find('sequence-preview'), previewText = find('sequence-preview-text');
        const confirm = find('sequence-save'), retry = find('serial-retry'), reload = find('serial-reload');
        let preview = null, operation = null, busy = false, preparing = false;
        const message = (text, error = false) => {
            status.textContent = text;
            status.classList.toggle('serial-error', error);
        };
        const invalidate = () => { preview = null; previewBox.hidden = true; };
        const render = () => {
            const key = select.value, available = groups(getState().rows);
            select.replaceChildren(new Option('Choose carton / POD / product', ''));
            for (const item of available) {
                const {box_number: box, pod_number: pod, part_number: part} = item.group;
                const filled = item.rows.filter(row => row.serial_number.trim()).length;
                select.add(new Option(`${part} · Box ${box || '(blank)'} · ${pod || '(blank POD)'} · ${filled}/${item.rows.length} entered`, item.key));
            }
            select.value = available.some(item => item.key === key) ? key : '';
            const selected = available.find(item => item.key === select.value);
            const blanks = selected ? selected.rows.filter(row => !row.serial_number.trim()) : [];
            progress.textContent = selected ? `${selected.rows.length - blanks.length} of ${selected.rows.length} serials entered. ${blanks.length ? `Next: database row #${blanks[0].db_id}.` : 'Group complete. Choose another group to continue.'}` :
                available.length ? 'Choose a group before scanning. Only blank Qty 1 rows will be filled.' : 'No Qty 1 receiving rows are available. Bulk rows remain in the records below.';
            const locked = busy || preparing || Boolean(operation);
            for (const control of host.querySelectorAll('input, select, button')) control.disabled = locked;
            select.disabled = locked || !available.length;
            for (const control of [scan, scanForm.querySelector('button'), first, count, find('sequence-preview-button')]) {
                control.disabled = locked || !blanks.length;
            }
            confirm.disabled = locked || !preview;
            retry.hidden = !operation || busy;
            reload.hidden = !operation || busy;
            retry.disabled = busy;
            reload.disabled = busy;
        };
        const submit = async () => {
            if (!operation || busy) return;
            busy = true; onBusy(true); render();
            message('Saving to the database. Wait for confirmation before the next scan.');
            try {
                const response = await fetch('/receiving/serials', {method: 'POST', credentials: 'same-origin', headers: {
                    'Content-Type': 'application/json', 'X-CSRF-Token': csrf
                }, body: JSON.stringify(operation.payload)});
                let result;
                try { result = await response.json(); } catch (_) { throw Error('The database response was interrupted.'); }
                if (!response.ok) throw Error(result.error || 'Serial save failed.');
                if (result.workspace?.id !== operation.payload.workspace_id || !Array.isArray(result.workspace.rows)) {
                    throw Error('The saved database state was not returned.');
                }
                const saved = operation.payload.rows.length, kind = operation.kind;
                sync(result.workspace); operation = null; invalidate();
                if (kind === 'scan') scan.value = '';
                else { first.value = ''; count.value = '1'; }
                message(`${saved === 1 ? 'Serial' : `${saved} serials`} saved to the database. Lookup is updated.`);
            } catch (error) {
                message(`${error.message} Retry uses the same rows and serials. Or reload database values before starting again.`, true);
            } finally {
                busy = false; onBusy(Boolean(operation)); render();
                if (operation) retry.focus();
                else if (!scan.disabled) scan.focus();
                else select.focus();
            }
        };
        scanForm.addEventListener('submit', async event => {
            event.preventDefault();
            if (busy || operation || preparing) return;
            preparing = true; onBusy(true); render();
            try {
                await beforeSave();
                operation = {kind: 'scan', payload: plan(getState(), select.value, [scan.value])};
                invalidate();
            } catch (error) { message(error.message, true); }
            finally { preparing = false; onBusy(Boolean(operation)); render(); }
            if (operation) await submit();
            else { scan.focus(); scan.select(); }
        });
        find('sequence-form').addEventListener('submit', async event => {
            event.preventDefault();
            if (busy || operation || preparing) return;
            preparing = true; onBusy(true); invalidate(); render();
            try {
                await beforeSave();
                const values = sequence(first.value, count.value);
                preview = plan(getState(), select.value, values);
                const group = preview.group;
                previewText.textContent = `${values.length} serial${values.length === 1 ? '' : 's'}: ${values[0]} → ${values[values.length - 1]}. Destination: ${group.part_number}, Box ${group.box_number || '(blank)'}, ${group.pod_number || '(blank POD)'}. Only blank rows will be filled.`;
                previewBox.hidden = false;
                message('Check the range and destination, then save the sequence. No sequence values have been saved yet.');
            } catch (error) { message(error.message, true); }
            finally { preparing = false; onBusy(false); render(); }
            if (preview) confirm.focus();
            else first.focus();
        });
        confirm.addEventListener('click', async () => {
            if (!preview || busy || operation || preparing) return;
            operation = {kind: 'sequence', payload: preview};
            await submit();
        });
        retry.addEventListener('click', submit);
        reload.addEventListener('click', () => {
            if (!window.confirm('Reload current database values? Keep a note of the entered serials. Any committed values will remain saved.')) return;
            operation = null; location.reload();
        });
        select.addEventListener('change', () => {
            invalidate(); render();
            message(!select.value ? 'Choose a group to start.' : scan.disabled ? 'No blank unit slots remain in this group. Choose another group to continue.' : 'Ready. Scan one serial and press Enter.');
            if (!scan.disabled) scan.focus();
        });
        for (const input of [first, count]) input.addEventListener('input', () => { invalidate(); render(); });
        render();
        return {hasUnconfirmed: () => busy || preparing || Boolean(operation), refresh: () => { invalidate(); render(); }};
    };
    const api = {groupKey, validateSerial, sequence, groups, plan, attach};
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    root.ReceivingSerials = api;
})(globalThis);
