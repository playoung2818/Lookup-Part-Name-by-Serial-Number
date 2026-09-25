const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function setup() {
    const elements = Object.fromEntries(['serial_number', 'item_number', 'item-lookup-status'].map(id => [id, {
        value: '', dataset: { lookupUrl: '/warehouse-borrow-log/lookup-item' },
        handlers: {}, addEventListener(name, fn) { this.handlers[name] = fn; }
    }]));
    const timers = new Map();
    const requests = [];
    let id = 0;
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/borrow_lookup.js'), 'utf8'), {
        document: { getElementById: id => elements[id] },
        window: { location: { origin: 'http://localhost' } }, URL, AbortController,
        setTimeout: (fn, ms) => { timers.set(++id, { fn, ms }); return id; },
        clearTimeout: id => timers.delete(id),
        fetch: url => new Promise(resolve => requests.push({ url, resolve }))
    });
    return {
        elements, requests,
        type(serial) {
            elements.serial_number.value = serial;
            elements.serial_number.handlers.input();
            for (const [id, timer] of timers) if (timer.ms === 300) { timers.delete(id); timer.fn(); }
        },
        async answer(index, result) {
            requests[index].resolve({ ok: true, json: async () => result });
            await new Promise(resolve => setImmediate(resolve));
        }
    };
}

test('fills an exact match and clears a stale item for a missing serial', async () => {
    const ui = setup();
    ui.type('Q1600095');
    await ui.answer(0, { found: true, item_name: 'NRU-161V-AWP' });
    assert.equal(ui.elements.item_number.value, 'NRU-161V-AWP');
    ui.type('MISSING');
    assert.equal(ui.elements.item_number.value, '');
    await ui.answer(1, { found: false, message: 'No matching item found.' });
    assert.equal(ui.elements['item-lookup-status'].textContent, 'No matching item found.');
});

test('a late response cannot replace a newer serial result', async () => {
    const ui = setup();
    ui.type('OLD');
    ui.type('NEW');
    await ui.answer(1, { found: true, item_name: 'New item' });
    await ui.answer(0, { found: true, item_name: 'Old item' });
    assert.equal(ui.elements.item_number.value, 'New item');
});

test('preserves manual input entered while a lookup is pending', async () => {
    const ui = setup();
    ui.type('Q1600095');
    ui.elements.item_number.value = 'Manual item';
    ui.elements.item_number.handlers.input();
    await ui.answer(0, { found: true, item_name: 'Database item' });
    assert.equal(ui.elements.item_number.value, 'Manual item');
});
