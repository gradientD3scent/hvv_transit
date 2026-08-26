// Äquivalenz-Nachweis: Positionen, die der TripsLayer aus den konvertierten
// Vertex-Zeitstempeln linear interpoliert, müssen mit unserer verifizierten
// position()-Funktion übereinstimmen. Dazu wird die TripsLayer-Interpolation
// hier nachgebaut (linear zwischen den umgebenden Zeitstempeln) und an
// dichten Stichproben gegen position() verglichen.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { position } from '../src/interpolation.js';
import { fahrtZuTrip, hexZuRgb, normalisiereFahrt } from '../src/trips_konverter.js';

// lineare Interpolation zwischen den Vertex-Zeitstempeln, wie im TripsLayer
function positionAusTrip(trip, t) {
  const { path, timestamps } = trip;
  if (t <= timestamps[0]) return path[0];
  if (t >= timestamps[timestamps.length - 1]) return path[path.length - 1];
  for (let i = 1; i < timestamps.length; i++) {
    if (t <= timestamps[i]) {
      const dt = timestamps[i] - timestamps[i - 1];
      const anteil = dt === 0 ? 1 : (t - timestamps[i - 1]) / dt;
      return [
        path[i - 1][0] + anteil * (path[i][0] - path[i - 1][0]),
        path[i - 1][1] + anteil * (path[i][1] - path[i - 1][1]),
      ];
    }
  }
  return path[path.length - 1];
}

const SHAPE = {
  coords: [[10.0, 53.0], [10.0, 53.001], [10.0, 53.003]],
  meter: [0, 111, 333],
};
const FAHRT = {
  id: 'test',
  linie: 'U1',
  shape: 's1',
  halte: [
    { name: 'A', an: 0, ab: 10, m: 0 },
    { name: 'B', an: 110, ab: 120, m: 200 },
    { name: 'C', an: 200, ab: 200, m: 333 },
  ],
};
const SHAPES = { s1: SHAPE };

test('synthetisch: Konverter-Struktur und Haltezeiten', () => {
  const trip = fahrtZuTrip(FAHRT, SHAPES);
  assert.equal(trip.path.length, trip.timestamps.length);

  // Zeitstempel nicht fallend
  for (let i = 1; i < trip.timestamps.length; i++) {
    assert.ok(trip.timestamps[i] >= trip.timestamps[i - 1], `Zeit fällt bei Index ${i}`);
  }

  // Haltezeit an B: Position konstant bei m=200
  const [lonAn, latAn] = positionAusTrip(trip, 112);
  const [lonAb, latAb] = positionAusTrip(trip, 118);
  assert.ok(Math.abs(lonAn - lonAb) < 1e-12 && Math.abs(latAn - latAb) < 1e-12);
});

test('synthetisch: äquivalent zu position()', () => {
  const trip = fahrtZuTrip(FAHRT, SHAPES);
  for (let t = -10; t <= 210; t += 1) {
    const [lonA, latA] = position(FAHRT, SHAPES, t);
    const [lonB, latB] = positionAusTrip(trip, t);
    assert.ok(Math.abs(lonA - lonB) < 1e-9 && Math.abs(latA - latB) < 1e-9, `Abweichung bei t=${t}`);
  }
});

test('echte Testfahrt: äquivalent zu position() über die ganze Fahrt', () => {
  const pfad = fileURLToPath(new URL('../public/geo/testfahrt.json', import.meta.url));
  const daten = JSON.parse(readFileSync(pfad, 'utf8'));
  const fahrt = daten.fahrten[0];
  const trip = fahrtZuTrip(fahrt, daten.shapes);

  const start = fahrt.halte[0].an;
  const ende = fahrt.halte[fahrt.halte.length - 1].an;
  for (let t = start; t <= ende; t += 5) {
    const [lonA, latA] = position(fahrt, daten.shapes, t);
    const [lonB, latB] = positionAusTrip(trip, t);
    // 1e-7 Grad sind ~1 cm, mehr Toleranz braucht identische Mathematik nicht
    assert.ok(Math.abs(lonA - lonB) < 1e-7 && Math.abs(latA - latB) < 1e-7, `Abweichung bei t=${t}`);
  }
});

test('vereinfachte Spur: deutlich weniger Vertices, begrenzte Abweichung', () => {
  const pfad = fileURLToPath(new URL('../public/geo/testfahrt.json', import.meta.url));
  const daten = JSON.parse(readFileSync(pfad, 'utf8'));
  const fahrt = daten.fahrten[0];

  const exakt = fahrtZuTrip(fahrt, daten.shapes);
  const vereinfacht = fahrtZuTrip(fahrt, daten.shapes, 0.0001);

  assert.ok(
    vereinfacht.path.length < exakt.path.length / 3,
    `nur ${exakt.path.length} -> ${vereinfacht.path.length} Vertices`
  );

  // Abweichung zur exakten Position bleibt im Rahmen der Toleranz (~11 m
  // quer plus Zeit-Linearisierung, grosszuegig 0.0004 Grad ~ 33 m)
  const skala = Math.cos((53.6 * Math.PI) / 180);
  const start = fahrt.halte[0].an;
  const ende = fahrt.halte[fahrt.halte.length - 1].an;
  for (let t = start; t <= ende; t += 10) {
    const [lonA, latA] = position(fahrt, daten.shapes, t);
    const [lonB, latB] = positionAusTrip(vereinfacht, t);
    const d = Math.hypot((lonA - lonB) * skala, latA - latB);
    assert.ok(d < 0.0004, `Abweichung ${d} Grad bei t=${t}`);
  }

  // Haltezeiten bleiben Stillstand: Position bei an und ab identisch
  for (const h of fahrt.halte) {
    if (h.ab > h.an) {
      const [lonAn, latAn] = positionAusTrip(vereinfacht, h.an);
      const [lonAb, latAb] = positionAusTrip(vereinfacht, h.ab);
      assert.ok(Math.abs(lonAn - lonAb) < 1e-12 && Math.abs(latAn - latAb) < 1e-12, h.name);
    }
  }
});

test('hexZuRgb', () => {
  assert.deepEqual(hexZuRgb('#1C6EB4'), [28, 110, 180]);
  assert.deepEqual(hexZuRgb('#FFDD00'), [255, 221, 0]);
});

test('normalisiereFahrt: v2-Halte-Arrays werden zu benannten Objekten', () => {
  const roh = {
    id: '42',
    linie: 'U1',
    shape: '2907',
    s: 3,
    halte: [[1, 0, 10, 0], [0, 110, 120, 333]],
  };
  const f = normalisiereFahrt(roh, ['Richtweg', 'Norderstedt Mitte']);
  assert.deepEqual(f.halte, [
    { name: 'Norderstedt Mitte', an: 0, ab: 10, m: 0 },
    { name: 'Richtweg', an: 110, ab: 120, m: 333 },
  ]);
  assert.equal(f.linie, 'U1');
  assert.equal(f.shape, '2907');
});
