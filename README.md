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

## Changing location

The Controls drawer takes a lat/lon and re-centres the chart, with a **home**
button back to Fairborn and **use my location** via the browser geolocation
prompt. The centre is a query parameter (`/api/flights?lat=&lon=`), and
responses are cached per location.

Bearings and distances are recomputed against the chosen centre rather than
reusing the upstream's own `dst`/`dir`, which are relative to the point the
server queried.

Note that the bundled airport data covers a 90 nm box around Fairborn, so
approach detection and place names only work near home. Further afield the
chart still works, but the location shows as bare coordinates and no approach
matching happens. Re-run `scripts/refresh_airports.py` with different
constants to move that box.

## Projector mode

The **projector** chip switches the chart to high-contrast, large type for
ceiling projection, and remembers the choice per browser.

A projector adds light and cannot subtract it, so black renders as whatever
the surface already is -- a beige ceiling stays beige. Every "dim it for a
dark room" choice that helps on a monitor works against you there. Projector
mode drops the dimming: callsigns go to 15px pure white with a heavy black
outline, the compass to 23px, rings and spokes brighten, aircraft glyphs grow
45%, and the street map falls back to 26% opacity so it stops competing with
the labels at the same luminance. Label de-confliction spacing scales with
the larger type.

## Text size

Two independent scales in the Controls drawer, each remembered per browser:

- **Panel text** (80-220%) sizes the side panels and their controls. Also
  bound to **Ctrl +** / **Ctrl -**, with **Ctrl 0** resetting both scales.
- **Marker text** (80-300%) sizes the callsigns, altitudes, compass and ring
  labels on the chart itself.

They are separate because a ceiling projection usually wants large chart
labels but not a side panel that eats the screen. Label de-confliction
spacing follows the marker scale, so bigger text still separates cleanly, and
the drawers widen with the panel scale rather than truncating their contents.

## Street map

The **streets** chip draws OpenStreetMap tiles under the chart, clipped to the
outer ring. It only applies in map view -- a mirrored looking-up chart would
need mirrored geography, which a street map cannot honestly provide, so
clicking the chip while mirrored switches to map view first.

Tiles are OSM's standard light style, inverted and desaturated in CSS to a dim
grey so they read in an unlit room without competing with the traffic. The
canvas is sized so its extent matches the outer ring exactly, and it rotates
with the chart.

Tiles are proxied through the app at `/tiles/{z}/{x}/{y}.png` and cached to
disk under `skyview/data/tiles/`, which is gitignored. The browser never talks
to OSM directly.

That indirection is required, not incidental. OSM's
[tile usage policy](https://operations.osmfoundation.org/policies/tiles/)
expects an identifying User-Agent and real caching, and their servers block
clients that do not comply -- an earlier version fetched tiles straight from
the browser and was blocked within a day, serving "Access blocked" images in
place of the map. The proxy sends a proper User-Agent, caches every tile, and
caps zoom at 14.

Carto's basemaps were the first choice for a dark UI, but they now watermark
unkeyed tiles with "API KEY REQUIRED".

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
