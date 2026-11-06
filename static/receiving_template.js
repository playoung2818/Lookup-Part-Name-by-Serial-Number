(() => {
    const host = document.getElementById('receiving-template');
    if (!host) return;
    let state = JSON.parse(document.getElementById('template-state').textContent);
    let dirty = false, busy = false, pendingCommit = false;
    const message = document.getElementById('template-message');
    const buttons = [...host.querySelectorAll('button')];
    const inputs = [...host.querySelectorAll('input')];
    const updateForms = () => {
        for (const id of ['shipment-upload-form', 'invoice-search-form']) {
            const form = document.getElementById(id);
            form.elements.workspace_id.value = state.id;
            form.elements.revision.value = state.revision;
        }
    };
    const post = async (url, data) => {
        const response = await fetch(url, {method: 'POST', headers: {
            'Content-Type': 'application/json', 'X-CSRF-Token': host.dataset.csrf
        }, body: JSON.stringify({workspace_id: state.id, ...data})});
        const result = await response.json();
        if (!response.ok) throw Error(result.error || 'Save failed. Retry safely.');
        return result.workspace;
    };
    inputs.forEach(input => input.addEventListener('input', () => { dirty = true; }));
    ReceivingGrid.attach({
        table: document.getElementById('template-table'),
        getRows: () => [...document.querySelectorAll('#template-table tbody tr')].map(tr => [...tr.cells].slice(1)),
        validate: ReceivingGrid.validateValue,
        onMessage: (text, error = false) => {
            message.textContent = text;
            message.classList.toggle('text-danger', error);
        }
    });
    const save = async commit => {
        if (busy) return;
        if (commit && !pendingCommit && !window.confirm('Save this reviewed template to the database and finish? After this, only serial numbers can be edited.')) return;
        if (!pendingCommit && inputs.some(input => !input.checkValidity())) {
            inputs.find(input => !input.checkValidity()).reportValidity(); return;
        }
        busy = true; buttons.forEach(button => { button.disabled = true; });
        inputs.forEach(input => { input.disabled = true; });
        try {
            if (!pendingCommit) {
                const rows = [...document.querySelectorAll('#template-table tbody tr')].map(tr => {
                    const row = {row_id: tr.dataset.rowId};
                    tr.querySelectorAll('[data-field]').forEach(input => { row[input.dataset.field] = input.value; });
                    return row;
                });
                state = await post('/receiving/template', {revision: state.revision, rows});
                dirty = false; updateForms();
            }
            if (commit) {
                pendingCommit = true;
                await post('/receiving/save', {revision: state.revision});
                pendingCommit = false; busy = false; location.reload();
            } else message.textContent = 'Draft changes saved. No database records written.';
        } catch (error) {
            message.textContent = error.message + (pendingCommit ? ' Reload to check database status, or retry Save template to database. Do not regenerate.' : '');
        } finally {
            busy = false;
            buttons.forEach(button => { button.disabled = pendingCommit && button.id !== 'commit-template'; });
            inputs.forEach(input => { input.disabled = pendingCommit; });
        }
    };
    document.getElementById('save-template-draft').addEventListener('click', () => save(false));
    document.getElementById('commit-template').addEventListener('click', () => save(true));
    window.addEventListener('beforeunload', event => {
        if (dirty || busy) { event.preventDefault(); event.returnValue = ''; }
    });
    for (const id of ['shipment-upload-form', 'invoice-search-form']) {
        document.getElementById(id).addEventListener('submit', event => {
            if (busy || pendingCommit || ((dirty || state.mode === 'draft') && !window.confirm('Leave this draft and switch transactions? Save draft changes first if needed.'))) event.preventDefault();
        });
    }
})();
