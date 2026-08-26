"""Tests der Replay-Interpolation. Aufruf: .venv/Scripts/python pipeline/test_interpolation.py

Die synthetischen Faelle sind von Hand nachgerechnet und dienen als
Vergleichswerte fuer den JS-Port (frontend/tests/interpolation.test.js),
beide Implementierungen muessen dieselben Zahlen liefern.
"""

import json
import math
from pathlib import Path

from interpolation import meter_zu_koord, position, zeit_zu_meter

ROOT = Path(__file__).resolve().parents[1]

# Synthetischer Minimalfall: 3 Shape-Punkte, 2 Halte
SHAPE = {
    "coords": [[10.0, 53.0], [10.0, 53.001], [10.0, 53.003]],
    "meter": [0, 111, 333],
}
HALTE = [
    {"name": "A", "an": 0, "ab": 10, "m": 0},
    {"name": "B", "an": 110, "ab": 120, "m": 333},
]
FAHRT = {"id": "test", "linie": "U1", "shape": "s1", "halte": HALTE}
SHAPES = {"s1": SHAPE}


def fast_gleich(a, b, toleranz=1e-9):
    return abs(a - b) <= toleranz


def test_synthetisch():
    # Klemmen vor Abfahrt und nach Ankunft
    assert zeit_zu_meter(HALTE, -5) == 0
    assert zeit_zu_meter(HALTE, 5) == 0        # Haltezeit am Start
    assert zeit_zu_meter(HALTE, 999) == 333
    assert zeit_zu_meter(HALTE, 115) == 333    # angekommen (t >= letzte Ankunft)

    # Fahrt: t=65 -> Fortschritt (65-10)/(110-10) = 0.55 -> m = 183.15
    assert fast_gleich(zeit_zu_meter(HALTE, 65), 183.15)

    # Meter -> Koordinate: m=183.15 liegt zwischen Punkt 2 (111 m) und 3 (333 m),
    # Anteil 72.15/222 = 0.325 -> lat = 53.001 + 0.325 * 0.002 = 53.00165
    lon, lat = meter_zu_koord(SHAPE, 183.15)
    assert fast_gleich(lon, 10.0) and fast_gleich(lat, 53.00165, 1e-6)

    # Exakt auf einem Shape-Punkt und an den Raendern
    assert meter_zu_koord(SHAPE, 111) == [10.0, 53.001]
    assert meter_zu_koord(SHAPE, -1) == [10.0, 53.0]
    assert meter_zu_koord(SHAPE, 9999) == [10.0, 53.003]

    # Gesamtkette
    lon, lat = position(FAHRT, SHAPES, 65)
    assert fast_gleich(lat, 53.00165, 1e-6)
    print("synthetische Faelle ok")


def test_echte_fahrt():
    daten = json.loads(
        (ROOT / "frontend" / "public" / "geo" / "testfahrt.json").read_text(encoding="utf-8")
    )
    fahrt = daten["fahrten"][0]
    halte = fahrt["halte"]
    shape = daten["shapes"][fahrt["shape"]]

    # An jedem Halt (Ankunftszeit) muss exakt der Meter-Wert des Halts herauskommen
    for h in halte:
        assert zeit_zu_meter(halte, h["an"]) == h["m"], h["name"]

    # Meter monoton nicht-fallend ueber die ganze Fahrt (1-Sekunden-Raster)
    # und plausible Hoechstgeschwindigkeit (U-Bahn faehrt keine 130 km/h)
    m_vorher = -1
    for t in range(halte[0]["ab"], halte[-1]["an"] + 1):
        m = zeit_zu_meter(halte, t)
        assert m >= m_vorher, f"Ruecksprung bei t={t}"
        assert m - m_vorher <= 36, f"unplausible Geschwindigkeit bei t={t}"
        m_vorher = m

    # Position am letzten Halt = letzter Shape-Punkt-Bereich (Endstation)
    lon, lat = position(fahrt, daten["shapes"], halte[-1]["an"])
    lon_ende, lat_ende = meter_zu_koord(shape, halte[-1]["m"])
    assert math.isclose(lon, lon_ende) and math.isclose(lat, lat_ende)
    print(f"echte Fahrt ok ({len(halte)} Halte, {halte[-1]['m'] / 1000:.1f} km)")


if __name__ == "__main__":
    test_synthetisch()
    test_echte_fahrt()
    print("alle Tests bestanden")
