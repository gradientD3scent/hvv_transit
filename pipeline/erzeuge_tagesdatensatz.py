"""Erzeugt den Tagesdatensatz (Replay-Format, Task-2-Schema) fuer einen Betriebstag.

Eingabe:  data/*.csv (HVV GTFS) + linien_farben.json
Ausgabe:  data/tagesdatensatz_{tag}.json
Aufruf:   .venv/Scripts/python pipeline/erzeuge_tagesdatensatz.py --tag 2026-09-16

Regeln (siehe CLAUDE.md und Projekt-Brief):
- nur U-Bahn (402) und S-Bahn (109), Gruppierung ueber route_short_name
- aktive service_ids = calendar (Wochentag + Zeitraum) plus/minus calendar_dates
- Durchfahrts-Betriebspunkte (pickup_type = drop_off_type = 1) sind keine Halte
- Shapes mit unter 3 Punkten sind Ausreisser, ihre Fahrten werden verworfen
- Snapping wird pro eindeutigem Laufweg (shape_id, Haltefolge) gecacht
"""

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
from gtfs_bausteine import gtfs_zeit_zu_sekunden, kumulierte_meter, snappe_halte, utm_linestring

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
FARBEN = json.loads((ROOT / "linien_farben.json").read_text(encoding="utf-8"))

WOCHENTAGSSPALTEN = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def lade_fahrten(con: duckdb.DuckDBPyConnection, tag: date) -> list:
    """Alle U-/S-Bahn-Fahrten des Betriebstags: (trip_id, linie, shape_id)."""
    tag_int = int(tag.strftime("%Y%m%d"))
    spalte = WOCHENTAGSSPALTEN[tag.weekday()]
    return con.execute(f"""
        WITH us_routes AS (
            SELECT route_id, route_short_name AS linie
            FROM read_csv_auto('{(DATA / "routes.csv").as_posix()}')
            WHERE route_type IN (402, 109)
        ),
        regulaer AS (
            SELECT service_id FROM read_csv_auto('{(DATA / "calendar.csv").as_posix()}')
            WHERE start_date <= {tag_int} AND end_date >= {tag_int} AND {spalte} = 1
        ),
        entfernt AS (
            SELECT service_id FROM read_csv_auto('{(DATA / "calendar_dates.csv").as_posix()}')
            WHERE date = {tag_int} AND exception_type = 2
        ),
        ergaenzt AS (
            SELECT service_id FROM read_csv_auto('{(DATA / "calendar_dates.csv").as_posix()}')
            WHERE date = {tag_int} AND exception_type = 1
        ),
        aktiv AS (
            (SELECT service_id FROM regulaer EXCEPT SELECT service_id FROM entfernt)
            UNION
            SELECT service_id FROM ergaenzt
        )
        SELECT t.trip_id, r.linie, t.shape_id
        FROM read_csv_auto('{(DATA / "trips.csv").as_posix()}') t
        JOIN us_routes r USING (route_id)
        JOIN aktiv USING (service_id)
    """).fetchall()


def lade_halte(con: duckdb.DuckDBPyConnection, trip_ids: list) -> dict:
    """Halte je Fahrt (Betriebspunkte gefiltert): trip_id -> [(stop_id, name, an, ab, lon, lat)]."""
    con.execute("CREATE OR REPLACE TEMP TABLE gesuchte_trips (trip_id VARCHAR)")
    con.executemany("INSERT INTO gesuchte_trips VALUES (?)", [[t] for t in trip_ids])
    zeilen = con.execute(f"""
        SELECT st.trip_id, s.stop_id, s.stop_name, st.arrival_time, st.departure_time,
               s.stop_lon, s.stop_lat
        FROM read_csv_auto('{(DATA / "stop_times.csv").as_posix()}',
                           types={{'arrival_time': 'VARCHAR', 'departure_time': 'VARCHAR'}}) st
        JOIN gesuchte_trips g ON CAST(st.trip_id AS VARCHAR) = g.trip_id
        JOIN read_csv_auto('{(DATA / "stops.csv").as_posix()}') s USING (stop_id)
        WHERE NOT (COALESCE(st.pickup_type, 0) = 1 AND COALESCE(st.drop_off_type, 0) = 1)
        ORDER BY st.trip_id, st.stop_sequence
    """).fetchall()
    halte: dict[str, list] = {}
    for trip_id, *rest in zeilen:
        halte.setdefault(str(trip_id), []).append(tuple(rest))
    return halte


