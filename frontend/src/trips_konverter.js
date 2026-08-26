// Konvertiert eine Fahrt des Tagesdatensatzes in TripsLayer-Eingaben:
// einen Pfad plus einen Zeitstempel je Pfadpunkt. Der TripsLayer
// interpoliert linear zwischen den Zeitstempeln auf der GPU und rechnet
// damit exakt dasselbe wie unsere position()-Funktion, denn zwischen zwei
// Pfadpunkten sind sowohl Meter ueber Zeit als auch Koordinate ueber Meter
// linear. Haltezeiten werden als Doppel-Vertex abgebildet (gleiche
// Position, Ankunfts- und Abfahrtszeit): der Zug steht.
// Aequivalenz-Nachweis: tests/trips_konverter.test.js

import { meterZuKoord } from './interpolation.js';

// Punkt-zu-Segment-Abstand in "Breitengrad-aequivalenten" Grad
// (Laengengrad um cos(Breite) gestaucht), reicht fuer Vereinfachung voellig
function abstandZuSegment(p, a, b, skala) {
  const px = (p[0] - a[0]) * skala;
  const py = p[1] - a[1];
  const bx = (b[0] - a[0]) * skala;
  const by = b[1] - a[1];
  const laenge2 = bx * bx + by * by;
  const anteil = laenge2 === 0 ? 0 : Math.max(0, Math.min(1, (px * bx + py * by) / laenge2));
  const dx = px - anteil * bx;
  const dy = py - anteil * by;
  return Math.sqrt(dx * dx + dy * dy);
}

// Douglas-Peucker, aber Halte-Vertices (fest) bleiben immer erhalten,
// damit Haltezeiten (Doppel-Vertex) und Haltepositionen exakt bleiben
function vereinfache(path, timestamps, fest, toleranz) {
  const n = path.length;
  const behalten = new Array(n).fill(false);
  behalten[0] = behalten[n - 1] = true;
  for (const i of fest) behalten[i] = true;

  const skala = Math.cos((path[0][1] * Math.PI) / 180);
  const stapel = [[0, n - 1]];
  while (stapel.length) {
    const [a, b] = stapel.pop();
    if (b - a < 2) continue;
    let split = -1;
    for (let i = a + 1; i < b; i++) {
      if (behalten[i]) {
        split = i;
        break;
      }
    }
    if (split === -1) {
      let maxD = 0;
      for (let i = a + 1; i < b; i++) {
        const d = abstandZuSegment(path[i], path[a], path[b], skala);
        if (d > maxD) {
          maxD = d;
          split = i;
        }
      }
      if (maxD <= toleranz) continue;
      behalten[split] = true;
    }
    stapel.push([a, split], [split, b]);
  }

  const neuPath = [];
  const neuZeiten = [];
  for (let i = 0; i < n; i++) {
    if (behalten[i]) {
      neuPath.push(path[i]);
      neuZeiten.push(timestamps[i]);
    }
  }
  return { path: neuPath, timestamps: neuZeiten };
}

export function fahrtZuTrip(fahrt, shapes, toleranzGrad = 0) {
  const shape = shapes[fahrt.shape];
  const { meter, coords } = shape;
  const halte = fahrt.halte;

  const path = [];
  const timestamps = [];
  const fest = [];
  const fuege = (koord, t, istHalt = false) => {
    if (istHalt) fest.push(path.length);
    path.push(koord);
    timestamps.push(t);
  };

  let j = 0;
  for (let i = 0; i < halte.length - 1; i++) {
    const h1 = halte[i];
    const h2 = halte[i + 1];

    if (i === 0) {
      fuege(meterZuKoord(shape, h1.m), h1.an, true);
      if (h1.ab > h1.an) fuege(meterZuKoord(shape, h1.m), h1.ab, true);
    } else if (h1.ab > h1.an) {
      // Ankunft wurde bereits als Ende des vorigen Segments eingefuegt
      fuege(meterZuKoord(shape, h1.m), h1.ab, true);
    }

    // Shape-Punkte strikt zwischen den beiden Halten, Zeit linear ueber Meter
    while (j < meter.length && meter[j] <= h1.m) j++;
    for (; j < meter.length && meter[j] < h2.m; j++) {
      const t = h1.ab + ((meter[j] - h1.m) / (h2.m - h1.m)) * (h2.an - h1.ab);
      fuege([coords[j][0], coords[j][1]], t);
    }

    fuege(meterZuKoord(shape, h2.m), h2.an, true);
  }

  if (toleranzGrad > 0) return vereinfache(path, timestamps, fest, toleranzGrad);
  return { path, timestamps };
}

export function hexZuRgb(hex) {
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
}
