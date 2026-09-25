(() => {
    const body = document.getElementById('batch-rows');
    const form = document.getElementById('batch-form');
    const status = document.getElementById('batch-status');
    const shared = ['warehouse', 'purpose', 'borrower', 'borrow_date'];
    const input = (row, name) => row.querySelector(`[name="${name}"]`);
    function renumber() {
        Array.from(body.rows).forEach((row, index) => {
            row.querySelector('.row-number').textContent = index + 1;
            row.querySelectorAll('input').forEach(cell => {
                cell.setAttribute('aria-label', `Row ${index + 1}: ${cell.name.replaceAll('_', ' ')}`);
            });
        });
        document.getElementById('add-row').disabled = body.rows.length >= 100;
    }
    function copyShared(source, target) {
        shared.forEach(name => { input(target, name).value = input(source, name).value; });
    }
    function attach(row) {
        window.attachBorrowLookup(input(row, 'serial_number'), input(row, 'item_number'), row.querySelector('.lookup-status'));
        row.querySelector('.remove-row').addEventListener('click', () => {
            row.remove();
            if (!body.rows.length) addRow();
            renumber();
        });
    }
    function addRow() {
        if (body.rows.length >= 100) return null;
        const row = document.getElementById('batch-row-template').content.firstElementChild.cloneNode(true);
        if (body.rows.length) copyShared(body.rows[body.rows.length - 1], row);
        body.append(row);
        attach(row);
        renumber();
        return row;
    }
    Array.from(body.rows).forEach(attach);
    renumber();
    document.getElementById('add-row').addEventListener('click', () => {
        const row = addRow();
        if (row) input(row, 'serial_number').focus();
    });
    // Excel clipboard text is tab-separated, with quoted multiline cells.
    function parseClipboard(text) {
        const rows = [[]];
        let cell = '', quoted = false;
        for (let i = 0; i < text.length; i++) {
            const ch = text[i];
            if (ch === '"' && (quoted || cell === '')) {
                if (quoted && text[i + 1] === '"') { cell += '"'; i++; }
                else quoted = !quoted;
            } else if (!quoted && (ch === '\t' || ch === '\n' || ch === '\r')) {
                rows[rows.length - 1].push(cell); cell = '';
                if (ch !== '\t') {
                    if (ch === '\r' && text[i + 1] === '\n') i++;
                    rows.push([]);
                }
            } else cell += ch;
        }
        rows[rows.length - 1].push(cell);
        if (rows.length > 1 && rows.at(-1).length === 1 && rows.at(-1)[0] === '') rows.pop();
        return rows;
    }
    body.addEventListener('paste', event => {
        if (!event.target.matches('input')) return;
        const text = event.clipboardData.getData('text/plain');
        if (!/[\t\r\n]/.test(text)) return;
        event.preventDefault();
        const cells = parseClipboard(text);
        const startRow = Array.from(body.rows).indexOf(event.target.closest('tr'));
        const startCol = Array.from(body.rows[startRow].querySelectorAll('input')).indexOf(event.target);
        const width = body.rows[startRow].querySelectorAll('input').length;
        if (startRow + cells.length > 100 || cells.some(row => startCol + row.length > width)) {
            status.textContent = 'Paste does not fit. Use at most 100 rows and match the visible column order. Nothing was pasted.';
            return;
        }
        while (body.rows.length < startRow + cells.length) addRow();
        cells.forEach((values, offset) => {
            const inputs = body.rows[startRow + offset].querySelectorAll('input');
            values.forEach((value, index) => {
                const cell = inputs[startCol + index];
                // Accept Excel's displayed US dates as well as ISO dates.
                if (cell.type === 'date') {
                    const match = value.trim().match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
                    if (match) value = `${match[3]}-${match[1].padStart(2, '0')}-${match[2].padStart(2, '0')}`;
                }
                cell.value = value;
                // A blank item pasted beside a serial should still be auto-filled.
                if (cell.name !== 'item_number' || value.trim()) {
                    cell.dispatchEvent(new Event('input', { bubbles: true }));
                }
            });
        });
        status.textContent = `Pasted ${cells.length} rows. Review the entries before saving.`;
    });
    form.addEventListener('submit', () => {
        document.getElementById('save-batch').disabled = true;
        status.textContent = 'Saving entries…';
    });
    window.addEventListener('pageshow', () => { document.getElementById('save-batch').disabled = false; });
})();
