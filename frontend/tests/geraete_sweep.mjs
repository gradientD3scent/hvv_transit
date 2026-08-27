// Geräte-Sweep: prüft die App auf 12 Standard-Geräten (Playwright-Presets)
// gegen Layout-Invarianten (kein Overflow, Steuerzeile intakt, alle Chips
// sichtbar, keine Überlappungen). Screenshots je Gerät als Beifang.
//
// Läuft bewusst NICHT in npm test / CI (braucht einen Browser-Download):
//   npm install --no-save playwright && npx playwright install chromium
//   node tests/geraete_sweep.mjs [url] [screenshot-ordner]
// Ohne Argumente wird die Live-URL getestet.
import { chromium, devices } from 'playwright';

const URL = process.argv[2] ?? 'https://gradientd3scent.github.io/hvv_transit/';
const ORDNER = process.argv[3] ?? '.';

const GERAETE = [
  'Galaxy S9+',
  'iPhone SE',
  'iPhone 12',
  'Pixel 7',
  'iPhone 15 Pro Max',
  'iPad Mini',
  'iPad (gen 7)',
  'iPad Pro 11',
  'iPad Mini landscape',
  'iPad Pro 11 landscape',
];
const DESKTOPS = [
  ['Desktop 1280', { viewport: { width: 1280, height: 800 } }],
  ['Desktop 1920', { viewport: { width: 1920, height: 1080 } }],
];

async function pruefe(page) {
  return page.evaluate(() => {
    const fehler = [];
    const b = innerWidth;
    const h = innerHeight;
    const rect = (el) => (el ? el.getBoundingClientRect() : null);
    const drin = (r) => r && r.left >= -1 && r.top >= -1 && r.right <= b + 1 && r.bottom <= h + 1;
    const schneidet = (a, c) =>
      a && c && !(a.right <= c.left || c.right <= a.left || a.bottom <= c.top || c.bottom <= a.top);

    if (document.scrollingElement.scrollWidth > b + 1) {
      fehler.push(`horizontaler Overflow (${document.scrollingElement.scrollWidth} > ${b})`);
    }

    const st = rect(document.getElementById('steuerung'));
    if (!drin(st)) fehler.push('Steuerung ragt aus dem Viewport');

    const mitte = (el) => {
      const r = rect(el);
      return r ? r.top + r.height / 2 : NaN;
    };
    const gleicheZeile = (elemente, label) => {
      const mitten = elemente.map(mitte);
      if (Math.max(...mitten) - Math.min(...mitten) > 10) {
        fehler.push(`${label} umgebrochen (Mitten: ${mitten.map((z) => Math.round(z)).join(', ')})`);
      }
    };
    const tempoKnoepfe = [...document.querySelectorAll('#tempo-stufen button')];
    const tag = document.getElementById('tagwahl');
    const pp = document.getElementById('playpause');
    const info = document.getElementById('info-knopf');
    if (b > 360) {
      // Normalfall: alles auf einer Zeile
      gleicheZeile([tag, pp, tempoKnoepfe[0], tempoKnoepfe[3], info], 'Steuerzeile');
    } else {
      // 320er-Geraete: kontrollierter Umbruch, Gruppen bleiben intakt
      gleicheZeile([tag, pp, info], 'Datum/Play/Info');
      gleicheZeile([tempoKnoepfe[0], tempoKnoepfe[3]], 'Tempo-Zeile');
    }

    const chips = [...document.querySelectorAll('#legende button')];
    if (chips.length !== 9) fehler.push(`nur ${chips.length} Linien-Chips`);
    const draussen = chips.filter((c) => !drin(rect(c))).map((c) => c.textContent);
    if (draussen.length) fehler.push(`Chips ausserhalb: ${draussen.join(', ')}`);

    const attrib = rect(document.querySelector('.maplibregl-ctrl-bottom-right'));
    if (schneidet(attrib, st)) fehler.push('Attribution ueberlappt Steuerung');
    if (schneidet(attrib, rect(document.getElementById('legende')))) {
      fehler.push('Attribution ueberlappt Legende');
    }

    if (!drin(rect(document.getElementById('zeitregler')))) fehler.push('Zeitregler nicht komplett sichtbar');
    if (!drin(rect(document.getElementById('uhr')))) fehler.push('Uhr nicht komplett sichtbar');

    return { fehler, viewport: `${b}x${h}` };
  });
}

const browser = await chromium.launch();
const ergebnisse = [];

const faelle = [
  ...GERAETE.map((name) => [name, devices[name]]),
  ...DESKTOPS,
];

for (const [name, konfig] of faelle) {
  if (!konfig) {
    ergebnisse.push(`? ${name}: Preset unbekannt, uebersprungen`);
    continue;
  }
  const kontext = await browser.newContext(konfig);
  const page = await kontext.newPage();
  const konsole = [];
  page.on('pageerror', (e) => konsole.push(`JS-Fehler: ${e.message}`));
  page.on('requestfailed', (r) => konsole.push(`Request kaputt: ${r.url()}`));
  try {
    await page.goto(URL, { waitUntil: 'load', timeout: 60000 });
    await page.waitForTimeout(7000);
    const { fehler, viewport } = await pruefe(page);
    fehler.push(...konsole);
    const datei = name.replace(/[^a-z0-9]+/gi, '_').toLowerCase();
    await page.screenshot({ path: `${ORDNER}/sweep_${datei}.png` });
    ergebnisse.push(
      fehler.length
        ? `FEHLER ${name} (${viewport}):\n    - ${fehler.join('\n    - ')}`
        : `ok     ${name} (${viewport})`
    );
  } catch (e) {
    ergebnisse.push(`CRASH  ${name}: ${e.message.split('\n')[0]}`);
  }
  await kontext.close();
}

await browser.close();
console.log(ergebnisse.join('\n'));
