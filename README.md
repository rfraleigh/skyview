# Sky View over Fairborn

A FastAPI single-page app showing live aircraft over Fairborn, OH as an
**overhead sky chart** — oriented as if you were lying on your back looking up.

## Run

```bash
.venv/Scripts/python.exe -m uvicorn skyview.main:app --reload --port 8000
# open http://127.0.0.1:8000
```

## Orientation

North is at top, but the view is **mirrored** east-for-west, because you're
facing up rather than down at a map. Lie on your back with your head pointing
north: east is on your left. Rings are **distance** (15/30/45/60 nm), not
elevation. Dot size grows with proximity; color encodes altitude band; the
tick shows heading.

## Interacting

- **Click any aircraft** (chart or list) for its details and flown track.
- **Rotate** turns the chart so any heading is "up" — useful when projecting.
- **mirrored / map view** flips handedness. Leave it mirrored for looking up;
  switch to map view for a conventional chart, or to correct a projector that
  reverses the image.
- **Operator filters** — comm / civil / mil. See the caveat below.
- **Phase filters** — dep ↑ / arr ↓ / cruise, from vertical rate.

## Tracks

The upstreams serve snapshots, not history, and there is no public trace
endpoint. So the server accumulates its own track: one point per poll, up to
120 points (~10 min at 5s), dropped 15 min after an aircraft leaves. Tracks
build while the server runs and start empty on restart.

## Approach detection

Descending aircraft are matched against local runways to produce
"→ DAY 06L" in the list and a full line in the detail panel. A match requires
all of: descending, within 10 nm of a threshold, under 4,000 ft AGL, within
25 degrees of the runway heading, flying toward (not away from) the threshold,
and under a generous glidepath cone (1,200 ft + 700 ft per nm out).

That cone matters -- without it, an aircraft overflying a grass strip at
4,000 ft matched as "landing". It is still a heuristic: an aircraft on a
visual approach that has not lined up yet will be missed, and a low overflight
straight down a centreline can still produce a false match.

Airport and runway data is OurAirports (public domain), trimmed to a 90 nm box
(353 airports, 682 runway ends, 49 KB). Refresh with:

```bash
.venv/Scripts/python.exe scripts/refresh_airports.py
```

## Flight phase

Phase now uses three signals, strongest first:

1. A matched runway approach -> arriving
2. `nav_altitude_mcp` (the crew's selected altitude) more than 1,500 ft from
   current -> climbing or descending toward it
3. Barometric vertical rate (>400 fpm / <-400 fpm)

Signal 2 is intent rather than state, so it catches a descent before the rate
does. Roughly 27 of 32 aircraft broadcast it.

## Classification caveats

**Operator class is a heuristic, not ground truth.** ADS-B carries no military
flag. `commercial` means an airline-style callsign (3 letters + digits);
`military` is inferred from US armed-forces ICAO hex blocks and common
callsign prefixes; everything else falls to `civilian`. Military aircraft that
don't broadcast, or broadcast with civil-looking identifiers, will be missed —
relevant here, since Wright-Patterson AFB is adjacent.

**Phase is inferred from vertical rate** (>400 fpm climb = departing, <-400 =
arriving), not from any flight plan. An aircraft levelling off mid-climb reads
as cruise.

## Data

Server-side proxy of [adsb.fi](https://adsb.fi) open data, with adsb.lol as
automatic fallback. No API key. The proxy exists because neither API sends
CORS headers, so the browser can't call them directly.

Responses are cached 4s server-side, so any number of open tabs stays within
adsb.fi's 1 req/sec public limit while the UI polls every 5s.

Non-commercial use only; adsb.fi asks to be cited with a link.

## Using your own receiver

If you set up an RTL-SDR with readsb/dump1090, point at it instead — same
`aircraft.json` schema, ~1s latency, no rate limit, no dependency on anyone:

```bash
READSB_URL=http://<receiver>/data/aircraft.json \
  .venv/Scripts/python.exe -m uvicorn skyview.main:app --port 8000
```

## Files

- `skyview/main.py` — FastAPI app, upstream proxy + fallback, `/api/flights`
- `skyview/static/index.html` — the sky chart (no build step, no framework)
- `fetch_cities.py` — separate: airplanes.live cities endpoint (needs their approval)
