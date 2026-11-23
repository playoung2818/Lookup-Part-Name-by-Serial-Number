const assert = require('node:assert/strict');
const {status, chartSvg, ago} = require('../static/home_climate.js');

// OK range is inclusive: 40 and 80 are fine, 39 and 81 are not.
assert.equal(status({humidity: 40, age_seconds: 60}, 40, 80).cls, 'ok');
assert.equal(status({humidity: 80, age_seconds: 60}, 40, 80).cls, 'ok');
assert.match(status({humidity: 39, age_seconds: 60}, 40, 80).text, /Too dry/);
assert.match(status({humidity: 81, age_seconds: 60}, 40, 80).text, /Too humid/);
assert.equal(status({humidity: 50, age_seconds: 3600}, 40, 80).cls, 'stale');
assert.equal(status(null, 40, 80).text, 'No readings yet');
assert.equal(ago(30), 'just now');
assert.equal(ago(600), '10 min ago');

const now = Date.now();
const points = [0, 5, 10, 60].map((min, i) => ({t: new Date(now - (60 - min) * 60e3).toISOString(), humidity: [50, 85, 60, 55][i], temperature: 21}));
const chart = chartSvg(points, 40, 80, '24h');
assert.equal(chart.xs.length, 4);
assert.equal((chart.svg.match(/class="out"/g) || []).length, 1, 'only the 85 % reading is flagged');
assert.match(chart.svg, /class="band"/);
assert.equal((chart.svg.match(/[ML]\d/g) || []).filter(s => s[0] === 'M').length, 2, 'line breaks at the 50-minute gap');
assert.match(chartSvg([], 40, 80, '7d').svg, /No readings in this period yet/);
console.log('Homepage humidity status, inclusive range, staleness and chart tests passed.');
