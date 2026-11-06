/* Spreadsheet selection/paste shared by draft and serial-only entry grids. */
((root) => {
    const parseTSV = text => {
        if (typeof text !== 'string' || text.length > 5_000_000) throw Error('Clipboard data is too large.');
        const rows = [], row = [];
        let value = '', quoted = false, closed = false;
        const cell = () => { row.push(value); value = ''; closed = false; };
        const line = () => { cell(); rows.push(row.splice(0)); };
        for (let i = 0; i < text.length; i++) {
            const char = text[i];
            if (quoted) {
                if (char === '"') {
                    if (text[i + 1] === '"') { value += '"'; i++; }
                    else { quoted = false; closed = true; }
                } else value += char;
            } else if (char === '\t') cell();
            else if (char === '\r' || char === '\n') {
                if (char === '\r' && text[i + 1] === '\n') i++;
                line();
            } else if (char === '"' && !value && !closed) quoted = true;
            else {
                if (closed) throw Error('Invalid quoted clipboard cell.');
                value += char;
            }
        }
        if (quoted) throw Error('Unclosed quoted clipboard cell.');
        // Excel appends a line break; do not create an extra destination row.
        if (value || row.length || !rows.length || !/[\r\n]$/.test(text)) line();
        if (!rows.length || !rows[0].length || rows.length > 20000 || rows.some(r => r.length !== rows[0].length)) {
            throw Error('Paste a rectangular block of Excel cells (at most 20,000 rows).');
        }
        return rows;
    };
    const planPaste = (matrix, selection, height, width) => {
        const top = Math.min(selection.anchor.r, selection.end.r), left = Math.min(selection.anchor.c, selection.end.c);
        const selectedHeight = Math.abs(selection.end.r - selection.anchor.r) + 1;
        const selectedWidth = Math.abs(selection.end.c - selection.anchor.c) + 1;
        const singleTarget = selectedHeight === 1 && selectedWidth === 1;
        const fill = matrix.length === 1 && matrix[0].length === 1 && !singleTarget;
        if (!singleTarget && !fill && (matrix.length !== selectedHeight || matrix[0].length !== selectedWidth)) {
            throw Error('Copied cells must match the selected range, or click one starting cell before pasting.');
        }
        const h = fill ? selectedHeight : matrix.length, w = fill ? selectedWidth : matrix[0].length;
        if (top + h > height || left + w > width) throw Error('Not enough editable rows or columns. Nothing was pasted.');
        const edits = [];
        for (let r = 0; r < h; r++) for (let c = 0; c < w; c++) {
            edits.push({r: top + r, c: left + c, value: fill ? matrix[0][0] : matrix[r][c]});
        }
        return edits;
    };
    const attach = ({table, getRows, onMessage, validate}) => {
        let selection = null, dragging = false;
        const locate = target => {
            const td = target.closest('td');
            if (!td || !table.contains(td)) return null;
            const rows = getRows();
            for (let r = 0; r < rows.length; r++) {
                const c = rows[r].findIndex(cell => cell === td);
                if (c >= 0) return {r, c};
            }
            return null;
        };
        const paint = () => {
            table.querySelectorAll('.grid-selected').forEach(cell => cell.classList.remove('grid-selected'));
            if (!selection) return;
            const rows = getRows();
            const top = Math.min(selection.anchor.r, selection.end.r), bottom = Math.max(selection.anchor.r, selection.end.r);
            const left = Math.min(selection.anchor.c, selection.end.c), right = Math.max(selection.anchor.c, selection.end.c);
            for (let r = top; r <= bottom; r++) for (let c = left; c <= right; c++) rows[r]?.[c]?.classList.add('grid-selected');
        };
        table.addEventListener('pointerdown', event => {
            if (event.button !== 0) return;
            const position = locate(event.target);
            if (!position) return;
            if (event.shiftKey && selection) { selection.end = position; event.preventDefault(); }
            else selection = {anchor: position, end: position};
            dragging = true; paint();
        });
        table.addEventListener('pointerover', event => {
            if (!dragging || !(event.buttons & 1)) return;
            const position = locate(event.target);
            if (position) { selection.end = position; paint(); }
        });
        table.addEventListener('selectstart', event => {
            if (dragging && selection && (selection.anchor.r !== selection.end.r || selection.anchor.c !== selection.end.c)) event.preventDefault();
        });
        root.addEventListener('pointerup', () => { dragging = false; });
        table.addEventListener('focusin', event => {
            const position = locate(event.target);
            if (position && !dragging) { selection = {anchor: position, end: position}; paint(); }
        });
        table.addEventListener('keydown', event => {
            const position = locate(event.target);
            if (!position) return;
            if (event.key === 'Escape') { selection = null; paint(); return; }
            if (!event.shiftKey || !['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(event.key)) return;
            event.preventDefault(); event.stopImmediatePropagation();
            if (!selection) selection = {anchor: position, end: position};
            const rows = getRows(), end = {...selection.end};
            end.r = Math.max(0, Math.min(rows.length - 1, end.r + (event.key === 'ArrowDown' ? 1 : event.key === 'ArrowUp' ? -1 : 0)));
            end.c = Math.max(0, Math.min(rows[0].length - 1, end.c + (event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0)));
            selection.end = end; paint(); rows[end.r][end.c].scrollIntoView({block: 'nearest', inline: 'nearest'});
        }, true);
        table.addEventListener('paste', event => {
            const position = locate(event.target);
            if (!position) return;
            event.preventDefault(); event.stopImmediatePropagation();
            try {
                const rows = getRows();
                const matrix = parseTSV(event.clipboardData.getData('text/plain'));
                const edits = planPaste(matrix, selection || {anchor: position, end: position}, rows.length, rows[0].length);
                // Validate every destination BEFORE touching any cell or dispatching autosaves.
                const prepared = edits.map(edit => {
                    const input = rows[edit.r][edit.c].querySelector('input');
                    if (!input || input.disabled || input.readOnly) throw Error('Paste includes a locked column. INV# and saved non-SN fields cannot be changed.');
                    const value = validate(input, edit.value);
                    return {input, value};
                });
                for (const {input, value} of prepared) input.value = value;
                for (const {input} of prepared) input.dispatchEvent(new Event('input', {bubbles: true}));
                selection = {anchor: {r: edits[0].r, c: edits[0].c}, end: {r: edits.at(-1).r, c: edits.at(-1).c}};
                paint(); onMessage(`${prepared.length} cells pasted. ${table.id === 'template-table' ? 'Review and save draft changes.' : 'Serial numbers are saving individually.'}`);
            } catch (error) { onMessage(error.message, true); }
        }, true);
        return {clear: () => { selection = null; paint(); }};
    };
    const validateValue = (input, raw) => {
        const value = raw.trim();
        const max = input.maxLength > 0 ? input.maxLength : 255;
        if (value.length > max || /[\r\n\t]/.test(value) || value.startsWith('=') || value.toUpperCase() === 'NAN') {
            throw Error(`Paste contains an invalid value (maximum ${max} characters; no formulas, multiline values or NAN). Nothing was pasted.`);
        }
        if (input.type === 'date') {
            if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(Date.parse(value + 'T00:00:00Z')) || new Date(value + 'T00:00:00Z').toISOString().slice(0, 10) !== value) {
                throw Error('Paste dates as YYYY-MM-DD. Nothing was pasted.');
            }
        }
        if (input.type === 'number' && (!value || !Number.isFinite(Number(value)) || Number(value) <= 0)) {
            throw Error('Quantities must be positive numbers. Nothing was pasted.');
        }
        if (input.dataset.field === 'part_number' && !value) throw Error('Part# cannot be blank. Nothing was pasted.');
        return value;
    };
    root.ReceivingGrid = {parseTSV, planPaste, attach, validateValue};
    if (typeof module !== 'undefined' && module.exports) module.exports = root.ReceivingGrid;
})(globalThis);
