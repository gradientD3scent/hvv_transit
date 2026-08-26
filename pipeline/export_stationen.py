"""Exportiert die Stationen der 9 U-/S-Bahn-Linien als GeoJSON fuers Frontend.

Eingabe:  data/*.csv (HVV GTFS, Dateien als .csv umbenannt)
Ausgabe:  frontend/public/geo/stationen.geojson
Aufruf:   .venv/Scripts/python pipeline/export_stationen.py

Dedup-Logik (parent_station ist im HVV-Feed fuer U-/S-Stops nicht gepflegt):
- Events mit pickup_type = 1 UND drop_off_type = 1 sind Durchfahrts-
  Betriebspunkte (z.B. Tarifgrenzen wie "349000"), keine Stationen: filtern
- DHID-Stops (de:02000:16:1:2): Station = die ersten 3 ID-Segmente (IFOPT-Ebene)
- Pseudo-Duplikate wie "Barmbek(2)" werden per Namensbasis + Distanz gemergt
"""

import json
import math
import re
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ZIEL = ROOT / "frontend" / "public" / "geo" / "stationen.geojson"

QUERY = f"""
WITH us_routes AS (
    SELECT route_id, route_short_name AS linie
    FROM read_csv_auto('{(DATA / "routes.csv").as_posix()}')
    WHERE route_type IN (402, 109)
),
us_trips AS (
    SELECT t.trip_id, r.linie
    FROM read_csv_auto('{(DATA / "trips.csv").as_posix()}') t
    JOIN us_routes r USING (route_id)
),
stop_events AS (
    SELECT DISTINCT st.stop_id, tr.linie
    FROM read_csv_auto('{(DATA / "stop_times.csv").as_posix()}') st
    JOIN us_trips tr USING (trip_id)
    WHERE NOT (COALESCE(st.pickup_type, 0) = 1 AND COALESCE(st.drop_off_type, 0) = 1)
)
SELECT s.stop_id, s.stop_name, s.stop_lon, s.stop_lat, list_sort(list(DISTINCT e.linie))
FROM stop_events e
JOIN read_csv_auto('{(DATA / "stops.csv").as_posix()}') s ON s.stop_id = e.stop_id
GROUP BY s.stop_id, s.stop_name, s.stop_lon, s.stop_lat
"""


def distanz_m(lon1, lat1, lon2, lat2):
    """Haversine-Distanz in Metern, fuer die kleinen Abstaende hier voellig ausreichend."""
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


def main() -> None:
    rows = duckdb.connect().execute(QUERY).fetchall()

    # Schluessel -> Liste der Gleis-Stops (name, lon, lat, linien)
    stationen: dict[str, list] = {}
    for stop_id, name, lon, lat, linien in rows:
        kern = ":".join(stop_id.split(":")[:3]) if stop_id.startswith("de:") else stop_id
        stationen.setdefault(kern, []).append((name, lon, lat, linien))

    features = []
    for kern, mitglieder in stationen.items():
        namen = [m[0] for m in mitglieder]
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [
                    round(sum(m[1] for m in mitglieder) / len(mitglieder), 6),
                    round(sum(m[2] for m in mitglieder) / len(mitglieder), 6),
                ],
            },
            "properties": {
                "id": kern,
                "name": min(namen),
                "linien": sorted({l for m in mitglieder for l in m[3]}),
            },
        })
    # Duplikat-Eintraege wie "Barmbek(2)" (Pseudo-DHID neben der echten Station)
    # in ihre Hauptstation mergen: gleicher Name ohne (N)-Suffix und unter 200 m
    nach_name = {f["properties"]["name"]: f for f in features}
    for f in list(features):
        name = f["properties"]["name"]
        basis = re.sub(r"\(\d+\)$", "", name)
        haupt = nach_name.get(basis)
        if basis == name or haupt is None:
            continue
        d = distanz_m(*f["geometry"]["coordinates"], *haupt["geometry"]["coordinates"])
        if d < 200:
            haupt["properties"]["linien"] = sorted(
                set(haupt["properties"]["linien"]) | set(f["properties"]["linien"])
            )
            features.remove(f)
            print(f"gemergt: {name} -> {basis} ({d:.0f} m)")

    features.sort(key=lambda f: f["properties"]["name"])

    ZIEL.parent.mkdir(parents=True, exist_ok=True)
    geojson = {"type": "FeatureCollection", "features": features}
    ZIEL.write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")

    linien = sorted({l for f in features for l in f["properties"]["linien"]})
    print(f"{len(features)} Stationen, Linien: {', '.join(linien)}")
    print(f"-> {ZIEL.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
