import { defineConfig } from 'vite';

export default defineConfig(({ command }) => ({
  // GitHub Pages serviert unter /hvv_transit/, der Dev-Server weiter unter /
  base: command === 'build' ? '/hvv_transit/' : '/',
  optimizeDeps: {
    // maplibre-gl laedt seinen Tile-Worker relativ zum eigenen Modulpfad,
    // Vites Dep-Optimizer verschiebt das Modul und bricht damit den Pfad
    exclude: ['maplibre-gl'],
  },
}));
