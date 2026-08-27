// Replay-Engine fuer den Mehrtages-Datensatz (Schema v2).
// Tagesauswahl filtert client-seitig (Tag -> aktive Services -> Fahrten),
// der Linienfilter wirkt auf Spuren, Kopfpunkte und die statischen Layer.
// Nachleuchtspuren rendert der TripsLayer auf der GPU, die hellen Zugpunkte
// kommen aus der eigenen position()-Interpolation.

import { TripsLayer } from '@deck.gl/geo-layers';
import { ScatterplotLayer } from '@deck.gl/layers';
import { MapboxOverlay } from '@deck.gl/mapbox';
import { position } from './interpolation.js';
import { fahrtZuTrip, hexZuRgb, normalisiereFahrt } from './trips_konverter.js';

const BETRIEBSTAG_BEGINN_S = 4 * 3600;
const TEMPO_STUFEN = [60, 120, 300, 600];
const TRAIL_LAENGE_S = 120;
// Spur-Geometrie um ~11 m vereinfacht (nur Optik, Kopfpunkte bleiben exakt)
const SPUR_TOLERANZ_GRAD = 0.0001;
// nur Fahrten eines gleitenden Zeitfensters liegen im GPU-Buffer
const FENSTER_S = 1800;
const START_TAG = '2026-09-16';

function formatUhrzeit(t) {
  const s = ((Math.floor(t) + BETRIEBSTAG_BEGINN_S) % 86400 + 86400) % 86400;
  const hh = String(Math.floor(s / 3600)).padStart(2, '0');
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  return `${hh}:${mm}:${ss}`;
}

function textFarbe([r, g, b]) {
  return 0.299 * r + 0.587 * g + 0.114 * b > 140 ? '#0e0e12' : '#f4f6fa';
}

// Leucht-Variante der offiziellen Linienfarbe fuer die Spuren: mehr
// Saettigung, Mindesthelligkeit angehoben, sonst saufen dunkle Farben
// (S7-Navy) auf der dunklen Karte ab. Legende/Doku behalten die Originale.
function leuchtFarbe([r, g, b]) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  let l = (max + min) / 2;
  let h = 0;
  let s = 0;
  const d = max - min;
  if (d > 0) {
    s = d / (1 - Math.abs(2 * l - 1));
    if (max === r) h = (((g - b) / d) % 6 + 6) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60;
  }
  s = Math.min(1, s * 1.4);
  l = Math.max(l, 0.55);
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  const [r2, g2, b2] =
    h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x]
    : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return [Math.round((r2 + m) * 255), Math.round((g2 + m) * 255), Math.round((b2 + m) * 255)];
}