def lade_shapes(con: duckdb.DuckDBPyConnection, shape_ids: set) -> dict:
    """Shape-Geometrien (unter 3 Punkten gefiltert): shape_id -> [[lon, lat], ...]."""
    con.execute("CREATE OR REPLACE TEMP TABLE gesuchte_shapes (shape_id VARCHAR)")
    con.executemany("INSERT INTO gesuchte_shapes VALUES (?)", [[s] for s in shape_ids])
    zeilen = con.execute(f"""
        SELECT s.shape_id, list([s.shape_pt_lon, s.shape_pt_lat] ORDER BY s.shape_pt_sequence)
        FROM read_csv_auto('{(DATA / "shapes.csv").as_posix()}') s
        JOIN gesuchte_shapes g ON CAST(s.shape_id AS VARCHAR) = g.shape_id
        GROUP BY s.shape_id
        HAVING COUNT(*) >= 3
    """).fetchall()
    return {str(shape_id): coords for shape_id, coords in zeilen}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", type=date.fromisoformat, default=date(2026, 9, 16))
    args = parser.parse_args()

    con = duckdb.connect()
    fahrten_roh = lade_fahrten(con, args.tag)
    if not fahrten_roh:
        raise SystemExit(f"Keine Fahrten am {args.tag}, Datum im Feed-Zeitraum?")

    halte_je_trip = lade_halte(con, [str(t) for t, _, _ in fahrten_roh])
    shapes_roh = lade_shapes(con, {str(s) for _, _, s in fahrten_roh})

    # Geometrie einmal je Shape aufbereiten
    shapes_utm = {sid: utm_linestring(coords) for sid, coords in shapes_roh.items()}
    shapes_block = {
        sid: {
            "coords": [[round(lon, 6), round(lat, 6)] for lon, lat in coords],
            "meter": [round(m) for m in kumulierte_meter(shapes_utm[sid])],
        }
        for sid, coords in shapes_roh.items()
    }

    # Snapping je eindeutigem Laufweg cachen: Fahrten desselben Laufwegs
    # teilen sich die Meter-Werte ihrer Halte
    snap_cache: dict[tuple, list[float] | None] = {}
    fahrten = []
    verworfen = {"shape": 0, "halte": 0, "snapping": 0}

    for trip_id, linie, shape_id in fahrten_roh:
        trip_id, shape_id = str(trip_id), str(shape_id)
        halte_roh = halte_je_trip.get(trip_id, [])
        if shape_id not in shapes_roh:
            verworfen["shape"] += 1
            continue
        if len(halte_roh) < 2:
            verworfen["halte"] += 1
            continue

        laufweg = (shape_id, tuple(h[0] for h in halte_roh))
        if laufweg not in snap_cache:
            try:
                snap_cache[laufweg] = snappe_halte(
                    shapes_utm[shape_id], [(lon, lat) for _, _, _, _, lon, lat in halte_roh]
                )
            except ValueError:
                snap_cache[laufweg] = None
        if snap_cache[laufweg] is None:
            verworfen["snapping"] += 1
            continue

        fahrten.append({
            "id": trip_id,
            "linie": linie,
            "shape": shape_id,
            "halte": [
                {"name": name, "an": gtfs_zeit_zu_sekunden(an), "ab": gtfs_zeit_zu_sekunden(ab), "m": round(m)}
                for (_, name, an, ab, _, _), m in zip(halte_roh, snap_cache[laufweg])
            ],
        })

    fahrten.sort(key=lambda f: (f["halte"][0]["ab"], f["id"]))

    # nur tatsaechlich referenzierte Shapes und Linien in die Datei
    genutzte_shapes = {f["shape"] for f in fahrten}
    genutzte_linien = {f["linie"] for f in fahrten}

    datensatz = {
        "meta": {
            "betriebstag": args.tag.isoformat(),
            "quelle": "HVV GTFS via Transparenzportal Hamburg, CC BY 4.0",
            "erzeugt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        "linien": {l: FARBEN[l] for l in sorted(genutzte_linien)},
        "shapes": {sid: shapes_block[sid] for sid in sorted(genutzte_shapes)},
        "fahrten": fahrten,
    }

    ziel = DATA / f"tagesdatensatz_{args.tag.isoformat()}.json"
    ziel.write_text(json.dumps(datensatz, ensure_ascii=False), encoding="utf-8")

    # Betriebstagesgrenzen-Check (offene Entscheidung aus dem Brief):
    # Wenn Nachtfahrten konsequent als ueber-24:00-Zeiten am Vortag codiert sind,
    # darf keine Fahrt vor 04:00 (relativ < 0) starten.
    vor_4 = sum(1 for f in fahrten if f["halte"][0]["ab"] < 0)
    ueber_24 = sum(1 for f in fahrten if f["halte"][-1]["an"] >= 20 * 3600)
    je_linie = {}
    for f in fahrten:
        je_linie[f["linie"]] = je_linie.get(f["linie"], 0) + 1

    print(f"Betriebstag {args.tag} ({WOCHENTAGSSPALTEN[args.tag.weekday()]})")
    print(f"{len(fahrten)} Fahrten, {len(genutzte_shapes)} Shapes, "
          f"{len(snap_cache)} eindeutige Laufwege")
    print("je Linie:", ", ".join(f"{l} {n}" for l, n in sorted(je_linie.items())))
    print(f"verworfen: {verworfen}")
    print(f"Grenz-Check: {vor_4} Fahrten starten vor 04:00, "
          f"{ueber_24} Fahrten enden nach Mitternacht (ueber 24:00 codiert)")
    print(f"-> {ziel.relative_to(ROOT)} ({ziel.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
