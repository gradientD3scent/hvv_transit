import { defineConfig } from 'vite';

export default defineConfig({
  optimizeDeps: {
    // maplibre-gl laedt seinen Tile-Worker relativ zum eigenen Modulpfad,
    // Vites Dep-Optimizer verschiebt das Modul und bricht damit den Pfad
    exclude: ['maplibre-gl'],
  },
});
