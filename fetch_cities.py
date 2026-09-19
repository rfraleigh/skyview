"""Fetch the airplanes.live cities reference endpoint and write it to JSON.

Usage:
    python fetch_cities.py [--country-code USA] [--city-code LON] [--all]

Auth: airplanes.live gates the API behind an approved key. Set one of:
    AIRPLANES_LIVE_API_KEY   -> sent as the `auth` header
Contact contact@airplanes.live to request access.
"""

import argparse
import json
import os
import sys

import requests

BASE_URL = "https://api.airplanes.live"
ENDPOINT = "/rest/v1/ref/cities"
MAX_LIMIT = 200


def build_session():
    session = requests.Session()
    session.headers["Accept"] = "application/json"
    key = os.environ.get("AIRPLANES_LIVE_API_KEY")
    if key:
        session.headers["auth"] = key
    return session


def fetch_page(session, params):
    response = session.get(BASE_URL + ENDPOINT, params=params, timeout=30)
    if response.status_code == 403:
        body = response.text.strip()
        raise SystemExit(
            "403 Forbidden from airplanes.live.\n"
            f"  server said: {body}\n"
            "  The API is reachable but gated -- an approved API key is required.\n"
            "  Set AIRPLANES_LIVE_API_KEY once you have one."
        )
    response.raise_for_status()
    return response.json()


def extract_rows(payload):
    """The endpoint may return a bare list or wrap rows under a key."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("cities", "data", "results", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city-code", help="Filter by IATA city code")
    parser.add_argument("--country-code", help="Filter by ISO 3166-1 country code")
    parser.add_argument("--limit", type=int, default=50, help="Rows per request (max 200)")
    parser.add_argument("--all", action="store_true", help="Page through every result")
    parser.add_argument("--out", default="cities.json", help="Output JSON file")
    args = parser.parse_args()

    params = {"limit": min(args.limit, MAX_LIMIT)}
    if args.city_code:
        params["city_code"] = args.city_code
    if args.country_code:
        params["country_code"] = args.country_code

    session = build_session()

    if not args.all:
        payload = fetch_page(session, params)
    else:
        params["limit"] = MAX_LIMIT
        collected, offset = [], 0
        while True:
            page = fetch_page(session, dict(params, offset=offset))
            rows = extract_rows(page)
            collected.extend(rows)
            if len(rows) < MAX_LIMIT:
                break
            offset += MAX_LIMIT
        payload = collected

    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)

    count = len(extract_rows(payload))
    print(f"Wrote {count} cities to {args.out}", file=sys.stderr)
    print(json.dumps(payload, indent=2, ensure_ascii=False)[:2000])


if __name__ == "__main__":
    main()
