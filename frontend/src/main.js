import { Map as MaplibreMap, NavigationControl } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import './style.css';

const map = new MaplibreMap({
  container: 'map',
  style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
  center: [9.99, 53.55],
  zoom: 10.5,
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
});
