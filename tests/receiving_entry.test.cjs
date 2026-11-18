const assert = require('node:assert/strict');
const { parseColumn, duplicateIds, nextBlankRow, canScanRow, validateSerialPaste } = require('../static/receiving.js');
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
const unit = (id, extra = {}) => ({row_id: id, quantity: 1, serial_number: '',
    box_number: 'BOX', pod_number: 'POD', part_number: 'PART', ...extra});
const rows = [unit('current', {serial_number: 'SAVED'}),
    unit('occupied', {serial_number: 'EXISTING'}), unit('bulk', {quantity: 3}),
    unit('other-box', {box_number: 'OTHER'}), unit('other-pod', {pod_number: 'OTHER'}),
    unit('other-part', {part_number: 'OTHER'}), unit('hidden'), unit('next'), unit('last')];
assert.equal(nextBlankRow(rows, 'current', () => true).row_id, 'bulk');
assert.equal(nextBlankRow(rows, 'current', row => !['bulk', 'hidden'].includes(row.row_id)).row_id, 'next');
assert.equal(nextBlankRow(rows, 'next', () => true).row_id, 'last');
assert.equal(nextBlankRow(rows, 'last', () => true), null);
assert.equal(nextBlankRow(rows, 'bulk', () => true).row_id, 'hidden');
assert.equal(nextBlankRow(rows, 'missing', () => true), null);
assert.equal(nextBlankRow(rows, 'current', () => false), null);
assert.equal(canScanRow(unit('blank', {db_id: 1})), true);
assert.equal(canScanRow(unit('whitespace', {db_id: 1, serial_number: '  '})), true);
assert.equal(canScanRow(unit('saved', {db_id: 1, serial_number: 'SN1'})), false);
assert.equal(canScanRow(unit('placeholder', {db_id: 1, serial_number: 'NA'})), false);
assert.equal(canScanRow(unit('bulk', {db_id: 1, quantity: 3})), true);
assert.equal(canScanRow(unit('draft', {db_id: null})), false);
assert.equal(canScanRow(null), false);
const pastedRows = [{row_id:'1',serial_number:'EXISTING'}, {row_id:'2',serial_number:''}, {row_id:'3',serial_number:''}];
assert.throws(() => validateSerialPaste(pastedRows, [{row_id:'2',serial_number:' existing '}]), /duplicate/);
assert.throws(() => validateSerialPaste(pastedRows, [{row_id:'2',serial_number:'SAME'}, {row_id:'3',serial_number:'same'}]), /duplicate/);
assert.doesNotThrow(() => validateSerialPaste(pastedRows, [{row_id:'2',serial_number:'NEW1'}, {row_id:'3',serial_number:'NEW2'}]));
assert.doesNotThrow(() => validateSerialPaste(pastedRows, [{row_id:'2',serial_number:'NA'}, {row_id:'3',serial_number:'NA'}]));
console.log('Receiving entry validation, range paste duplicate checks, blank scan eligibility and Enter navigation tests passed.');
