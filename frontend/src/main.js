import { Map as MaplibreMap, NavigationControl } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import './style.css';

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
});
