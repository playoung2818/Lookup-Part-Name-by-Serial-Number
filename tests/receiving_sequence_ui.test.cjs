const assert = require('node:assert/strict');
const {test} = require('node:test');
const {attach} = require('../static/receiving_serials.js');

const fixture = clipboard => {
    const ids = ['sequence-first', 'sequence-count', 'sequence-result', 'sequence-summary',
        'sequence-output', 'sequence-copy', 'serial-status', 'sequence-form'];
    const controls = new Map(ids.map(id => [id, {value: '', hidden: false, disabled: false,
        textContent: '', classList: {toggle() {}}, listeners: {}, focused: false, selected: false,
        addEventListener(type, callback) { this.listeners[type] = callback; },
        focus() { this.focused = true; }, select() { this.selected = true; }}]));
    const find = id => controls.get(id);
    attach({host: {querySelector: selector => find(selector.slice(1))}, clipboard});
    const generate = () => find('sequence-form').listeners.submit({preventDefault() {}});
    find('sequence-first').value = 'SC69031431'; find('sequence-count').value = '20';
    return {find, generate};
};

test('standalone generator needs no invoice or starting row', () => {
    const {find, generate} = fixture();
    generate();
    assert.equal(find('sequence-result').hidden, false);
    assert.equal(find('sequence-output').value.split('\n').length, 20);
    assert.match(find('sequence-summary').textContent, /SC69031431 → SC69031450/);
    assert.match(find('serial-status').textContent, /No database records were changed/);
});

test('copy uses generated column and input edits invalidate stale results', async () => {
    let copied;
    const {find, generate} = fixture({writeText: async text => {copied = text;}});
    generate();
    await find('sequence-copy').listeners.click();
    assert.equal(copied, find('sequence-output').value);
    find('sequence-first').listeners.input();
    assert.equal(find('sequence-result').hidden, true);
    assert.equal(find('sequence-output').value, '');
    assert.equal(find('sequence-copy').disabled, true);
});

test('HTTP clipboard fallback selects output for manual copy', async () => {
    const {find, generate} = fixture({writeText: async () => {throw Error('Not secure');}});
    generate();
    await find('sequence-copy').listeners.click();
    assert.equal(find('sequence-output').selected, true);
    assert.match(find('serial-status').textContent, /Ctrl\+C/);
});

test('invalid range leaves inputs usable and does not expose old results', () => {
    const {find, generate} = fixture();
    generate();
    find('sequence-count').value = '20001';
    generate();
    assert.equal(find('sequence-result').hidden, true);
    assert.equal(find('sequence-output').value, '');
    assert.equal(find('sequence-first').disabled, false);
    assert.match(find('serial-status').textContent, /20,000/);
});
