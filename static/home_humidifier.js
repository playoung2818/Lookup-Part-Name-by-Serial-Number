/* Homepage "Humidifier" panel: SwitchBot Evaporative Humidifier status and controls.
   GET /api/humidifier (cached 60 s on the server); POST /api/humidifier with the
   X-Warehouse-Control header. Every command asks for confirmation first. */
((root) => {
    const MODES = {1: 'Level 4 (high)', 2: 'Level 3', 3: 'Level 2', 4: 'Level 1 (low)', 5: 'Target humidity', 6: 'Sleep', 7: 'Auto', 8: 'Drying'};
    const confirmText = (action, mode, target) => action === 'on' ? 'Turn the warehouse humidifier ON?'
        : action === 'off' ? 'Turn the warehouse humidifier OFF?'
        : mode === 5 ? `Set the humidifier to Target humidity ${target} %?` : `Set the humidifier to ${MODES[mode]} mode?`;
    const filterText = (used, life) => used == null || !life ? '--' : `${Math.max(0, life - used)} of ${life} h left`;
    if (typeof module !== 'undefined' && module.exports) module.exports = {confirmText, filterText, MODES};
    if (typeof document === 'undefined') return;
    const panel = document.getElementById('humidifier-panel');
    if (!panel) return;
    const $ = id => document.getElementById(id);
    const message = (text, error = false) => { $('hum-message').textContent = text; $('hum-message').classList.toggle('error', error); };
    const modeSelect = $('hum-mode'), target = $('hum-target');
    const syncTarget = () => { target.closest('.hum-target').hidden = modeSelect.value !== '5'; };
    let busy = false, modeTouched = false;

    const render = s => {
        $('hum-device').textContent = `SwitchBot ${s.device}`;
        const power = $('hum-power');
        power.textContent = s.power === 'on' ? 'ON' : s.power === 'off' ? 'OFF' : '?';
        power.className = `hum-power ${s.power}`;
        $('hum-mode-name').textContent = s.power === 'off' ? 'Switched off' : `${MODES[s.mode] || 'Unknown'} mode`;
        for (const button of panel.querySelectorAll('[data-hum-action="on"], [data-hum-action="off"]')) {
            button.disabled = busy || button.dataset.humAction === s.power;
        }
        if (!modeTouched && MODES[s.mode]) { modeSelect.value = String(s.mode); syncTarget(); }
    };
    const load = async (refresh = false) => {
        try {
            const response = await fetch(`/api/humidifier${refresh ? '?refresh=1' : ''}`, {cache: 'no-store'});
            const data = await response.json();
            if (!response.ok) throw Error(data.error || 'Humidifier status is unavailable.');
            render(data);
        } catch (error) {
            $('hum-power').textContent = '?'; $('hum-power').className = 'hum-power unknown';
            $('hum-mode-name').textContent = error.message;
        }
    };
    const send = async (action) => {
        const mode = Number(modeSelect.value), goal = Number(target.value);
        if (action === 'mode' && mode === 5 && !(Number.isInteger(goal) && goal >= 0 && goal <= 100)) {
            message('Target humidity must be a whole number from 0 to 100.', true); target.focus(); return;
        }
        if (busy || !window.confirm(confirmText(action, mode, goal))) return;
        busy = true;
        panel.querySelectorAll('[data-hum-action]').forEach(button => { button.disabled = true; });
        message('Sending to the humidifier…');
        try {
            const body = action === 'mode' ? {action, mode, ...(mode === 5 ? {target: goal} : {})} : {action};
            const response = await fetch('/api/humidifier', {method: 'POST', cache: 'no-store',
                headers: {'Content-Type': 'application/json', 'X-Warehouse-Control': 'humidifier'}, body: JSON.stringify(body)});
            const data = await response.json();
            if (!response.ok) throw Error(data.error || 'Command failed.');
            message('Done. The humidifier usually updates within a few seconds.');
            modeTouched = false;
            setTimeout(() => load(true), 4000);
        } catch (error) { message(error.message, true); }
        finally {
            busy = false;
            panel.querySelectorAll('[data-hum-action]').forEach(button => { button.disabled = false; });
            setTimeout(() => load(), 300);
        }
    };
    panel.querySelectorAll('[data-hum-action]').forEach(button => button.addEventListener('click', () => send(button.dataset.humAction)));
    modeSelect.addEventListener('change', () => { modeTouched = true; syncTarget(); });
    target.addEventListener('input', () => { modeTouched = true; });
    $('hum-refresh').addEventListener('click', () => load(true));
    syncTarget();
    load();
    setInterval(load, 60000);
})(globalThis);
