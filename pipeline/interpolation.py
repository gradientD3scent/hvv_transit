"""Referenz-Implementierung der Replay-Interpolation (Python, wird nach JS portiert).

Zweistufig gemaess Task-2-Schema:
  Zeit -> Meter:      linear zwischen den umgebenden Halten (konstante Geschwindigkeit),
                      waehrend einer Haltezeit (an..ab) steht der Zug
  Meter -> Koordinate: binaere Suche in der kumulierten meter-Liste des Shapes,
                      linear zwischen den zwei umgebenden Shape-Punkten

Die lineare Interpolation der Koordinaten passiert bewusst direkt in WGS84:
bei Shape-Punktabstaenden von wenigen Metern ist der Fehler vernachlaessigbar.
"""

from bisect import bisect_right


def zeit_zu_meter(halte: list[dict], t: float) -> float:
    """Streckenmeter der Fahrt zum Zeitpunkt t (Sekunden seit Betriebstagesbeginn).

    Vor der ersten Abfahrt und nach der letzten Ankunft wird an den Endhalten
    geklemmt (der Zug steht am Start- bzw. Zielgleis).
    """
    if t <= halte[0]["ab"]:
        return halte[0]["m"]
    if t >= halte[-1]["an"]:
        return halte[-1]["m"]

    for h1, h2 in zip(halte, halte[1:]):
        if h1["an"] <= t <= h1["ab"]:
            return h1["m"]
        if h1["ab"] < t < h2["an"]:
            fortschritt = (t - h1["ab"]) / (h2["an"] - h1["ab"])
            return h1["m"] + fortschritt * (h2["m"] - h1["m"])

    return halte[-1]["m"]


def meter_zu_koord(shape: dict, m: float) -> list[float]:
    """Koordinate [lon, lat] am Streckenmeter m eines Shapes ({coords, meter})."""
    meter = shape["meter"]
    coords = shape["coords"]

    if m <= meter[0]:
        return list(coords[0])
    if m >= meter[-1]:
        return list(coords[-1])

    # Index des ersten Punkts hinter m; m liegt zwischen i-1 und i
    i = bisect_right(meter, m)
    anteil = (m - meter[i - 1]) / (meter[i] - meter[i - 1])
    lon1, lat1 = coords[i - 1]
    lon2, lat2 = coords[i]
    return [lon1 + anteil * (lon2 - lon1), lat1 + anteil * (lat2 - lat1)]


def position(fahrt: dict, shapes: dict, t: float) -> list[float]:
    """Position [lon, lat] einer Fahrt zum Zeitpunkt t."""
    m = zeit_zu_meter(fahrt["halte"], t)
    return meter_zu_koord(shapes[fahrt["shape"]], m)
