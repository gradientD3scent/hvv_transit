import { defineConfig } from 'vite';

export default defineConfig(({ command }) => ({
  // GitHub Pages serviert unter /hvv_transit/, der Dev-Server weiter unter /
  base: command === 'build' ? '/hvv_transit/' : '/',
}));
