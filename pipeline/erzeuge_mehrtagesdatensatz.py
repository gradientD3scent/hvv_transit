"""Erzeugt den Mehrtages-Datensatz (Schema v2) fuer alle Betriebstage des Feeds.

Eingabe:  data/*.csv (HVV GTFS) + linien_farben.json
Ausgabe:  data/mehrtagesdatensatz.json (--frontend: zusaetzlich ins Frontend)
Aufruf:   .venv/Scripts/python pipeline/erzeuge_mehrtagesdatensatz.py --frontend

Idee Schema v2: Die Tagesdateien aus v1 sind zu ~95 Prozent redundant, jeder
Betriebstag ist nur eine Auswahl aus denselben ~15.000 Fahrten. v2 speichert
deshalb alle Fahrten einmal (Stationsnamen als Tabelle, Halte als kompakte
Arrays [station, an, ab, m]) plus einen Kalenderblock:
  services: Liste der GTFS-service_ids (nur als Index referenziert)
  fahrten[i].s: Index in services
  tage: {datum: [service-Indizes]} fuer jeden Betriebstag des Feeds
Das Frontend filtert client-seitig: Tag -> aktive Services -> Fahrten.
Alle uebrigen Regeln (Betriebspunkte, 2-Punkte-Shapes, Vorwaerts-Snapping,
Sekunden seit 04:00) sind identisch zur Tages-ETL.
"""

import argparse
import gzip
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
from gtfs_bausteine import gtfs_zeit_zu_sekunden, kumulierte_meter, snappe_halte, utm_linestring

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
FARBEN = json.loads((ROOT / "linien_farben.json").read_text(encoding="utf-8"))

