/* Receiving page chrome: New-shipment panel, tool dialogs, menus and theme switch. */
(() => {
    const root = document.documentElement;

    // Theme switch (Tools menu). The <head> script applies the saved theme before paint.
    for (const input of document.querySelectorAll('input[name="receiving-theme"]')) {
        input.checked = input.value === root.dataset.rt;
        input.addEventListener('change', () => {
            root.dataset.rt = input.value;
            try { localStorage.setItem('receivingTheme', input.value); } catch (e) {}
        });
    }

    // + New shipment toggles the upload panel (open automatically when nothing is loaded).
    const toggle = document.getElementById('new-shipment-toggle');
    const panel = document.getElementById('shipment-upload');
    const setPanel = open => {
        if (!panel) return;
        panel.hidden = !open;
        if (toggle) toggle.setAttribute('aria-expanded', String(open));
        if (open) { panel.scrollIntoView({block: 'nearest'}); panel.querySelector('input[type="file"]')?.focus(); }
    };
    if (toggle) toggle.addEventListener('click', () => setPanel(panel.hidden));
    for (const button of document.querySelectorAll('[data-close-panel]')) {
        button.addEventListener('click', () => { setPanel(false); toggle?.focus(); });
    }

    // Menus (<details class="rcv-menu">): close on outside click, Escape, or after choosing an item.
    const menus = [...document.querySelectorAll('details.rcv-menu')];
    const closeMenus = except => menus.forEach(menu => { if (menu !== except) menu.open = false; });
    document.addEventListener('click', event => {
        const menu = event.target.closest('details.rcv-menu');
        closeMenus(menu);
        if (menu && event.target.closest('.rcv-menu-list button')) menu.open = false;
    });
    document.addEventListener('keydown', event => {
        if (event.key !== 'Escape') return;
        const open = menus.find(menu => menu.open);
        if (open) { open.open = false; open.querySelector('summary').focus(); }
    });

    // Tool dialogs.
    for (const button of document.querySelectorAll('[data-open-dialog]')) {
        button.addEventListener('click', () => {
            const dialog = document.getElementById(button.dataset.openDialog);
            if (!dialog) return;
            if (dialog.showModal) dialog.showModal(); else dialog.setAttribute('open', '');
            dialog.querySelector('input:not([type="hidden"])')?.focus();
        });
    }
    for (const dialog of document.querySelectorAll('dialog.rcv-dialog')) {
        dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });  // backdrop
        for (const button of dialog.querySelectorAll('[data-close-dialog]')) button.addEventListener('click', () => dialog.close());
    }
})();
