// Replay-Interpolation, 1:1-Port der Python-Referenz (pipeline/interpolation.py).
// Zweistufig: Zeit -> Meter (linear zwischen Halten, Stillstand in Haltezeiten)
// und Meter -> Koordinate (binaere Suche in der kumulierten meter-Liste).
// Beide Implementierungen muessen dieselben Testzahlen liefern, siehe
// frontend/tests/interpolation.test.js und pipeline/test_interpolation.py.

export function zeitZuMeter(halte, t) {
  if (t <= halte[0].ab) return halte[0].m;
  if (t >= halte[halte.length - 1].an) return halte[halte.length - 1].m;

  for (let i = 0; i < halte.length - 1; i++) {
    const h1 = halte[i];
    const h2 = halte[i + 1];
    if (h1.an <= t && t <= h1.ab) return h1.m;
    if (h1.ab < t && t < h2.an) {
      const fortschritt = (t - h1.ab) / (h2.an - h1.ab);
      return h1.m + fortschritt * (h2.m - h1.m);
    }
  }
  return halte[halte.length - 1].m;
}

export function meterZuKoord(shape, m) {
  const { meter, coords } = shape;

  if (m <= meter[0]) return [...coords[0]];
  if (m >= meter[meter.length - 1]) return [...coords[coords.length - 1]];

  // binaere Suche: kleinster Index i mit meter[i] > m; m liegt zwischen i-1 und i
  let lo = 0;
  let hi = meter.length - 1;
  while (lo < hi) {
    const mitte = (lo + hi) >> 1;
    if (meter[mitte] > m) hi = mitte;
    else lo = mitte + 1;
  }

  const anteil = (m - meter[lo - 1]) / (meter[lo] - meter[lo - 1]);
  const [lon1, lat1] = coords[lo - 1];
  const [lon2, lat2] = coords[lo];
  return [lon1 + anteil * (lon2 - lon1), lat1 + anteil * (lat2 - lat1)];
}

export function position(fahrt, shapes, t) {
  return meterZuKoord(shapes[fahrt.shape], zeitZuMeter(fahrt.halte, t));
}
