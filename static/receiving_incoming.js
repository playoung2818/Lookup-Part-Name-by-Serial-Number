/* Independent, read-only incoming-form download. No active workspace required. */
(() => {
    const form = document.getElementById('incoming-form');
    if (!form) return;
    const button = document.getElementById('incoming-generate');
    const status = document.getElementById('incoming-status');
    let busy = false;
    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (busy) return;
        busy = true; button.disabled = true;
        status.className = 'small mt-3 mb-0';
        status.textContent = 'Reading receiving records and preparing the Word document…';
        try {
            const response = await fetch(form.action, {method: 'POST', credentials: 'same-origin', body: new FormData(form)});
            if (!response.ok) {
                let message = `Incoming form generation failed (HTTP ${response.status}). Reload the page if your session expired.`;
                try { message = (await response.json()).error || message; } catch (_) {}
                throw Error(message);
            }
            if (!response.headers.get('Content-Type')?.includes('application/vnd.openxmlformats-officedocument.wordprocessingml.document')) {
                throw Error('The server did not return a Word document. Reload the page and retry.');
            }
            const url = URL.createObjectURL(await response.blob());
            const link = document.createElement('a');
            const filename = /filename="?([^";]+)/i.exec(response.headers.get('Content-Disposition') || '');
            link.href = url; link.download = filename ? filename[1] : 'Incoming_form.docx';
            document.body.appendChild(link); link.click(); link.remove();
            setTimeout(() => URL.revokeObjectURL(url), 30000);
            const count = response.headers.get('X-Incoming-Lines');
            status.textContent = `Incoming form downloaded${count ? ` — ${count} product lines` : ''}. No receiving records were changed.`;
        } catch (error) {
            status.classList.add('entry-error'); status.textContent = error.message;
        } finally { busy = false; button.disabled = false; }
    });
})();
