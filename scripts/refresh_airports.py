"""Rebuild skyview/data/*_local.csv from OurAirports.

OurAirports is public domain and updated continuously. Re-run occasionally:
    .venv/Scripts/python.exe scripts/refresh_airports.py
"""

import csv
import io
import math
import urllib.request
from pathlib import Path

LAT, LON = 39.7792142, -84.0399195
BOX_NM = 90
BASE = "https://davidmegginson.github.io/ourairports-data/"
OUT = Path(__file__).resolve().parent.parent / "skyview" / "data"

AIRPORT_COLS = ("ident", "type", "name", "latitude_deg", "longitude_deg",
                "elevation_ft", "iata_code", "municipality")
RUNWAY_COLS = ("airport_ident", "le_ident", "he_ident", "length_ft", "surface",
               "le_latitude_deg", "le_longitude_deg", "le_heading_degT",
               "he_latitude_deg", "he_longitude_deg", "he_heading_degT")


def nm(lat, lon):
    mid = math.radians((lat + LAT) / 2)
    return math.hypot((lon - LON) * 60 * math.cos(mid), (lat - LAT) * 60)


def fetch(name):
    # The CDN rejects urllib's default user-agent with a connection reset.
    request = urllib.request.Request(
        BASE + name, headers={"User-Agent": "skyview-fairborn/1.0"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return csv.DictReader(io.StringIO(response.read().decode("utf-8")))


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    keep, airports = set(), []
    for row in fetch("airports.csv"):
        if row["type"] not in ("large_airport", "medium_airport", "small_airport"):
            continue
        try:
            if nm(float(row["latitude_deg"]), float(row["longitude_deg"])) > BOX_NM:
                continue
        except (TypeError, ValueError):
            continue
        keep.add(row["ident"])
        airports.append({k: row[k] for k in AIRPORT_COLS})

    runways = [
        {k: row[k] for k in RUNWAY_COLS}
        for row in fetch("runways.csv")
        if row["airport_ident"] in keep and row["closed"] != "1"
    ]

    for name, rows, cols in (
        ("airports_local.csv", airports, AIRPORT_COLS),
        ("runways_local.csv", runways, RUNWAY_COLS),
    ):
        with (OUT / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(cols))
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {name}: {len(rows)} rows")


if __name__ == "__main__":
    main()
