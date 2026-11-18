/* One search box: SO / serial / item. Destination hint, item suggestions,
   "/" shortcut and recent searches. Enter always searches exactly what was typed
   (scanner-safe); a suggestion is used only when picked with arrows or the mouse. */
((root) => {
    // Mirrors routes/Index_Routes.py ORDER_PATTERN: 8 digits, optionally SO- or WOnn- prefixed.
    const ORDER = /^(?:(?:SO\s*-?\s*)|(?:WO\d{2}\s*-\s*))?(\d{8})$/i;
    const KEY = 'warehouse.recentSearches', MAX_RECENT = 5, MAX_SUGGESTIONS = 8;
    const describe = raw => {
        const value = (raw || '').trim();
        if (!value) return null;
        const order = ORDER.exec(value);
        return order ? {kind: 'so', label: `SO number SO-${order[1]} — press Enter for results`}
                     : {kind: 'serial', label: 'Press Enter to search serial numbers, SO numbers and inventory items'};
    };
    const remember = (list, value) => {
        value = (value || '').trim();
        if (!value) return list;
        return [value, ...list.filter(item => item.toUpperCase() !== value.toUpperCase())].slice(0, MAX_RECENT);
    };
    const typingTarget = element => element && (element.isContentEditable ||
        ['INPUT', 'TEXTAREA', 'SELECT'].includes(element.tagName));
    const wantsSuggestions = raw => {
        const value = (raw || '').trim();
        return value.length >= 2 && !ORDER.test(value);
    };
    if (typeof module !== 'undefined' && module.exports) module.exports = {describe, remember, typingTarget, wantsSuggestions};
    if (typeof document === 'undefined') return;

    const form = document.querySelector('.global-search');
    if (!form) return;
    const input = form.querySelector('#global-search-input');
    const status = form.querySelector('#global-search-status');
    const list = form.querySelector('#global-search-suggestions');
    const recentBox = form.querySelector('.global-search-recent');
    const recentItems = form.querySelector('.recent-items');
    const defaultStatus = status.textContent;
    const inventoryUrl = input.dataset.suggestUrl.replace(/\/item-suggest$/, '');
    let timer, controller, generation = 0, active = -1;

    const load = () => {
        try { const items = JSON.parse(localStorage.getItem(KEY) || '[]'); return Array.isArray(items) ? items.filter(v => typeof v === 'string').slice(0, MAX_RECENT) : []; }
        catch (_) { return []; }
    };
    const save = items => { try { localStorage.setItem(KEY, JSON.stringify(items)); } catch (_) { /* storage unavailable */ } };
    const lookupUrl = value => `${form.getAttribute('action')}?q=${encodeURIComponent(value)}`;
    const renderRecent = () => {
        const items = load();
        recentItems.replaceChildren(...items.map(value => {
            const link = document.createElement('a');
            link.href = lookupUrl(value); link.textContent = value; link.className = 'recent-chip';
            link.addEventListener('click', () => save(remember(load(), value)));
            return link;
        }));
        recentBox.hidden = !items.length;
    };
    const updateStatus = () => {
        const info = describe(input.value);
        status.textContent = info ? info.label : defaultStatus;
        form.dataset.kind = info ? info.kind : '';
    };

    const options = () => [...list.querySelectorAll('[role="option"]')];
    const highlight = index => {
        const items = options();
        active = items.length ? (index + items.length) % items.length : -1;
        items.forEach((item, i) => item.setAttribute('aria-selected', String(i === active)));
        if (active >= 0) input.setAttribute('aria-activedescendant', items[active].id);
        else input.removeAttribute('aria-activedescendant');
    };
    const hide = () => {
        list.hidden = true; list.replaceChildren(); active = -1;
        input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant');
    };
    const openItem = item => {
        save(remember(load(), item));
        root.location.href = `${inventoryUrl}?item=${encodeURIComponent(item)}`;
    };
    const show = items => {
        hide();
        if (!items.length) return;
        const heading = document.createElement('div');
        heading.className = 'suggestions-heading'; heading.textContent = 'Inventory items';
        list.append(heading);
        items.slice(0, MAX_SUGGESTIONS).forEach((item, index) => {
            const option = document.createElement('div');
            option.id = `global-search-option-${index}`;
            option.className = 'suggestion'; option.setAttribute('role', 'option');
            option.setAttribute('aria-selected', 'false'); option.textContent = item;
            // mousedown keeps focus in the input; click opens the item.
            option.addEventListener('mousedown', event => event.preventDefault());
            option.addEventListener('click', () => openItem(item));
            list.append(option);
        });
        list.hidden = false; input.setAttribute('aria-expanded', 'true');
    };
    const suggest = () => {
        clearTimeout(timer); controller?.abort();
        const current = ++generation, query = input.value.trim();
        if (!wantsSuggestions(query)) { hide(); return; }
        timer = setTimeout(async () => {
            controller = new AbortController();
            try {
                const response = await fetch(`${input.dataset.suggestUrl}?q=${encodeURIComponent(query)}`, {signal: controller.signal});
                const data = await response.json();
                if (current !== generation || input.value.trim() !== query || document.activeElement !== input) return;
                if (response.ok && data.ok && Array.isArray(data.items)) show(data.items.filter(i => typeof i === 'string')); else hide();
            } catch (error) { if (error.name !== 'AbortError' && current === generation) hide(); }
        }, 200);
    };

    input.addEventListener('input', () => { updateStatus(); suggest(); });
    input.addEventListener('keydown', event => {
        if (event.key === 'ArrowDown' && !list.hidden) { event.preventDefault(); highlight(active + 1); }
        else if (event.key === 'ArrowUp' && !list.hidden) { event.preventDefault(); highlight(active - 1); }
        else if (event.key === 'Escape') hide();
        else if (event.key === 'Enter' && active >= 0) { event.preventDefault(); openItem(options()[active].textContent); }
    });
    input.addEventListener('blur', () => setTimeout(hide, 150));
    form.addEventListener('submit', () => { clearTimeout(timer); generation++; hide(); save(remember(load(), input.value)); });
    form.querySelector('.recent-clear').addEventListener('click', () => { save([]); renderRecent(); input.focus(); });
    document.addEventListener('keydown', event => {
        if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey || typingTarget(event.target)) return;
        event.preventDefault(); input.focus(); input.select();
    });
    // Ready for the next scan on search pages; other pages keep their own focus.
    if (input.hasAttribute('data-autofocus') && !typingTarget(document.activeElement)) { input.focus(); input.select(); }
    updateStatus(); renderRecent();
})(globalThis);
