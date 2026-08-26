// Konvertiert eine Fahrt des Tagesdatensatzes in TripsLayer-Eingaben:
// einen Pfad plus einen Zeitstempel je Pfadpunkt. Der TripsLayer
// interpoliert linear zwischen den Zeitstempeln auf der GPU und rechnet
// damit exakt dasselbe wie unsere position()-Funktion, denn zwischen zwei
// Pfadpunkten sind sowohl Meter ueber Zeit als auch Koordinate ueber Meter
// linear. Haltezeiten werden als Doppel-Vertex abgebildet (gleiche
// Position, Ankunfts- und Abfahrtszeit): der Zug steht.
// Aequivalenz-Nachweis: tests/trips_konverter.test.js

import { meterZuKoord } from './interpolation.js';

export function fahrtZuTrip(fahrt, shapes) {
  const shape = shapes[fahrt.shape];
  const { meter, coords } = shape;
  const halte = fahrt.halte;

  const path = [];
  const timestamps = [];
  const fuege = (koord, t) => {
    path.push(koord);
    timestamps.push(t);
  };

  let j = 0;
  for (let i = 0; i < halte.length - 1; i++) {
    const h1 = halte[i];
    const h2 = halte[i + 1];

    if (i === 0) {
      fuege(meterZuKoord(shape, h1.m), h1.an);
      if (h1.ab > h1.an) fuege(meterZuKoord(shape, h1.m), h1.ab);
    } else if (h1.ab > h1.an) {
      // Ankunft wurde bereits als Ende des vorigen Segments eingefuegt
      fuege(meterZuKoord(shape, h1.m), h1.ab);
    }

    // Shape-Punkte strikt zwischen den beiden Halten, Zeit linear ueber Meter
    while (j < meter.length && meter[j] <= h1.m) j++;
    for (; j < meter.length && meter[j] < h2.m; j++) {
      const t = h1.ab + ((meter[j] - h1.m) / (h2.m - h1.m)) * (h2.an - h1.ab);
      fuege([coords[j][0], coords[j][1]], t);
    }

    fuege(meterZuKoord(shape, h2.m), h2.an);
  }

  return { path, timestamps };
}

export function hexZuRgb(hex) {
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
}
