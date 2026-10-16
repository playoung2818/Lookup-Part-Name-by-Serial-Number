(() => {
  const input = document.getElementById('inventory-item');
  const list = document.getElementById('inventory-suggestions');
  if (!input || !list) return;
  let timer, controller, generation = 0;
  const hide = () => {
    list.hidden = true;
    list.replaceChildren();
    input.setAttribute('aria-expanded', 'false');
  };
  const show = items => {
    hide();
    for (const item of items) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'list-group-item list-group-item-action';
      button.setAttribute('role', 'option');
      button.textContent = item;
      button.addEventListener('click', () => { input.value = item; hide(); input.focus(); });
      button.addEventListener('keydown', event => {
        if (event.key === 'ArrowDown') { event.preventDefault(); (button.nextElementSibling || button).focus(); }
        if (event.key === 'ArrowUp') { event.preventDefault(); (button.previousElementSibling || input).focus(); }
        if (event.key === 'Escape') { hide(); input.focus(); }
      });
      list.append(button);
    }
    list.hidden = items.length === 0;
    input.setAttribute('aria-expanded', String(items.length > 0));
  };
  input.addEventListener('input', () => {
    clearTimeout(timer);
    controller?.abort();
    const current = ++generation;
    const query = input.value.trim();
    hide();
    if (!query) return;
    timer = setTimeout(async () => {
      controller = new AbortController();
      try {
        const response = await fetch(input.dataset.suggestUrl + '?q=' + encodeURIComponent(query), {signal:controller.signal});
        const data = await response.json();
        if (current !== generation || input.value.trim() !== query) return;
        if (response.ok && data.ok && Array.isArray(data.items)) show(data.items); else hide();
      } catch (error) { if (error.name !== 'AbortError' && current === generation) hide(); }
    }, 180);
  });
  input.addEventListener('keydown', event => {
    if (event.key === 'Escape') hide();
    if (event.key === 'ArrowDown' && !list.hidden) { event.preventDefault(); list.firstElementChild?.focus(); }
  });
  document.addEventListener('click', event => { if (event.target !== input && !list.contains(event.target)) hide(); });
})();