WOCHENTAGSSPALTEN = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def als_datum(gtfs_datum: int) -> date:
    s = str(gtfs_datum)
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def lade_service_tage(con: duckdb.DuckDBPyConnection, service_ids: set) -> dict:
    """service_id -> sortierte Liste der aktiven Kalendertage (ISO-Strings)."""
    tage: dict[str, set] = {sid: set() for sid in service_ids}

    for sid, *flags, start, ende in con.execute(f"""
        SELECT service_id, monday, tuesday, wednesday, thursday, friday, saturday, sunday,
               start_date, end_date
        FROM read_csv_auto('{(DATA / "calendar.csv").as_posix()}')
    """).fetchall():
        sid = str(sid)
        if sid not in tage:
            continue
        tag = als_datum(start)
        ende_d = als_datum(ende)
        while tag <= ende_d:
            if flags[tag.weekday()] == 1:
                tage[sid].add(tag.isoformat())
            tag += timedelta(days=1)

    for sid, datum, ausnahme in con.execute(f"""
        SELECT service_id, date, exception_type
        FROM read_csv_auto('{(DATA / "calendar_dates.csv").as_posix()}')
    """).fetchall():
        sid = str(sid)
        if sid not in tage:
            continue
        iso = als_datum(datum).isoformat()
        if ausnahme == 1:
            tage[sid].add(iso)
        else:
            tage[sid].discard(iso)

    return {sid: sorted(t) for sid, t in tage.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", action="store_true",
                        help="zusaetzlich nach frontend/public/geo/mehrtagesdatensatz.json schreiben")
    args = parser.parse_args()

    con = duckdb.connect()

    fahrten_roh = con.execute(f"""
        WITH us_routes AS (
            SELECT route_id, route_short_name AS linie
            FROM read_csv_auto('{(DATA / "routes.csv").as_posix()}')
            WHERE route_type IN (402, 109)
        )
        SELECT t.trip_id, r.linie, t.shape_id, t.service_id
        FROM read_csv_auto('{(DATA / "trips.csv").as_posix()}') t
        JOIN us_routes r USING (route_id)
    """).fetchall()

    halte_zeilen = con.execute(f"""
        WITH us_routes AS (
            SELECT route_id FROM read_csv_auto('{(DATA / "routes.csv").as_posix()}')
            WHERE route_type IN (402, 109)
        ),
        us_trips AS (
            SELECT trip_id FROM read_csv_auto('{(DATA / "trips.csv").as_posix()}')
            JOIN us_routes USING (route_id)
        )
        SELECT st.trip_id, s.stop_id, s.stop_name, st.arrival_time, st.departure_time,
               s.stop_lon, s.stop_lat
        FROM read_csv_auto('{(DATA / "stop_times.csv").as_posix()}',
                           types={{'arrival_time': 'VARCHAR', 'departure_time': 'VARCHAR'}}) st
        JOIN us_trips USING (trip_id)
        JOIN read_csv_auto('{(DATA / "stops.csv").as_posix()}') s USING (stop_id)
        WHERE NOT (COALESCE(st.pickup_type, 0) = 1 AND COALESCE(st.drop_off_type, 0) = 1)
        ORDER BY st.trip_id, st.stop_sequence
    """).fetchall()
    halte_je_trip: dict[str, list] = {}
    for trip_id, *rest in halte_zeilen:
        halte_je_trip.setdefault(str(trip_id), []).append(tuple(rest))

    shape_zeilen = con.execute(f"""
        WITH us_routes AS (
            SELECT route_id FROM read_csv_auto('{(DATA / "routes.csv").as_posix()}')
            WHERE route_type IN (402, 109)
        ),
        us_shapes AS (
            SELECT DISTINCT shape_id FROM read_csv_auto('{(DATA / "trips.csv").as_posix()}')
            JOIN us_routes USING (route_id)
        )
        SELECT s.shape_id, list([s.shape_pt_lon, s.shape_pt_lat] ORDER BY s.shape_pt_sequence)
        FROM read_csv_auto('{(DATA / "shapes.csv").as_posix()}') s
        JOIN us_shapes USING (shape_id)
        GROUP BY s.shape_id
        HAVING COUNT(*) >= 3
    """).fetchall()
    shapes_roh = {str(sid): coords for sid, coords in shape_zeilen}
    shapes_utm = {sid: utm_linestring(coords) for sid, coords in shapes_roh.items()}
    shapes_block = {
        sid: {
            "coords": [[round(lon, 6), round(lat, 6)] for lon, lat in coords],
            "meter": [round(m) for m in kumulierte_meter(shapes_utm[sid])],
        }
        for sid, coords in shapes_roh.items()
    }

    service_tage = lade_service_tage(con, {str(s) for *_, s in fahrten_roh})

    stationen: list[str] = []
    stations_index: dict[str, int] = {}
    services: list[str] = []
    service_index: dict[str, int] = {}
    snap_cache: dict[tuple, list | None] = {}
    fahrten = []
    verworfen = {"shape": 0, "halte": 0, "snapping": 0, "ohne_tage": 0}

    for trip_id, linie, shape_id, service_id in fahrten_roh:
        trip_id, shape_id, service_id = str(trip_id), str(shape_id), str(service_id)
        halte_roh = halte_je_trip.get(trip_id, [])
        if shape_id not in shapes_roh:
            verworfen["shape"] += 1
            continue
        if len(halte_roh) < 2:
            verworfen["halte"] += 1
            continue
        if not service_tage.get(service_id):
            verworfen["ohne_tage"] += 1
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

        if service_id not in service_index:
            service_index[service_id] = len(services)
            services.append(service_id)

        halte = []
        for (_, name, an, ab, _, _), m in zip(halte_roh, snap_cache[laufweg]):
            if name not in stations_index:
                stations_index[name] = len(stationen)
                stationen.append(name)
            halte.append([stations_index[name], gtfs_zeit_zu_sekunden(an),
                          gtfs_zeit_zu_sekunden(ab), round(m)])

        fahrten.append({
            "id": trip_id,
            "linie": linie,
            "shape": shape_id,
            "s": service_index[service_id],
            "halte": halte,
        })

    fahrten.sort(key=lambda f: (f["halte"][0][2], f["id"]))

    # Kalenderblock: Tag -> Indizes der an dem Tag aktiven Services
    tage: dict[str, list[int]] = {}
    for sid, idx in service_index.items():
        for datum in service_tage[sid]:
            tage.setdefault(datum, []).append(idx)
    tage = {datum: sorted(idx_liste) for datum, idx_liste in sorted(tage.items())}

    genutzte_shapes = {f["shape"] for f in fahrten}
    genutzte_linien = {f["linie"] for f in fahrten}

    datensatz = {
        "meta": {
            "version": 2,
            "zeitraum": [min(tage), max(tage)],
            "quelle": "HVV GTFS via Transparenzportal Hamburg, CC BY 4.0",
            "erzeugt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        "linien": {l: FARBEN[l] for l in sorted(genutzte_linien)},
        "stationen": stationen,
        "services": services,
        "shapes": {sid: shapes_block[sid] for sid in sorted(genutzte_shapes)},
        "fahrten": fahrten,
        "tage": tage,
    }

    inhalt = json.dumps(datensatz, ensure_ascii=False)
    ziel = DATA / "mehrtagesdatensatz.json"
    ziel.write_text(inhalt, encoding="utf-8")
    if args.frontend:
        fe_ziel = ROOT / "frontend" / "public" / "geo" / "mehrtagesdatensatz.json"
        fe_ziel.write_text(inhalt, encoding="utf-8")

    je_linie: dict[str, int] = {}
    for f in fahrten:
        je_linie[f["linie"]] = je_linie.get(f["linie"], 0) + 1
    print(f"{len(fahrten)} Fahrten, {len(genutzte_shapes)} Shapes, {len(stationen)} Stationen, "
          f"{len(services)} Services, {len(tage)} Betriebstage ({min(tage)} bis {max(tage)})")
    print("je Linie:", ", ".join(f"{l} {n}" for l, n in sorted(je_linie.items())))
    print(f"verworfen: {verworfen}")

    # Stichprobe gegen die Tages-ETL: der Referenztag muss dieselbe Zahl liefern
    referenz = "2026-09-16"
    if referenz in tage:
        aktiv = set(tage[referenz])
        n = sum(1 for f in fahrten if f["s"] in aktiv)
        print(f"Kontrolle {referenz}: {n} Fahrten (Tages-ETL: 3412)")

    roh_mb = len(inhalt.encode()) / 1024 / 1024
    gz_mb = len(gzip.compress(inhalt.encode())) / 1024 / 1024
    print(f"-> {ziel.relative_to(ROOT)} ({roh_mb:.1f} MB roh, {gz_mb:.1f} MB gzip)")


if __name__ == "__main__":
    main()
