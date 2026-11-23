/* Homepage "Warehouse humidity" panel: latest Hub 2 reading and an SVG humidity chart.
   Data: GET /api/climate?range=24h|7d|30d (recorded every 5 minutes by the web app). */
((root) => {
    const W = 900, H = 260, PAD = {l: 38, r: 10, t: 10, b: 26};
    const x0 = PAD.l, x1 = W - PAD.r, y0 = H - PAD.b, y1 = PAD.t;
    const yOf = value => y0 - (value / 100) * (y0 - y1);

    const status = (latest, okMin, okMax, staleSeconds = 900) => {
        if (!latest) return {cls: 'stale', text: 'No readings yet'};
        if (latest.age_seconds > staleSeconds) return {cls: 'stale', text: `No new reading for ${ago(latest.age_seconds)}`};
        if (latest.humidity < okMin) return {cls: 'bad', text: `Too dry: below ${okMin} %`};
        if (latest.humidity > okMax) return {cls: 'bad', text: `Too humid: above ${okMax} %`};
        return {cls: 'ok', text: 'Within OK range'};
    };
    const ago = seconds => seconds < 90 ? 'just now' : seconds < 5400 ? `${Math.round(seconds / 60)} min ago`
        : seconds < 172800 ? `${Math.round(seconds / 3600)} h ago` : `${Math.round(seconds / 86400)} days ago`;

    // Builds the chart as an SVG string (exported for tests).
    const chartSvg = (points, okMin, okMax, range) => {
        const parts = [];
        parts.push(`<rect class="band" x="${x0}" y="${yOf(okMax)}" width="${x1 - x0}" height="${yOf(okMin) - yOf(okMax)}"/>`);
        for (const v of [0, 20, 40, 60, 80, 100]) {
            parts.push(`<line class="grid${v === okMin || v === okMax ? ' limit' : ''}" x1="${x0}" x2="${x1}" y1="${yOf(v)}" y2="${yOf(v)}"/>`);
            parts.push(`<text class="axis" x="${x0 - 6}" y="${yOf(v) + 4}" text-anchor="end">${v}</text>`);
        }
        if (!points.length) {
            parts.push(`<text class="empty" x="${(x0 + x1) / 2}" y="${H / 2}" text-anchor="middle">No readings in this period yet</text>`);
            return {svg: parts.join(''), xs: []};
        }
        const times = points.map(p => Date.parse(p.t));
        const spanMs = {'24h': 864e5, '7d': 6048e5, '30d': 2592e6}[range] || 864e5;
        const end = Math.max(Date.now(), times[times.length - 1]), start = end - spanMs;
        const xOf = t => x0 + ((t - start) / spanMs) * (x1 - x0);
        // Time labels: 6 evenly spaced ticks.
        for (let i = 0; i <= 5; i++) {
            const t = start + (spanMs * i) / 5, d = new Date(t);
            const label = range === '24h' ? d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})
                : d.toLocaleDateString([], {month: 'short', day: 'numeric'});
            parts.push(`<text class="axis" x="${xOf(t)}" y="${H - 6}" text-anchor="${i === 0 ? 'start' : i === 5 ? 'end' : 'middle'}">${label}</text>`);
        }
        // Break the line where readings are missing for more than 3 expected intervals.
        const gap = {'24h': 15 * 60e3, '7d': 90 * 60e3, '30d': 9 * 3600e3}[range] || 15 * 60e3;
        let d = '';
        points.forEach((p, i) => {
            const cmd = i === 0 || times[i] - times[i - 1] > gap ? 'M' : 'L';
            d += `${cmd}${xOf(times[i]).toFixed(1)},${yOf(p.humidity).toFixed(1)}`;
        });
        parts.push(`<path class="line" d="${d}"/>`);
        points.forEach((p, i) => {
            if (p.humidity < okMin || p.humidity > okMax) {
                parts.push(`<circle class="out" cx="${xOf(times[i]).toFixed(1)}" cy="${yOf(p.humidity).toFixed(1)}" r="2.5"/>`);
            }
        });
        parts.push(`<line class="cursor" x1="0" x2="0" y1="${y1}" y2="${y0}" visibility="hidden"/>`);
        return {svg: parts.join(''), xs: times.map(xOf)};
    };

    if (typeof module !== 'undefined' && module.exports) module.exports = {status, chartSvg, ago};
    if (typeof document === 'undefined') return;
    const panel = document.getElementById('climate-panel');
    if (!panel) return;
    const okMin = Number(panel.dataset.okMin), okMax = Number(panel.dataset.okMax);
    const $ = id => document.getElementById(id);
    const svg = $('climate-svg'), tip = $('climate-tip');
    let range = '24h', current = {points: [], xs: []};

    const render = data => {
        const latest = data.latest, state = status(latest, okMin, okMax);
        $('climate-humidity').textContent = latest ? latest.humidity : '--';
        $('climate-temp').textContent = latest && latest.temperature != null ? `${latest.temperature.toFixed(1)} °C` : '--';
        $('climate-updated').textContent = latest ? ago(latest.age_seconds) : '--';
        $('climate-updated').title = latest ? new Date(latest.t).toLocaleString() : '';
        if (latest && latest.device) $('climate-source').textContent = `SwitchBot ${latest.device}`;
        const box = $('climate-status');
        box.textContent = state.text; box.className = `climate-status ${state.cls}`;
        panel.dataset.state = state.cls;
        const chart = chartSvg(data.points, okMin, okMax, data.range);
        svg.innerHTML = chart.svg;
        current = {points: data.points, xs: chart.xs};
        const values = data.points.map(p => p.humidity);
        $('climate-caption').textContent = values.length
            ? `Humidity over the last ${data.range}: ${Math.min(...values)}–${Math.max(...values)} % RH; OK range ${okMin}–${okMax} %.`
            : 'No humidity readings in this period yet.';
    };
    // Humidifier power (read-only). The server asks SwitchBot at most once a minute.
    const loadHumidifier = async (fresh = false) => {
        const label = $('climate-hum-power');
        if (!label) return;
        try {
            const response = await fetch(`/api/humidifier${fresh ? '?refresh=1' : ''}`, {cache: 'no-store'});
            const data = await response.json();
            if (!response.ok) throw Error();
            const power = data.power === 'on' || data.power === 'off' ? data.power : 'unknown';
            label.textContent = power === 'unknown' ? 'Unknown' : power.toUpperCase();
            label.className = `hum-state ${power}`;
            label.title = power === 'on' ? `${data.mode_name} mode` : '';
        } catch (_) {
            label.textContent = 'Unavailable'; label.className = 'hum-state unknown';
        }
    };
    const load = async (fresh = false) => {
        const humidifier = loadHumidifier(fresh);
        try {
            const response = await fetch(`/api/climate?range=${range}${fresh ? '&refresh=1' : ''}`, {cache: 'no-store'});
            if (!response.ok) throw Error();
            render(await response.json());
        } catch (_) {
            const box = $('climate-status');
            box.textContent = 'Humidity data is unavailable right now.'; box.className = 'climate-status stale';
        }
        await humidifier;
    };
    // Refresh: fresh Hub 2 reading + humidifier status (the server allows one fresh reading per minute).
    const refreshButton = $('climate-refresh');
    refreshButton.addEventListener('click', async () => {
        refreshButton.disabled = true; refreshButton.textContent = 'Refreshing…';
        try { await load(true); } finally { refreshButton.disabled = false; refreshButton.textContent = 'Refresh'; }
    });
    for (const button of panel.querySelectorAll('[data-range]')) {
        button.addEventListener('click', () => {
            range = button.dataset.range;
            for (const other of panel.querySelectorAll('[data-range]')) other.setAttribute('aria-pressed', String(other === button));
            load();
        });
    }
    // Hover: nearest reading.
    svg.addEventListener('pointermove', event => {
        if (!current.xs.length) return;
        const rect = svg.getBoundingClientRect(), x = ((event.clientX - rect.left) / rect.width) * W;
        let best = 0;
        current.xs.forEach((value, i) => { if (Math.abs(value - x) < Math.abs(current.xs[best] - x)) best = i; });
        const point = current.points[best], cursor = svg.querySelector('.cursor');
        cursor.setAttribute('x1', current.xs[best]); cursor.setAttribute('x2', current.xs[best]); cursor.setAttribute('visibility', 'visible');
        tip.hidden = false;
        tip.textContent = `${point.humidity} % RH${point.temperature != null ? ` · ${point.temperature} °C` : ''} · ${new Date(point.t).toLocaleString([], {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'})}`;
        tip.style.left = `${Math.min(rect.width - 10, Math.max(10, (current.xs[best] / W) * rect.width))}px`;
    });
    svg.addEventListener('pointerleave', () => { tip.hidden = true; svg.querySelector('.cursor')?.setAttribute('visibility', 'hidden'); });
    load();
    setInterval(load, 60000);
})(globalThis);
