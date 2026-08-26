"""Exportiert das U-/S-Bahn-Liniennetz als GeoJSON fuers Frontend.

Eingabe:  data/*.csv (HVV GTFS) + linien_farben.json
Ausgabe:  frontend/public/geo/liniennetz.geojson (ein Feature pro Linie)
Aufruf:   .venv/Scripts/python pipeline/export_liniennetz.py

Pro Linie werden alle Shape-Varianten (Richtungen, Kurzlaeufer, Aeste) mit
shapely vereinigt und zusammengefuehrt, damit ueberlappende Streckenteile
nur einmal in der Datei liegen. Shapes mit unter 3 Punkten sind Ausreisser
(Betriebsfahrten) und werden gefiltert.
"""

import json
from collections import defaultdict
from pathlib import Path

import duckdb
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge, unary_union

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
FARBEN = json.loads((ROOT / "linien_farben.json").read_text(encoding="utf-8"))
ZIEL = ROOT / "frontend" / "public" / "geo" / "liniennetz.geojson"

QUERY = f"""
WITH us_routes AS (
    SELECT route_id, route_short_name AS linie
    FROM read_csv_auto('{(DATA / "routes.csv").as_posix()}')
    WHERE route_type IN (402, 109)
),
linien_shapes AS (
    SELECT DISTINCT r.linie, t.shape_id
    FROM read_csv_auto('{(DATA / "trips.csv").as_posix()}') t
    JOIN us_routes r USING (route_id)
)
SELECT ls.linie, ls.shape_id,
       list([s.shape_pt_lon, s.shape_pt_lat] ORDER BY s.shape_pt_sequence) AS coords
FROM read_csv_auto('{(DATA / "shapes.csv").as_posix()}') s
JOIN linien_shapes ls USING (shape_id)
GROUP BY ls.linie, ls.shape_id
HAVING COUNT(*) >= 3
"""


def main() -> None:
    rows = duckdb.connect().execute(QUERY).fetchall()

    pro_linie: dict[str, list[LineString]] = defaultdict(list)
    for linie, _shape_id, coords in rows:
        pro_linie[linie].append(LineString(coords))

    features = []
    for linie in sorted(pro_linie):
        vereinigt = linemerge(unary_union(pro_linie[linie]))
        if isinstance(vereinigt, LineString):
            vereinigt = MultiLineString([vereinigt])
        teile = [
            [[round(x, 6), round(y, 6)] for x, y in teil.coords]
            for teil in vereinigt.geoms
        ]
        features.append({
            "type": "Feature",
            "geometry": {"type": "MultiLineString", "coordinates": teile},
            "properties": {"linie": linie, "farbe": FARBEN[linie]["farbe"]},
        })
        punkte = sum(len(t) for t in teile)
        print(f"{linie}: {len(pro_linie[linie])} Shapes -> {len(teile)} Teilstuecke, {punkte} Punkte")

    ZIEL.parent.mkdir(parents=True, exist_ok=True)
    ZIEL.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"-> {ZIEL.relative_to(ROOT)} ({ZIEL.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
