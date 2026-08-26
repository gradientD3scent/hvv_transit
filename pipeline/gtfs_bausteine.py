"""Gemeinsame GTFS-Bausteine der Pipeline: Zeitparsing, UTM-Meter, Snapping.

Wird vom Testfahrt-Export (Task 4) und der Tages-ETL (Task 5) genutzt,
damit die verifizierte Logik nur einmal existiert.
"""

from pyproj import Transformer
from shapely.geometry import LineString, Point
from shapely.ops import substring

BETRIEBSTAG_BEGINN_S = 4 * 3600  # 04:00, bestaetigt gegen die Daten in Task 5
WGS84_ZU_UTM = Transformer.from_crs(4326, 25832, always_xy=True)


def gtfs_zeit_zu_sekunden(zeit: str) -> int:
    """GTFS-Zeit (auch ueber 24:00, z.B. 25:28:00) -> Sekunden seit Betriebstagesbeginn."""
    h, m, s = (int(teil) for teil in zeit.split(":"))
    return h * 3600 + m * 60 + s - BETRIEBSTAG_BEGINN_S


def utm_linestring(coords_wgs84: list) -> LineString:
    """Shape-Koordinaten ([lon, lat]) nach UTM 32N (EPSG:25832) projizieren."""
    return LineString([WGS84_ZU_UTM.transform(lon, lat) for lon, lat in coords_wgs84])


def kumulierte_meter(linie_utm: LineString) -> list[float]:
    """Kumulierte Streckenmeter je Shape-Punkt."""
    punkte = list(linie_utm.coords)
    meter = [0.0]
    for (x1, y1), (x2, y2) in zip(punkte, punkte[1:]):
        meter.append(meter[-1] + ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5)
    return meter


def snappe_halte(linie_utm: LineString, halte_wgs84: list, max_abstand: float = 100.0) -> list[float]:
    """Meter-Werte der Halte per Vorwaerts-Snapping.

    Jede Station wird nur auf dem Streckenrest ab dem Meter-Wert des vorherigen
    Halts gesucht (U3-Ring-Falle: Barmbek kommt zweimal vor, naives Snapping
    springt zurueck). Wirft ValueError, wenn ein Halt weiter als max_abstand
    von der Strecke entfernt liegt.

    Toleranz 100 m: U-Bahn-Stops liegen auf der Gleisachse (unter 3 m),
    S-Bahn-Stops bis ~20 m daneben (Bahnsteigmitte statt Gleis), und am
    Berliner Tor referenzieren S2/S7-Fahrten eine 86 m entfernte
    Bahnsteiggruppe. Echte Fehler wie ein falscher oder gedrehter Shape
    liegen im Kilometerbereich, die Validierung prueft zusaetzlich
    Monotonie und Geschwindigkeiten.
    """
    meter_werte = []
    m_vorher = 0.0
    for lon, lat in halte_wgs84:
        rest = substring(linie_utm, m_vorher, linie_utm.length)
        punkt = Point(WGS84_ZU_UTM.transform(lon, lat))
        abstand = rest.distance(punkt)
        if abstand > max_abstand:
            raise ValueError(f"Snapping-Abstand {abstand:.1f} m bei [{lon}, {lat}]")
        m = m_vorher + rest.project(punkt)
        meter_werte.append(m)
        m_vorher = m
    return meter_werte
