"""Airport and runway join for Sky View.

Turns "descending, 2,800 ft, bearing 287" into "on approach to KDAY 06L".

Data: OurAirports (public domain), trimmed at build time to a 90 nm box around
Fairborn -- see data/airports_local.csv and data/runways_local.csv. Refresh with
scripts/refresh_airports.py.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# An aircraft is only considered "approaching" inside this envelope. These are
# deliberately loose -- the goal is a useful hint, not an ATC-grade judgement.
MAX_APPROACH_ALT_AGL = 4000     # ft above field elevation
MAX_APPROACH_DIST_NM = 10.0
MAX_ALIGN_DEG = 25.0            # track vs. runway heading
MIN_DESCENT_FPM = -200

# An approach follows a glidepath: roughly 300 ft of height per nm out (a 3
# degree slope). Allow generous slack, but reject anything far above the cone --
# that is an overflight, not an arrival.
MAX_AGL_PER_NM = 700
GLIDEPATH_FLOOR_FT = 1200       # slack for pattern work close in


@dataclass(frozen=True)
class Runway:
    airport: str
    ident: str
    heading: float
    length_ft: int | None
    lat: float
    lon: float


@dataclass(frozen=True)
class Airport:
    ident: str
    name: str
    kind: str
    lat: float
    lon: float
    elevation_ft: float
    iata: str | None
    municipality: str | None


def _nm_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    mid = math.radians((lat1 + lat2) / 2)
    dy = (lat2 - lat1) * 60.0
    dx = (lon2 - lon1) * 60.0 * math.cos(mid)
    return math.hypot(dx, dy)


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    mid = math.radians((lat1 + lat2) / 2)
    dy = (lat2 - lat1) * 60.0
    dx = (lon2 - lon1) * 60.0 * math.cos(mid)
    return (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0


def _angle_diff(a: float, b: float) -> float:
    """Smallest absolute difference between two headings, 0-180."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _load() -> tuple[dict[str, Airport], list[Runway]]:
    airports: dict[str, Airport] = {}
    path = DATA_DIR / "airports_local.csv"
    if not path.exists():
        return {}, []

    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                airports[row["ident"]] = Airport(
                    ident=row["ident"],
                    name=row["name"],
                    kind=row["type"],
                    lat=float(row["latitude_deg"]),
                    lon=float(row["longitude_deg"]),
                    elevation_ft=float(row["elevation_ft"] or 0),
                    iata=row["iata_code"] or None,
                    municipality=row["municipality"] or None,
                )
            except (TypeError, ValueError):
                continue

    runways: list[Runway] = []
    rw_path = DATA_DIR / "runways_local.csv"
    if rw_path.exists():
        with rw_path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row["airport_ident"] not in airports:
                    continue
                try:
                    length = int(row["length_ft"]) if row["length_ft"] else None
                except ValueError:
                    length = None
                # Each physical runway is two landing directions; both are usable.
                for end, lat_k, lon_k, hdg_k in (
                    (row["le_ident"], "le_latitude_deg", "le_longitude_deg", "le_heading_degT"),
                    (row["he_ident"], "he_latitude_deg", "he_longitude_deg", "he_heading_degT"),
                ):
                    if not end:
                        continue
                    # Most small strips never publish a true heading. The runway
                    # identifier encodes it though -- "06" means roughly 060 --
                    # so fall back to that rather than dropping the runway.
                    if not row.get(hdg_k):
                        digits = "".join(c for c in end if c.isdigit())
                        if not digits:
                            continue
                        row = dict(row)
                        row[hdg_k] = str((int(digits) * 10) % 360)
                    try:
                        lat = float(row[lat_k]) if row[lat_k] else airports[row["airport_ident"]].lat
                        lon = float(row[lon_k]) if row[lon_k] else airports[row["airport_ident"]].lon
                        runways.append(
                            Runway(
                                airport=row["airport_ident"],
                                ident=end,
                                heading=float(row[hdg_k]),
                                length_ft=length,
                                lat=lat,
                                lon=lon,
                            )
                        )
                    except (TypeError, ValueError):
                        continue
    return airports, runways


AIRPORTS, RUNWAYS = _load()


def nearest_airport(lat: float, lon: float, max_nm: float = 30.0) -> tuple[Airport, float] | None:
    best = None
    for airport in AIRPORTS.values():
        dist = _nm_between(lat, lon, airport.lat, airport.lon)
        if dist <= max_nm and (best is None or dist < best[1]):
            best = (airport, dist)
    return best


def approach_for(
    lat: float | None,
    lon: float | None,
    alt_ft: float | None,
    track: float | None,
    baro_rate: float | None,
) -> dict | None:
    """Best guess at the runway an aircraft is approaching, or None.

    Requires all four inputs: a descending aircraft, low, close to a field, and
    tracking roughly down a runway's centreline. Returns the runway plus the
    evidence behind the call so the UI can be honest about confidence.
    """
    if lat is None or lon is None or alt_ft is None or track is None:
        return None
    if baro_rate is None or baro_rate > MIN_DESCENT_FPM:
        return None

    best = None
    for runway in RUNWAYS:
        airport = AIRPORTS.get(runway.airport)
        if airport is None:
            continue
        agl = alt_ft - airport.elevation_ft
        if agl > MAX_APPROACH_ALT_AGL or agl < -500:
            continue
        dist = _nm_between(lat, lon, runway.lat, runway.lon)
        if dist > MAX_APPROACH_DIST_NM:
            continue
        # Aligned with the runway...
        align = _angle_diff(track, runway.heading)
        if align > MAX_ALIGN_DEG:
            continue
        # ...and low enough for its distance out to actually be on a glidepath.
        if agl > GLIDEPATH_FLOOR_FT + dist * MAX_AGL_PER_NM:
            continue
        # ...and actually flying toward the threshold, not away from it.
        to_threshold = _bearing(lat, lon, runway.lat, runway.lon)
        if _angle_diff(track, to_threshold) > 60.0:
            continue

        # Prefer the closest, best-aligned candidate.
        score = dist + (align / 15.0)
        if best is None or score < best[0]:
            best = (
                score,
                {
                    "airport": airport.ident,
                    "airport_name": airport.name,
                    "iata": airport.iata,
                    "runway": runway.ident,
                    "distance_nm": round(dist, 1),
                    "agl_ft": int(agl),
                    "alignment_deg": round(align, 1),
                },
            )
    return best[1] if best else None
