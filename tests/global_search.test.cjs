const assert = require('node:assert/strict');
const {test} = require('node:test');
const {describe, remember, typingTarget} = require('../static/global_search.js');

test('destination hint mirrors the server /lookup routing', () => {
    for (const value of ['SO-20260295', 'so 20260295', '20260295', 'WO26-20260295', ' SO-20260295 ']) {
        assert.equal(describe(value).kind, 'so', value);
    }
    assert.match(describe('20260295').label, /SO-20260295/);
    assert.match(describe('Q0700370').label, /serial numbers, SO numbers and inventory items/);
    for (const value of ['Q0700370', '2026029', '202602951', 'SO-2026029X', 'DDR4-16GB', 'WO2-20260295']) {
        assert.equal(describe(value).kind, 'serial', value);
    }
    assert.equal(describe('   '), null);
    assert.equal(describe(''), null);
});

test('recent searches: newest first, case-insensitive de-duplication, max five', () => {
    let list = [];
    for (const value of ['A1', 'B2', 'a1', ' C3 ', '', 'D4', 'E5', 'F6']) list = remember(list, value);
    assert.deepEqual(list, ['F6', 'E5', 'D4', 'C3', 'a1']);
});

test('slash shortcut ignored while typing in fields', () => {
    assert.equal(typingTarget({tagName: 'INPUT'}), true);
    assert.equal(typingTarget({tagName: 'TEXTAREA'}), true);
    assert.equal(typingTarget({tagName: 'DIV', isContentEditable: true}), true);
    assert.equal(typingTarget({tagName: 'BODY'}), false);
    assert.equal(typingTarget(null), null);
});

test('item suggestions only for 2+ characters and never for SO numbers', () => {
    const {wantsSuggestions} = require('../static/global_search.js');
    assert.equal(wantsSuggestions('74'), true);
    assert.equal(wantsSuggestions(' Nuvo-9006 '), true);
    assert.equal(wantsSuggestions('7'), false);
    assert.equal(wantsSuggestions(''), false);
    assert.equal(wantsSuggestions('SO-20260295'), false);
    assert.equal(wantsSuggestions('20260295'), false);
});
