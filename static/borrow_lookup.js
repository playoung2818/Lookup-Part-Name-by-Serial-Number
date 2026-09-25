(() => {
    function attachLookup(serial, item, status) {
    if (!serial || !item || !status) return;

    let timer;
    let controller;
    let revision = 0;
    let manualRevision = 0;
    item.addEventListener('input', () => { manualRevision += 1; });

    serial.addEventListener('input', () => {
        clearTimeout(timer);
        if (controller) controller.abort();
        const currentRevision = ++revision;
        const currentManualRevision = manualRevision;
        const value = serial.value.trim();
        // A different serial must not retain the previous serial's item.
        item.value = '';
        if (!value || /^(?:NA|N\/A|NONE)$/i.test(value)) {
            status.textContent = 'Enter the item name manually for items without a serial number.';
            return;
        }
        status.textContent = 'Looking up item…';
        timer = setTimeout(async () => {
            const requestController = new AbortController();
            controller = requestController;
            const timeout = setTimeout(() => requestController.abort(), 8000);
            try {
                const url = new URL(serial.dataset.lookupUrl, window.location.origin);
                url.searchParams.set('serial_number', value);
                const response = await fetch(url, { signal: requestController.signal, cache: 'no-store' });
                const result = await response.json();
                if (currentRevision !== revision) return;
                if (response.ok && result.found) {
                    if (manualRevision === currentManualRevision) {
                        item.value = result.item_name;
                        status.textContent = 'Item found in the receiving log. You can edit it if needed.';
                    } else {
                        status.textContent = `Receiving log item: ${result.item_name}. Your manual entry was kept.`;
                    }
                } else {
                    status.textContent = result.message || 'Lookup is unavailable. Enter the item name manually.';
                }
            } catch (error) {
                if (currentRevision === revision) {
                    status.textContent = 'Lookup is unavailable. You can enter the item name manually.';
                }
            } finally {
                clearTimeout(timeout);
            }
        }, 300);
    });
    }
    window.attachBorrowLookup = attachLookup;
    attachLookup(document.getElementById('serial_number'), document.getElementById('item_number'),
                 document.getElementById('item-lookup-status'));
})();
