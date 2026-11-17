const assert = require('node:assert/strict');
const {sequence, groups, groupKey, plan, validateSerial} = require('../static/receiving_serials.js');
assert.deepEqual(sequence(' ABC000127 ', 4), ['ABC000127', 'ABC000128', 'ABC000129', 'ABC000130']);
assert.deepEqual(sequence('000009', 2), ['000009', '000010']);
assert.deepEqual(sequence('X9007199254740992', 2), ['X9007199254740992', 'X9007199254740993']);
assert.deepEqual(sequence('ABC99', 1), ['ABC99']);
assert.throws(() => sequence('ABC99', 2), /numeric width/);
assert.throws(() => sequence('ABC123X', 2), /end with digits/);
for (const count of [0, -1, 1.5, 20001, '', 'bad', Infinity]) assert.throws(() => sequence('ABC001', count), /Quantity/);
for (const serial of ['', 'NA', 'NAN', '=BAD()', 'A\nB', 'A\tB', 'X'.repeat(256), null]) assert.throws(() => validateSerial(serial));
const row = (id, sn = '', extra = {}) => ({row_id: String(id), db_id: id, row_version: `version-${id}`, serial_number: sn,
    box_number: 'BOX1', pod_number: 'POD1', part_number: 'MODEL1', quantity: 1, ...extra});
const state = {id: 'workspace', rows: [row(3), row(1, 'IMPORTED'), row(2), row(4, '', {quantity: 3}), row(5, '', {box_number: 'BOX2'})]};
const key = groupKey(state.rows[0]);
assert.equal(groups(state.rows).length, 2);
assert.deepEqual(groups(state.rows)[0].rows.map(row => row.db_id), [1, 2, 3]);
const payload = plan(state, key, sequence('ABC001', 2));
assert.deepEqual(payload, {workspace_id: 'workspace', group: {box_number: 'BOX1', pod_number: 'POD1', part_number: 'MODEL1'}, rows: [
    {row_id: '2', row_version: 'version-2', serial_number: 'ABC001'},
    {row_id: '3', row_version: 'version-3', serial_number: 'ABC002'}
]});
assert.throws(() => plan(state, key, sequence('ABC001', 3)), /Only 2 blank/);
assert.throws(() => plan(state, key, ['imported']), /already exists/);
assert.throws(() => plan(state, key, ['ABC', ' abc ']), /Duplicate/);
assert.throws(() => plan(state, 'unknown', ['ABC']), /Choose/);
assert.throws(() => plan(state, key, []), /Fill between/);
assert.equal(state.rows[2].serial_number, '', 'planning never mutates database state');
assert.notEqual(groupKey(row(1, '', {box_number: 'a|b', pod_number: 'c'})), groupKey(row(2, '', {box_number: 'a', pod_number: 'b|c'})));
console.log('Receiving scan assignment, grouping, sequence width/precision and duplicate tests passed.');
