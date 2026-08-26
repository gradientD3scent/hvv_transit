"""Exportiert eine echte U1-Fahrt als Mini-Tagesdatensatz im Task-2-Schema.

Eingabe:  data/*.csv (HVV GTFS) + linien_farben.json
Ausgabe:  frontend/public/geo/testfahrt.json
Aufruf:   .venv/Scripts/python pipeline/export_testfahrt.py

Vorgriff auf die ETL (Task 5) im Kleinen: kumulierte Shape-Meter in UTM 32N,
Haltezeiten als Sekunden seit Betriebstagesbeginn (04:00), Meter-Werte der
Halte per Vorwaerts-Snapping (jede Station wird nur auf dem Streckenrest ab
dem vorherigen Halt gesucht, siehe U3-Ring-Falle im Projekt-Brief).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
from pyproj import Transformer
from shapely.geometry import LineString, Point
from shapely.ops import substring

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
FARBEN = json.loads((ROOT / "linien_farben.json").read_text(encoding="utf-8"))
ZIEL = ROOT / "frontend" / "public" / "geo" / "testfahrt.json"

BETRIEBSTAG_BEGINN_S = 4 * 3600  # 04:00, Arbeitshypothese aus dem Brief
LINIE = "U1"

WGS84_ZU_UTM = Transformer.from_crs(4326, 25832, always_xy=True)


def gtfs_zeit_zu_sekunden(zeit: str) -> int:
    """GTFS-Zeit (auch ueber 24:00, z.B. 25:28:00) -> Sekunden seit Betriebstagesbeginn."""
    h, m, s = (int(teil) for teil in zeit.split(":"))
    return h * 3600 + m * 60 + s - BETRIEBSTAG_BEGINN_S


def lade_fahrt(con: duckdb.DuckDBPyConnection):
    """Waehlt deterministisch eine vormittaegliche U1-Fahrt mit maximaler Haltezahl."""
    return con.execute(f"""
        WITH u1 AS (
            SELECT route_id FROM read_csv_auto('{(DATA / "routes.csv").as_posix()}')
            WHERE route_type = 402 AND route_short_name = '{LINIE}'
        ),
        u1_trips AS (
            SELECT t.trip_id, t.shape_id
            FROM read_csv_auto('{(DATA / "trips.csv").as_posix()}') t
            JOIN u1 USING (route_id)
        ),
        kandidaten AS (
            SELECT st.trip_id, COUNT(*) AS halte, MIN(st.departure_time) AS start
            FROM read_csv_auto('{(DATA / "stop_times.csv").as_posix()}',
                               types={{'arrival_time': 'VARCHAR', 'departure_time': 'VARCHAR'}}) st
            JOIN u1_trips USING (trip_id)
            GROUP BY st.trip_id
            HAVING start BETWEEN '08:00:00' AND '12:00:00'
        )
        SELECT k.trip_id, t.shape_id, k.halte
        FROM kandidaten k JOIN u1_trips t USING (trip_id)
        ORDER BY k.halte DESC, k.start, k.trip_id
        LIMIT 1
    """).fetchone()


def main() -> None:
    con = duckdb.connect()
    trip_id, shape_id, _ = lade_fahrt(con)

    shape_punkte = con.execute(f"""
        SELECT shape_pt_lon, shape_pt_lat
        FROM read_csv_auto('{(DATA / "shapes.csv").as_posix()}')
        WHERE shape_id = ? ORDER BY shape_pt_sequence
    """, [shape_id]).fetchall()

    halte_raw = con.execute(f"""
        SELECT s.stop_name, st.arrival_time, st.departure_time, s.stop_lon, s.stop_lat
        FROM read_csv_auto('{(DATA / "stop_times.csv").as_posix()}',
                           types={{'arrival_time': 'VARCHAR', 'departure_time': 'VARCHAR'}}) st
        JOIN read_csv_auto('{(DATA / "stops.csv").as_posix()}') s USING (stop_id)
        WHERE st.trip_id = ?
          -- Durchfahrts-Betriebspunkte (Tarifgrenzen) sind keine Halte
          AND NOT (COALESCE(st.pickup_type, 0) = 1 AND COALESCE(st.drop_off_type, 0) = 1)
        ORDER BY st.stop_sequence
    """, [str(trip_id)]).fetchall()

    # Shape nach UTM 32N projizieren und kumulierte Meter je Punkt berechnen
    utm_punkte = [WGS84_ZU_UTM.transform(lon, lat) for lon, lat in shape_punkte]
    linie_utm = LineString(utm_punkte)
    meter = [0]
    for (x1, y1), (x2, y2) in zip(utm_punkte, utm_punkte[1:]):
        meter.append(meter[-1] + ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5)

    # Vorwaerts-Snapping: jeden Halt nur auf dem Streckenrest ab dem Vorgaenger suchen
    halte = []
    m_vorher = 0.0
    for name, an, ab, lon, lat in halte_raw:
        rest = substring(linie_utm, m_vorher, linie_utm.length)
        punkt = Point(WGS84_ZU_UTM.transform(lon, lat))
        m = m_vorher + rest.project(punkt)
        abstand = rest.distance(punkt)
        if abstand > 10:
            raise SystemExit(f"Snapping-Abstand {abstand:.1f} m bei {name}, Abbruch")
        halte.append({
            "name": name,
            "an": gtfs_zeit_zu_sekunden(an),
            "ab": gtfs_zeit_zu_sekunden(ab),
            "m": round(m),
        })
        m_vorher = m

    meter_werte = [h["m"] for h in halte]
    assert meter_werte == sorted(meter_werte), "Meter-Werte nicht aufsteigend"

    datensatz = {
        "meta": {
            "quelle": "HVV GTFS via Transparenzportal Hamburg, CC BY 4.0",
            "erzeugt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "hinweis": "Einzelfahrt-Prototyp (Task 4), Betriebstag-Zuordnung folgt mit der ETL (Task 5)",
        },
        "linien": {LINIE: FARBEN[LINIE]},
        "shapes": {
            str(shape_id): {
                "coords": [[round(lon, 6), round(lat, 6)] for lon, lat in shape_punkte],
                "meter": [round(m) for m in meter],
            }
        },
        "fahrten": [{
            "id": str(trip_id),
            "linie": LINIE,
            "shape": str(shape_id),
            "halte": halte,
        }],
    }

    ZIEL.write_text(json.dumps(datensatz, ensure_ascii=False), encoding="utf-8")

    dauer = halte[-1]["an"] - halte[0]["ab"]
    print(f"Trip {trip_id} (Shape {shape_id}): {len(halte)} Halte, "
          f"{halte[0]['name']} -> {halte[-1]['name']}")
    print(f"Strecke {halte[-1]['m'] / 1000:.1f} km, Fahrzeit {dauer // 60} min, "
          f"Shape-Punkte: {len(shape_punkte)}")
    print(f"-> {ZIEL.relative_to(ROOT)} ({ZIEL.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
