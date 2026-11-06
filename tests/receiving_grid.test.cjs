const assert = require('node:assert/strict');
const {parseTSV, planPaste, validateValue} = require('../static/receiving_grid.js');
const selection = (r, c, er = r, ec = c) => ({anchor: {r, c}, end: {r: er, c: ec}});
assert.deepEqual(parseTSV('Box A\tPOD1\r\nBox B\tPOD2\r\n'), [['Box A', 'POD1'], ['Box B', 'POD2']]);
assert.deepEqual(parseTSV('"A ""quoted"" value"\tB\n'), [['A "quoted" value', 'B']]);
assert.deepEqual(parseTSV('A\t\r\n\t\r\n'), [['A', ''], ['', '']]);
assert.deepEqual(parseTSV(''), [['']]);
assert.deepEqual(parseTSV('"multi\nline"\tvalue\r\n'), [['multi\nline', 'value']]);
assert.throws(() => parseTSV('A\tB\nC'), /rectangular/);
assert.throws(() => parseTSV('"unclosed'), /Unclosed/);
assert.throws(() => parseTSV('"closed"extra'), /Invalid/);
assert.deepEqual(planPaste([['A', 'B'], ['C', 'D']], selection(1, 2), 5, 7), [
    {r: 1, c: 2, value: 'A'}, {r: 1, c: 3, value: 'B'},
    {r: 2, c: 2, value: 'C'}, {r: 2, c: 3, value: 'D'}
]);
assert.equal(planPaste([['ONE']], selection(2, 3, 0, 1), 5, 7).length, 9);
assert.throws(() => planPaste([['A', 'B']], selection(0, 0), 5, 1), /Not enough/);
assert.throws(() => planPaste([['A'], ['B']], selection(4, 0), 5, 1), /Not enough/);
assert.throws(() => planPaste([['A'], ['B']], selection(0, 0, 2, 0), 5, 1), /match/);
assert.equal(planPaste([['A'], ['B']], selection(0, 0, 1, 0), 5, 1).length, 2);
const input = (type = 'text', field = '', maxLength = 255) => ({type, dataset: {field}, maxLength});
assert.equal(validateValue(input(), ' SN123 '), 'SN123');
assert.equal(validateValue(input('number'), '1.5'), '1.5');
assert.equal(validateValue(input('date'), '2026-11-04'), '2026-11-04');
for (const value of ['=formula', 'NaN', 'line\nline', 'A'.repeat(256)]) assert.throws(() => validateValue(input(), value));
for (const value of ['0', '-1', 'Infinity', '', 'bad']) assert.throws(() => validateValue(input('number'), value));
for (const value of ['11/4/2026', '2026-02-30', '2026-13-01', '']) assert.throws(() => validateValue(input('date'), value));
assert.throws(() => validateValue(input('text', 'part_number'), ''));
console.log('Receiving grid TSV parsing, rectangular selection, paste bounds and validation tests passed.');
