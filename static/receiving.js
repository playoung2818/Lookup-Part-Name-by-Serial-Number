(() => {
    const groups = [...document.querySelectorAll('.serial-group')];
    if (!groups.length) return;
    const normalize = (cell) => {
        let value = cell.textContent.trim();
        if (cell.dataset.field === 'serial_number') value = value.toUpperCase();
        if (cell.dataset.field === 'quantity' && value !== '' && Number.isFinite(Number(value))) value = String(Number(value));
        return value;
    };
    for (const group of groups) {
        const rows = [...group.querySelectorAll('tbody tr')];
        const baseline = rows[0];
        for (const row of rows.slice(1)) {
            for (const cell of row.querySelectorAll('[data-field]')) {
                const original = baseline.querySelector(`[data-field="${cell.dataset.field}"]`);
                if (original && normalize(cell) !== normalize(original)) {
                    cell.classList.add('diff-changed');
                    cell.title = `First version: ${original.textContent.trim() || '(blank)'}`;
                }
            }
        }
    }
    const refresh = () => {
        let inserts = 0, updates = 0, deletes = 0, untouched = 0;
        for (const group of groups) {
            const selected = group.querySelector('input[type=radio]:checked');
            const choice = selected ? selected.value : 'skip';
            const dbRows = [...group.querySelectorAll('tr[data-source=db]')];
            const uploadSelected = choice.startsWith('upload:');
            const historySelected = choice === 'history';
            const status = group.querySelector('.choice-status');
            if (choice === 'skip') {
                untouched++;
                status.textContent = 'Unchanged';
            } else if (historySelected) {
                inserts += group.querySelectorAll('tr[data-source=upload][data-history-new=yes]').length;
                status.textContent = 'Keep all history / add distinct events';
            } else if (uploadSelected) {
                if (dbRows.length) updates++; else inserts++;
                status.textContent = dbRows.length ? 'Update from Excel' : 'Insert from Excel';
            } else {
                status.textContent = 'Keep database version';
            }
            for (const row of group.querySelectorAll('tbody tr')) {
                const input = row.querySelector('input');
                let effect = 'NOT IMPORTED';
                if (row.dataset.source === 'db') {
                    const survivor = choice === input.value || (uploadSelected && row === dbRows[0]);
                    effect = choice === 'skip' ? 'UNCHANGED' : historySelected ? 'KEEP HISTORY' : survivor ? (uploadSelected ? 'UPDATE / KEEP ID' : 'KEEP') : 'DELETE';
                    if (effect === 'DELETE') deletes++;
                } else if (historySelected) {
                    effect = row.dataset.historyNew === 'yes' ? 'INSERT NEW EVENT' : 'ALREADY RECORDED — SKIP';
                } else if (input.checked) {
                    effect = dbRows.length ? 'USE FOR UPDATE' : 'INSERT';
                }
                row.classList.toggle('will-delete', effect === 'DELETE');
                row.classList.toggle('will-keep', input.checked || (historySelected && (row.dataset.source === 'db' || row.dataset.historyNew === 'yes')));
                row.querySelector('.row-effect').textContent = effect;
            }
        }
        const summary = document.getElementById('change-summary');
        if (summary) summary.textContent = `Selected: ${inserts} insert(s), ${updates} update(s), ${deletes} database row deletion(s); ${untouched} serial group(s) unchanged.`;
        const checkbox = document.querySelector('[name=allow_delete]');
        if (checkbox) checkbox.required = deletes > 0;
        document.getElementById('review-count').textContent = `${groups.filter(g => !g.hidden).length} of ${groups.length} serial groups shown`;
    };
    document.getElementById('review-form').addEventListener('change', refresh);
    document.getElementById('review-search').addEventListener('input', (event) => {
        const query = event.target.value.trim().toUpperCase();
        for (const group of groups) group.hidden = !group.dataset.serial.includes(query);
        refresh();
    });
    document.getElementById('expand-review').addEventListener('click', () => {
        for (const group of groups) if (!group.hidden) group.open = true;
    });
    document.getElementById('collapse-review').addEventListener('click', () => {
        for (const group of groups) group.open = false;
    });
    document.getElementById('skip-review').addEventListener('click', () => {
        for (const group of groups) group.querySelector('input[value=skip]').checked = true;
        refresh();
    });
    refresh();
})();
