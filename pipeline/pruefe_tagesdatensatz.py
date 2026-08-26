"""Prueft einen Tagesdatensatz auf Schema- und Fachinvarianten.

Aufruf:   .venv/Scripts/python pipeline/pruefe_tagesdatensatz.py data/tagesdatensatz_2026-09-16.json
Exitcode: 0 wenn alles ok, 1 bei Verstoessen (mit Report).

Invarianten je Fahrt:
- Linie und Shape existieren in den Top-Level-Bloecken
- mindestens 2 Halte, an <= ab je Halt, Zeiten ueber die Halte nicht fallend
- Meter-Werte streng aufsteigend (deckt die U3-Ring-Falle ab) und im Shape-Bereich
- Reisegeschwindigkeit: ueber 250 km/h ist ein Fehler (strukturell kaputt,
  vgl. Betriebspunkte-Fund mit 264 km/h), ueber 140 km/h nur eine Warnung,
  denn die minutengranular gestaffelten Fahrplanzeiten erzeugen bei kurzen
  Stationsabstaenden rechnerische Sprints (z.B. Garstedt -> Richtweg in 30 s)
Invarianten je Shape: len(coords) == len(meter), Meter nicht fallend.
"""

import json
import sys
from pathlib import Path

TEMPO_WARNUNG_MS = 140 / 3.6
TEMPO_FEHLER_MS = 250 / 3.6


def pruefe(pfad: Path) -> int:
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    fehler = []
    warnungen = []
    v2 = daten["meta"].get("version") == 2

    for pflicht in (("zeitraum",) if v2 else ("betriebstag",)) + ("quelle", "erzeugt"):
        if pflicht not in daten["meta"]:
            fehler.append(f"meta.{pflicht} fehlt")
    if "CC BY" not in daten["meta"].get("quelle", ""):
        fehler.append("meta.quelle ohne CC-BY-Attribution")

    if v2:
        # Kalenderblock: jeder Tag nicht leer, alle Service-Indizes gueltig
        anzahl_services = len(daten["services"])
        for datum, service_idx in daten["tage"].items():
            if not service_idx:
                fehler.append(f"Tag {datum} ohne Services")
            if any(not 0 <= i < anzahl_services for i in service_idx):
                fehler.append(f"Tag {datum}: ungueltiger Service-Index")
        # v2-Halte ([station, an, ab, m]) fuer die Invarianten normalisieren
        anzahl_stationen = len(daten["stationen"])
        for f in daten["fahrten"]:
            if not 0 <= f["s"] < anzahl_services:
                fehler.append(f"Fahrt {f['id']}: ungueltiger Service-Index")
            if any(not 0 <= h[0] < anzahl_stationen for h in f["halte"]):
                fehler.append(f"Fahrt {f['id']}: ungueltiger Stations-Index")
            f["halte"] = [
                {"name": daten["stationen"][s], "an": an, "ab": ab, "m": m}
                for s, an, ab, m in f["halte"]
            ]

    for sid, shape in daten["shapes"].items():
        if len(shape["coords"]) != len(shape["meter"]):
            fehler.append(f"Shape {sid}: coords/meter unterschiedlich lang")
        if any(b < a for a, b in zip(shape["meter"], shape["meter"][1:])):
            fehler.append(f"Shape {sid}: Meter fallen")

    max_tempo = 0.0
    for f in daten["fahrten"]:
        kontext = f"Fahrt {f['id']} ({f['linie']})"
        if f["linie"] not in daten["linien"]:
            fehler.append(f"{kontext}: Linie unbekannt")
            continue
        if f["shape"] not in daten["shapes"]:
            fehler.append(f"{kontext}: Shape unbekannt")
            continue
        halte = f["halte"]
        if len(halte) < 2:
            fehler.append(f"{kontext}: unter 2 Halte")
            continue

        shape_ende = daten["shapes"][f["shape"]]["meter"][-1]
        for h in halte:
            if h["an"] > h["ab"]:
                fehler.append(f"{kontext}, {h['name']}: an > ab")
            if not -1 <= h["m"] <= shape_ende + 1:
                fehler.append(f"{kontext}, {h['name']}: m ausserhalb des Shapes")

        for h1, h2 in zip(halte, halte[1:]):
            if h2["an"] < h1["ab"]:
                fehler.append(f"{kontext}, {h2['name']}: Zeit faellt")
            if h2["m"] <= h1["m"]:
                fehler.append(f"{kontext}, {h2['name']}: Meter nicht aufsteigend")
            dt = h2["an"] - h1["ab"]
            dm = h2["m"] - h1["m"]
            if dt <= 0 and dm > 0:
                fehler.append(f"{kontext}, {h2['name']}: Bewegung ohne Fahrzeit")
            elif dt > 0:
                tempo = dm / dt
                max_tempo = max(max_tempo, tempo)
                if tempo > TEMPO_FEHLER_MS:
                    fehler.append(f"{kontext}, {h2['name']}: {tempo * 3.6:.0f} km/h")
                elif tempo > TEMPO_WARNUNG_MS:
                    warnungen.append(f"{kontext}, {h1['name']} -> {h2['name']}: {tempo * 3.6:.0f} km/h")

    # Report
    je_linie = {}
    for f in daten["fahrten"]:
        je_linie[f["linie"]] = je_linie.get(f["linie"], 0) + 1
    zeiten = [h[k] for f in daten["fahrten"] for h in f["halte"] for k in ("an", "ab")]

    def uhr(t):
        s = t + 4 * 3600
        return f"{s // 3600:02d}:{s % 3600 // 60:02d}"

    kopf = (f"{daten['meta']['zeitraum'][0]} bis {daten['meta']['zeitraum'][1]}, {len(daten['tage'])} Betriebstage"
            if v2 else f"Betriebstag {daten['meta']['betriebstag']}")
    print(f"{kopf}: {len(daten['fahrten'])} Fahrten, "
          f"{len(daten['shapes'])} Shapes, {len(daten['linien'])} Linien")
    print("je Linie:", ", ".join(f"{l} {n}" for l, n in sorted(je_linie.items())))
    print(f"Zeitspanne {uhr(min(zeiten))} bis {uhr(max(zeiten))}, "
          f"max. Reisegeschwindigkeit {max_tempo * 3.6:.0f} km/h")
    print(f"Dateigroesse {pfad.stat().st_size / 1024 / 1024:.1f} MB")

    if warnungen:
        print(f"\n{len(warnungen)} Tempo-Warnungen (Fahrplan-Rundung, nicht fatal), Beispiele:")
        for w in warnungen[:5]:
            print(" ", w)

    if fehler:
        print(f"\n{len(fehler)} VERSTOESSE:")
        for f in fehler[:20]:
            print(" ", f)
        if len(fehler) > 20:
            print(f"  ... und {len(fehler) - 20} weitere")
        return 1
    print("\nalle Invarianten erfuellt")
    return 0


if __name__ == "__main__":
    sys.exit(pruefe(Path(sys.argv[1])))