export function starteReplay(map, daten) {
  const farben = Object.fromEntries(
    Object.entries(daten.linien).map(([linie, info]) => [linie, hexZuRgb(info.farbe)])
  );
  const spurFarben = Object.fromEntries(
    Object.entries(farben).map(([linie, rgb]) => [linie, leuchtFarbe(rgb)])
  );
  const aktiveLinien = new Set(Object.keys(daten.linien));

  const overlay = new MapboxOverlay({ layers: [] });
  map.addControl(overlay);

  // UI-Elemente
  const uhrZeit = document.getElementById('uhr-zeit');
  const uhrFahrt = document.getElementById('uhr-fahrt');
  const playpause = document.getElementById('playpause');
  const regler = document.getElementById('zeitregler');
  const tempoLeiste = document.getElementById('tempo-stufen');
  const tagwahl = document.getElementById('tagwahl');
  const legende = document.getElementById('legende');
  document.getElementById('uhr').hidden = false;
  document.getElementById('steuerung').hidden = false;
  legende.hidden = false;

  // Tageszustand
  let tagesFahrten = [];
  let trips = [];
  let tMax = 1;
  let simZeit = 0;
  let tempo = 120;
  let laeuft = true;
  let fensterStart = Number.NEGATIVE_INFINITY;
  let fensterTrips = [];

  function ladeTag(datum) {
    const services = new Set(daten.tage[datum] ?? []);
    tagesFahrten = daten.fahrten
      .filter((f) => services.has(f.s))
      .map((f) => normalisiereFahrt(f, daten.stationen));
    trips = tagesFahrten.map((f) => {
      const halte = f.halte;
      return {
        ...fahrtZuTrip(f, daten.shapes, SPUR_TOLERANZ_GRAD),
        linie: f.linie,
        farbe: spurFarben[f.linie],
        start: halte[0].an,
        ende: halte[halte.length - 1].an,
      };
    });
    tMax = trips.length ? Math.max(...trips.map((t) => t.ende)) : 1;
    regler.max = tMax;
    simZeit = 0;
    fensterStart = Number.NEGATIVE_INFINITY;
  }

  // gleitendes Zeitfenster: nur Fahrten, die das Fenster beruehren, gehen
  // an den TripsLayer, damit der GPU-Buffer klein bleibt
  function tripsImFenster(t) {
    const start = Math.floor(t / FENSTER_S) * FENSTER_S;
    if (start !== fensterStart) {
      fensterStart = start;
      fensterTrips = trips.filter(
        (tr) =>
          aktiveLinien.has(tr.linie) &&
          tr.ende >= start - TRAIL_LAENGE_S &&
          tr.start <= start + FENSTER_S
      );
    }
    return fensterTrips;
  }

  // Linienfilter auch auf die statischen MapLibre-Layer anwenden
  function setzeKartenFilter() {
    const liste = [...aktiveLinien];
    map.setFilter('liniennetz-linien', ['in', ['get', 'linie'], ['literal', liste]]);
    map.setFilter('stationen-punkte', ['any', false, ...liste.map((l) => ['in', l, ['get', 'linien']])]);
    fensterStart = Number.NEGATIVE_INFINITY;
  }

  // Legende: klickbare Linien-Chips
  function stileChip(chip, linie) {
    const aktiv = aktiveLinien.has(linie);
    chip.style.background = aktiv ? `rgb(${farben[linie].join(',')})` : '#2a2f3a';
    chip.style.color = aktiv ? textFarbe(farben[linie]) : '#8891a0';
  }
  for (const linie of Object.keys(daten.linien)) {
    const chip = document.createElement('button');
    chip.textContent = linie;
    chip.addEventListener('click', () => {
      if (aktiveLinien.has(linie)) aktiveLinien.delete(linie);
      else aktiveLinien.add(linie);
      stileChip(chip, linie);
      setzeKartenFilter();
    });
    stileChip(chip, linie);
    legende.append(chip);
  }

  // Steuerungs-Events
  const ueber = document.getElementById('ueber');
  document.getElementById('info-knopf').addEventListener('click', () => ueber.showModal());
  document.getElementById('ueber-schliessen').addEventListener('click', () => ueber.close());

  playpause.addEventListener('click', () => {
    laeuft = !laeuft;
    playpause.textContent = laeuft ? '⏸' : '▶';
  });
  regler.addEventListener('input', () => {
    simZeit = Number(regler.value);
  });
  for (const stufe of TEMPO_STUFEN) {
    const knopf = document.createElement('button');
    knopf.textContent = `${stufe}x`;
    knopf.classList.toggle('aktiv', stufe === tempo);
    knopf.addEventListener('click', () => {
      tempo = stufe;
      for (const k of tempoLeiste.children) k.classList.toggle('aktiv', k === knopf);
    });
    tempoLeiste.append(knopf);
  }

  const tage = Object.keys(daten.tage);
  let aktuellerTag = daten.tage[START_TAG] ? START_TAG : tage[0];
  let hinweis = '';
  let hinweisBis = 0;
  tagwahl.min = daten.meta.zeitraum[0];
  tagwahl.max = daten.meta.zeitraum[1];
  tagwahl.value = aktuellerTag;
  tagwahl.addEventListener('change', () => {
    // min/max erzwingt nicht jeder Picker: Auswahl ohne Fahrplan
    // zuruecksetzen und kurz erklaeren statt stillschweigend ignorieren
    if (!daten.tage[tagwahl.value]) {
      hinweis = `${tagwahl.value || 'Datum'}: kein Fahrplan im Datensatz`;
      hinweisBis = performance.now() + 4000;
      tagwahl.value = aktuellerTag;
      return;
    }
    aktuellerTag = tagwahl.value;
    hinweisBis = 0;
    ladeTag(aktuellerTag);
  });

  function render(t) {
    const aktive = tagesFahrten.filter(
      (f) =>
        aktiveLinien.has(f.linie) &&
        f.halte[0].an <= t &&
        t <= f.halte[f.halte.length - 1].an
    );
    overlay.setProps({
      layers: [
        new TripsLayer({
          id: 'zuege-spur',
          data: tripsImFenster(t),
          getPath: (d) => d.path,
          getTimestamps: (d) => d.timestamps,
          getColor: (d) => d.farbe,
          currentTime: t,
          trailLength: TRAIL_LAENGE_S,
          widthMinPixels: 3,
          capRounded: true,
          jointRounded: true,
          opacity: 1.0,
        }),
        new ScatterplotLayer({
          id: 'zuege-punkte',
          data: aktive,
          getPosition: (d) => position(d, daten.shapes, t),
          getFillColor: [255, 255, 255, 235],
          radiusMinPixels: 2.5,
          updateTriggers: { getPosition: t },
        }),
      ],
    });
    uhrZeit.textContent = formatUhrzeit(t);
    uhrFahrt.textContent =
      performance.now() < hinweisBis
        ? hinweis
        : `${aktuellerTag} · ${aktive.length} Züge unterwegs`;
    regler.value = t;
  }

  ladeTag(tagwahl.value);
  setzeKartenFilter();

  let letzterFrame = null;
  function tick(jetzt) {
    if (letzterFrame !== null && laeuft) {
      simZeit += ((jetzt - letzterFrame) / 1000) * tempo;
      if (simZeit > tMax) simZeit = 0; // Tagesende: von vorn
    }
    letzterFrame = jetzt;
    render(simZeit);
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}
