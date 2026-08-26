// Aufruf: npm test (node --test, keine Test-Dependencies noetig).
// Die synthetischen Erwartungswerte sind dieselben wie in
// pipeline/test_interpolation.py, damit der Port beweisbar aequivalent ist.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { meterZuKoord, position, zeitZuMeter } from '../src/interpolation.js';

const SHAPE = {
  coords: [[10.0, 53.0], [10.0, 53.001], [10.0, 53.003]],
  meter: [0, 111, 333],
};
const HALTE = [
  { name: 'A', an: 0, ab: 10, m: 0 },
  { name: 'B', an: 110, ab: 120, m: 333 },
];
const FAHRT = { id: 'test', linie: 'U1', shape: 's1', halte: HALTE };
const SHAPES = { s1: SHAPE };

test('synthetisch: klemmen, stehen, fahren', () => {
  assert.equal(zeitZuMeter(HALTE, -5), 0);
  assert.equal(zeitZuMeter(HALTE, 5), 0);
  assert.equal(zeitZuMeter(HALTE, 999), 333);
  assert.equal(zeitZuMeter(HALTE, 115), 333);

  // t=65 -> Fortschritt (65-10)/(110-10) = 0.55 -> m = 183.15
  assert.ok(Math.abs(zeitZuMeter(HALTE, 65) - 183.15) < 1e-9);
});

test('synthetisch: meter zu koordinate', () => {
  // m=183.15: Anteil 72.15/222 = 0.325 -> lat = 53.001 + 0.325 * 0.002 = 53.00165
  const [lon, lat] = meterZuKoord(SHAPE, 183.15);
  assert.ok(Math.abs(lon - 10.0) < 1e-9);
  assert.ok(Math.abs(lat - 53.00165) < 1e-6);

  assert.deepEqual(meterZuKoord(SHAPE, 111), [10.0, 53.001]);
  assert.deepEqual(meterZuKoord(SHAPE, -1), [10.0, 53.0]);
  assert.deepEqual(meterZuKoord(SHAPE, 9999), [10.0, 53.003]);

  const [, lat2] = position(FAHRT, SHAPES, 65);
  assert.ok(Math.abs(lat2 - 53.00165) < 1e-6);
});

test('echte Testfahrt: haltgenau, monoton, plausibel', () => {
  const pfad = fileURLToPath(new URL('../public/geo/testfahrt.json', import.meta.url));
  const daten = JSON.parse(readFileSync(pfad, 'utf8'));
  const fahrt = daten.fahrten[0];
  const halte = fahrt.halte;

  for (const h of halte) {
    assert.equal(zeitZuMeter(halte, h.an), h.m, h.name);
  }

  let mVorher = -1;
  for (let t = halte[0].ab; t <= halte[halte.length - 1].an; t++) {
    const m = zeitZuMeter(halte, t);
    assert.ok(m >= mVorher, `Ruecksprung bei t=${t}`);
    assert.ok(m - mVorher <= 36, `unplausible Geschwindigkeit bei t=${t}`);
    mVorher = m;
  }

  const ende = position(fahrt, daten.shapes, halte[halte.length - 1].an);
  const erwartet = meterZuKoord(daten.shapes[fahrt.shape], halte[halte.length - 1].m);
  assert.deepEqual(ende, erwartet);
});
