const assert = require('node:assert/strict');
const { parseColumn, duplicateIds } = require('../static/receiving.js');
assert.deepEqual(parseColumn('SN-1\r\nSN-2\r\n'), ['SN-1', 'SN-2']);
assert.deepEqual(parseColumn(' SN-1 \n\nSN-3'), ['SN-1', '', 'SN-3']);
assert.throws(() => parseColumn('SN-1\tPART'), /one SN column/);
assert.throws(() => parseColumn('=FORMULA()\nSN-2'), /not formulas/);
assert.throws(() => parseColumn('NAN\nSN-2'), /not formulas/);
assert.throws(() => parseColumn('x'.repeat(256)), /255/);
assert.deepEqual([...duplicateIds([
    {row_id: '1', serial_number: ''}, {row_id: '2', serial_number: ''},
    {row_id: '3', serial_number: 'na'}, {row_id: '4', serial_number: 'NA'},
    {row_id: '5', serial_number: 'sn-1'}, {row_id: '6', serial_number: ' SN-1 '}
])].sort(), ['5', '6']);
console.log('Receiving entry paste and duplicate validation tests passed.');
