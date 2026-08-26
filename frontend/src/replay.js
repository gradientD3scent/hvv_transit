// Replay-Engine: spielt einen kompletten Betriebstag ab.
// Nachleuchtspuren rendert der TripsLayer auf der GPU (currentTime je Frame),
// die hellen Zugpunkte kommen aus der eigenen position()-Interpolation,
// gerechnet nur fuer die gerade aktiven Fahrten.

import { TripsLayer } from '@deck.gl/geo-layers';
import { ScatterplotLayer } from '@deck.gl/layers';
import { MapboxOverlay } from '@deck.gl/mapbox';
import { position } from './interpolation.js';
import { fahrtZuTrip, hexZuRgb } from './trips_konverter.js';

const BETRIEBSTAG_BEGINN_S = 4 * 3600;
const TEMPO_STUFEN = [60, 120, 300, 600];
const TRAIL_LAENGE_S = 120;

function formatUhrzeit(t) {
  const s = ((Math.floor(t) + BETRIEBSTAG_BEGINN_S) % 86400 + 86400) % 86400;
  const hh = String(Math.floor(s / 3600)).padStart(2, '0');
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  return `${hh}:${mm}:${ss}`;
}

export function starteReplay(map, daten) {
  const farben = Object.fromEntries(
    Object.entries(daten.linien).map(([linie, info]) => [linie, hexZuRgb(info.farbe)])
  );
  const trips = daten.fahrten.map((f) => ({ ...fahrtZuTrip(f, daten.shapes), farbe: farben[f.linie] }));

  // Replay-Fenster: ab 04:00 (t=0), die 4 Ausreisser-Fahrten davor laufen aus dem Bild
  const tMax = Math.max(...daten.fahrten.map((f) => f.halte[f.halte.length - 1].an));

  const overlay = new MapboxOverlay({ layers: [] });
  map.addControl(overlay);

  // UI-Elemente
  const uhrZeit = document.getElementById('uhr-zeit');
  const uhrFahrt = document.getElementById('uhr-fahrt');
  const playpause = document.getElementById('playpause');
  const regler = document.getElementById('zeitregler');
  const tempoLeiste = document.getElementById('tempo-stufen');
  document.getElementById('uhr').hidden = false;
  document.getElementById('steuerung').hidden = false;
  regler.min = 0;
  regler.max = tMax;

  let simZeit = 0;
  let tempo = 120;
  let laeuft = true;

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

  function render(t) {
    const aktive = daten.fahrten.filter(
      (f) => f.halte[0].an <= t && t <= f.halte[f.halte.length - 1].an
    );
    overlay.setProps({
      layers: [
        new TripsLayer({
          id: 'zuege-spur',
          data: trips,
          getPath: (d) => d.path,
          getTimestamps: (d) => d.timestamps,
          getColor: (d) => d.farbe,
          currentTime: t,
          trailLength: TRAIL_LAENGE_S,
          widthMinPixels: 3,
          capRounded: true,
          jointRounded: true,
          opacity: 0.7,
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
    uhrFahrt.textContent = `${daten.meta.betriebstag} · ${aktive.length} Züge unterwegs`;
    regler.value = t;
  }

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
