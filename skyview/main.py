"""Sky View over Fairborn, OH -- FastAPI app serving a live overhead sky chart.

Run:
    .venv/Scripts/python.exe -m uvicorn skyview.main:app --reload --port 8000
Then open http://127.0.0.1:8000

Data: adsb.fi open data (public endpoint, no key, 1 req/sec limit).
      Non-commercial use only; cite https://adsb.fi
"""

from __future__ import annotations

import math
import os
import time
from collections import deque
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response

from . import airports as apt

# Fairborn, Ohio
FAIRBORN_LAT = 39.7792142
FAIRBORN_LON = -84.0399195
# Fetch wide once; the UI filters to the radius the viewer selects. This keeps
# radius changes instant and costs no extra upstream calls.
FETCH_RADIUS_NM = 120
DEFAULT_RADIUS_NM = 20

UPSTREAMS = [
    ("adsb.fi", "https://opendata.adsb.fi/api/v2/lat/{lat}/lon/{lon}/dist/{dist}", "aircraft"),
    ("adsb.lol", "https://api.adsb.lol/v2/point/{lat}/{lon}/{dist}", "ac"),
]

# Local readsb/dump1090 feed. Set READSB_URL to use your own receiver instead of
# the aggregators -- same aircraft.json schema, ~1s latency, no rate limit.
READSB_URL = os.environ.get("READSB_URL")

STATIC_DIR = Path(__file__).parent / "static"

# Street map tiles are proxied rather than fetched by the browser. OSM's tile
# policy requires an identifying User-Agent and sensible caching, and blocks
# clients that do not comply -- which a browser making anonymous cross-origin
# requests does not. Tiles are cached on disk and served from there.
TILE_CACHE_DIR = Path(__file__).parent / "data" / "tiles"
TILE_UA = "skyview-fairborn/1.0 (https://github.com/rfraleigh/skyview)"
TILE_MAX_ZOOM = 14

app = FastAPI(title="Sky View over Fairborn")

_cache: dict[str, object] = {"at": 0.0, "payload": None, "key": None}
CACHE_SECONDS = 4.0  # stay under adsb.fi's 1 req/sec even with many viewers

# The upstreams serve snapshots, not history -- there is no public trace endpoint.
# So we accumulate our own track per aircraft, one point per poll.
TRACK_POINTS = 120        # ~10 min of history at a 5s poll
TRACK_TTL_SECONDS = 900   # forget an aircraft 15 min after it drops out
_tracks: dict[str, deque] = {}
_track_seen: dict[str, float] = {}


def _record_tracks(rows: list[dict], now: float) -> None:
    for a in rows:
        hex_id = a.get("hex")
        lat, lon = a.get("lat"), a.get("lon")
        if not hex_id or lat is None or lon is None:
            continue
        track = _tracks.get(hex_id)
        if track is None:
            track = _tracks[hex_id] = deque(maxlen=TRACK_POINTS)
        # Skip duplicate positions so a parked/hovering aircraft doesn't fill
        # the buffer with identical points.
        if track and track[-1][0] == lat and track[-1][1] == lon:
            _track_seen[hex_id] = now
            continue
        track.append((lat, lon, a.get("alt_baro"), now))
        _track_seen[hex_id] = now

    for hex_id, seen in list(_track_seen.items()):
        if now - seen > TRACK_TTL_SECONDS:
            _track_seen.pop(hex_id, None)
            _tracks.pop(hex_id, None)


async def _fetch_upstream(client: httpx.AsyncClient, clat: float, clon: float) -> tuple[str, list[dict]]:
    if READSB_URL:
        response = await client.get(READSB_URL, timeout=8.0)
        response.raise_for_status()
        return "local readsb", response.json().get("aircraft", [])

    errors = []
    for name, template, key in UPSTREAMS:
        url = template.format(lat=clat, lon=clon, dist=FETCH_RADIUS_NM)
        try:
            response = await client.get(url, timeout=8.0)
            response.raise_for_status()
            return name, response.json().get(key) or []
        except Exception as exc:  # try the next mirror
            errors.append(f"{name}: {exc}")
    raise HTTPException(status_code=502, detail="All upstreams failed: " + "; ".join(errors))


def _place_name(lat: float, lon: float) -> str:
    """Label the chart centre using the nearest known airport, if any."""
    if abs(lat - FAIRBORN_LAT) < 0.02 and abs(lon - FAIRBORN_LON) < 0.02:
        return "Fairborn, OH"
    near = apt.nearest_airport(lat, lon, max_nm=25.0)
    if near:
        airport, dist = near
        where = airport.municipality or airport.name
        return f"{where} ({airport.ident}, {dist:.0f} nm)"
    return f"{lat:.3f}, {lon:.3f}"


