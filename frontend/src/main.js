import { TripsLayer } from '@deck.gl/geo-layers';
import { ScatterplotLayer } from '@deck.gl/layers';
import { MapboxOverlay } from '@deck.gl/mapbox';
import { Map as MaplibreMap, NavigationControl } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import './style.css';
import { position } from './interpolation.js';
import { fahrtZuTrip, hexZuRgb } from './trips_konverter.js';

const ZEITRAFFER = 60;
const BETRIEBSTAG_BEGINN_S = 4 * 3600;

const map = new MaplibreMap({
  container: 'map',
  style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
  center: [9.99, 53.55],
  zoom: 10.5,
  attributionControl: {
    customAttribution: [
      'Fahrplandaten: HVV via Transparenzportal Hamburg (CC BY 4.0)',
      'Verwaltungsgrenzen: FHH, Landesbetrieb Geoinformation und Vermessung (dl-de/by-2-0)',
    ],
  },
});

map.addControl(new NavigationControl(), 'top-right');

function formatUhrzeit(t) {
  const s = Math.floor(t + BETRIEBSTAG_BEGINN_S) % 86400;
  const hh = String(Math.floor(s / 3600)).padStart(2, '0');
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  return `${hh}:${mm}:${ss}`;
}

async function starteTestfahrt() {
  const daten = await (await fetch('/geo/testfahrt.json')).json();
  const fahrt = daten.fahrten[0];
  const halte = fahrt.halte;
  const trip = { ...fahrtZuTrip(fahrt, daten.shapes), farbe: hexZuRgb(daten.linien[fahrt.linie].farbe) };

  // etwas Vor- und Nachlauf, damit der Zug sichtbar am Gleis steht
  const start = halte[0].an - 30;
  const ende = halte[halte.length - 1].an + 30;

  const overlay = new MapboxOverlay({ layers: [] });
  map.addControl(overlay);

  const uhr = document.getElementById('uhr');
  const uhrZeit = document.getElementById('uhr-zeit');
  const uhrFahrt = document.getElementById('uhr-fahrt');
  uhrFahrt.textContent = `${fahrt.linie} ${halte[0].name} → ${halte[halte.length - 1].name} (${ZEITRAFFER}x)`;
  uhr.hidden = false;

  const t0 = performance.now();
  function tick(jetzt) {
    // Simulationszeit laeuft im Zeitraffer und springt am Ende zurueck zum Start
    const t = start + (((jetzt - t0) / 1000) * ZEITRAFFER) % (ende - start);
    overlay.setProps({
      layers: [
        // Nachleuchtspur: GPU interpoliert zwischen den Vertex-Zeitstempeln
        new TripsLayer({
          id: 'zuege-spur',
          data: [trip],
          getPath: (d) => d.path,
          getTimestamps: (d) => d.timestamps,
          getColor: (d) => d.farbe,
          currentTime: t,
          trailLength: 180,
          widthMinPixels: 4,
          capRounded: true,
          jointRounded: true,
          opacity: 0.85,
        }),
        // heller Zugpunkt an der Spitze, Position aus unserer Interpolation
        new ScatterplotLayer({
          id: 'zuege-punkte',
          data: [fahrt],
          getPosition: (d) => position(d, daten.shapes, t),
          getFillColor: [255, 255, 255],
          radiusMinPixels: 4,
          updateTriggers: { getPosition: t },
        }),
      ],
    });
    uhrZeit.textContent = formatUhrzeit(t);
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

map.on('load', () => {
  map.addSource('bezirke', {
    type: 'geojson',
    data: '/geo/bezirke.geojson',
  });

  // vor dem ersten Symbol-Layer einfuegen, damit Ortsnamen lesbar bleiben
  const firstSymbolId = map.getStyle().layers.find((l) => l.type === 'symbol')?.id;

  map.addLayer(
    {
      id: 'bezirke-grenzen',
      type: 'line',
      source: 'bezirke',
      paint: {
        'line-color': '#56606f',
        'line-width': 1,
        'line-opacity': 0.45,
      },
    },
    firstSymbolId
  );

  map.addSource('liniennetz', {
    type: 'geojson',
    data: '/geo/liniennetz.geojson',
  });

  map.addLayer(
    {
      id: 'liniennetz-linien',
      type: 'line',
      source: 'liniennetz',
      layout: {
        'line-join': 'round',
        'line-cap': 'round',
      },
      paint: {
        // Farbe kommt aus den Feature-Properties (von der Pipeline gebacken)
        'line-color': ['get', 'farbe'],
        'line-width': ['interpolate', ['linear'], ['zoom'], 9, 1.2, 12, 2.5, 14, 4],
        'line-opacity': 0.85,
      },
    },
    firstSymbolId
  );

  map.addSource('stationen', {
    type: 'geojson',
    data: '/geo/stationen.geojson',
  });

  map.addLayer(
    {
      id: 'stationen-punkte',
      type: 'circle',
      source: 'stationen',
      paint: {
        // Radius waechst mit dem Zoom, sonst verklumpen die Punkte im Zentrum
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 9, 1.5, 12, 3, 14, 4.5],
        'circle-color': '#dbe2ee',
        'circle-opacity': 0.85,
      },
    },
    firstSymbolId
  );

  starteTestfahrt();
});