def _polar(lat: float, lon: float, clat: float, clon: float) -> tuple[float, float]:
    """Bearing (deg true) and distance (nm) from the chart centre to a point.

    Equirectangular approximation -- accurate well within a degree at these
    ranges, and far cheaper than haversine for every point of every track.
    """
    lat_rad = math.radians((lat + clat) / 2)
    dy = (lat - clat) * 60.0
    dx = (lon - clon) * 60.0 * math.cos(lat_rad)
    bearing = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0
    return bearing, math.hypot(dx, dy)


def _clean(rows: list[dict], clat: float, clon: float) -> list[dict]:
    """Keep airborne contacts that have a usable position."""
    out = []
    for a in rows:
        alt = a.get("alt_baro")
        if alt == "ground":
            continue
        if a.get("lat") is None or a.get("lon") is None:
            continue
        # Recomputed against the viewer's centre -- the upstream's own dst/dir
        # are relative to the point we queried, which may differ.
        bearing, distance = _polar(a["lat"], a["lon"], clat, clon)
        out.append(
            {
                "hex": a.get("hex"),
                "flight": (a.get("flight") or "").strip() or None,
                "reg": a.get("r"),
                "type": a.get("t"),
                "desc": a.get("desc"),
                "operator": a.get("ownOp"),
                "alt": alt if isinstance(alt, (int, float)) else None,
                "gs": a.get("gs"),
                "track": a.get("track"),
                "baro_rate": a.get("baro_rate"),
                "squawk": a.get("squawk"),
                "emergency": a.get("emergency"),
                "dst": round(distance, 3),
                "dir": round(bearing, 2),
                "category": a.get("category"),
                # Intent, not just state: the altitude the crew has dialled in,
                # and the autopilot modes they have armed.
                "nav_alt": a.get("nav_altitude_mcp"),
                "nav_modes": a.get("nav_modes") or [],
                "rc": a.get("rc"),
                "approach": apt.approach_for(
                    a.get("lat"), a.get("lon"),
                    alt if isinstance(alt, (int, float)) else None,
                    a.get("track"), a.get("baro_rate"),
                ),
                "mlat": bool(a.get("mlat")),
                "seen_pos": a.get("seen_pos"),
                "track_pts": [
                    {"dir": b, "dst": d, "alt": alt_p}
                    for b, d, alt_p in (
                        (*_polar(pt[0], pt[1], clat, clon), pt[2]) for pt in _tracks.get(a.get("hex"), ())
                    )
                ],
            }
        )
    out.sort(key=lambda a: a["dst"] if a["dst"] is not None else 9e9)
    return out


@app.get("/api/flights")
async def flights(lat: float | None = None, lon: float | None = None):
    clat = FAIRBORN_LAT if lat is None else max(-90.0, min(90.0, lat))
    clon = FAIRBORN_LON if lon is None else max(-180.0, min(180.0, lon))

    now = time.time()
    # Cache per location, so panning somewhere new always fetches.
    key = (round(clat, 3), round(clon, 3))
    if (
        _cache["payload"] is not None
        and _cache["key"] == key
        and now - float(_cache["at"]) < CACHE_SECONDS
    ):
        return _cache["payload"]

    async with httpx.AsyncClient(headers={"User-Agent": "skyview-fairborn/1.0"}) as client:
        source, rows = await _fetch_upstream(client, clat, clon)

    _record_tracks(rows, now)

    payload = {
        "now": now,
        "source": source,
        "center": {"lat": clat, "lon": clon, "name": _place_name(clat, clon)},
        "radius_nm": DEFAULT_RADIUS_NM,
        "fetch_radius_nm": FETCH_RADIUS_NM,
        "aircraft": _clean(rows, clat, clon),
    }
    _cache["at"] = now
    _cache["key"] = key
    _cache["payload"] = payload
    return JSONResponse(payload)


@app.get("/tiles/{z}/{x}/{y}.png")
async def tile(z: int, x: int, y: int):
    """Proxy and cache OSM tiles, so the browser never hits OSM directly."""
    if not (0 <= z <= TILE_MAX_ZOOM):
        raise HTTPException(status_code=404, detail="zoom out of range")
    limit = 2 ** z
    if not (0 <= x < limit and 0 <= y < limit):
        raise HTTPException(status_code=404, detail="tile out of range")

    path = TILE_CACHE_DIR / str(z) / str(x) / f"{y}.png"
    if path.exists():
        return Response(
            content=path.read_bytes(),
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=604800"},
        )

    url = f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    try:
        async with httpx.AsyncClient(headers={"User-Agent": TILE_UA}) as client:
            response = await client.get(url, timeout=12.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"tile fetch failed: {exc}")

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="tile unavailable")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    return Response(
        content=response.content,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=604800"},
    )


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")
