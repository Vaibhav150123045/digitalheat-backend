"""Build hourly weather profiles for 100 well-spaced places in Switzerland.

    python scripts/fetch_locations.py        # writes data/ch_weather_2025.json

Steps
  1. Geocode a list of ~150 Swiss towns (Open-Meteo geocoding API). Towns, not
     grid points, because a server needs a house to heat.
  2. Keep 100 of them by farthest-point sampling, starting from Basel: each
     pick is the town farthest from all towns already picked.
  3. Download hourly temperature_2m for the year from the Open-Meteo
     historical archive, in local time (Europe/Zurich).
  4. Download a coarse outline of Switzerland for the map (optional).

No API key is needed. Requests are spaced out to stay inside the free limits,
and every response is cached in data/cache so a rerun continues where it stopped.
"""

from __future__ import annotations

import argparse
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
OUTLINE = "https://raw.githubusercontent.com/georgique/world-geojson/develop/countries/switzerland.json"

CANDIDATES = """
Basel, Liestal, Rheinfelden, Laufen, Delémont, Porrentruy, Saignelégier, Moutier, Olten, Aarau,
Baden, Brugg, Zofingen, Solothurn, Grenchen, Biel, Schaffhausen, Stein am Rhein, Frauenfeld,
Kreuzlingen, Romanshorn, Weinfelden, Winterthur, Zürich, Uster, Wetzikon, Rapperswil, Bülach, Wil,
St. Gallen, Herisau, Appenzell, Altstätten, Rorschach, Sargans, Bad Ragaz, Wattwil, Wildhaus,
Glarus, Linthal, Elm, Zug, Luzern, Sursee, Willisau, Schüpfheim, Schwyz, Einsiedeln, Altdorf,
Andermatt, Göschenen, Sarnen, Engelberg, Stans, Sörenberg, Bern, Burgdorf, Langnau im Emmental,
Langenthal, Thun, Spiez, Interlaken, Grindelwald, Lauterbrunnen, Meiringen, Brienz, Kandersteg,
Adelboden, Lenk, Zweisimmen, Gstaad, Schwarzenburg, Lyss, Neuchâtel, La Chaux-de-Fonds, Le Locle,
Fleurier, Yverdon-les-Bains, Sainte-Croix, Vallorbe, Le Sentier, Lausanne, Morges, Nyon, Genève,
Vevey, Montreux, Aigle, Château-d'Oex, Bulle, Fribourg, Romont, Payerne, Murten, Echallens,
Moudon, Monthey, Martigny, Verbier, Orsières, Sion, Sierre, Crans-Montana, Leukerbad, Visp,
Zermatt, Saas-Fee, Brig, Fiesch, Ulrichen, Evolène, Zinal, Champéry, Airolo, Faido, Biasca,
Olivone, Bellinzona, Locarno, Cevio, Lugano, Mendrisio, Chiasso, Chur, Landquart, Klosters,
Davos, Arosa, Lenzerheide, Thusis, Tiefencastel, Savognin, Bivio, Splügen, San Bernardino,
Mesocco, Roveredo, Ilanz, Disentis, Vals, Flims, St. Moritz, Samedan, Pontresina, Zuoz, Zernez,
Scuol, Samnaun, Müstair, Poschiavo, Maloja, Vicosoprano
"""


def get_json(url: str, cache: Path, pause_s: float, retries: int = 6):
    """GET with an on-disk cache and patient retries on rate limiting."""
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "weather-profile-script"})
            with urllib.request.urlopen(request, timeout=120) as response:
                body = response.read().decode("utf-8")
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(body, encoding="utf-8")
            time.sleep(pause_s)
            return json.loads(body)
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == retries - 1:
                raise
            wait = 65 * (attempt + 1)
            print(f"  rate limited, waiting {wait} s", flush=True)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def km(a: dict, b: dict) -> float:
    """Great-circle distance."""
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dl = math.radians(b["lon"] - a["lon"])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def geocode(name: str, cache_dir: Path) -> dict | None:
    query = urllib.parse.urlencode({"name": name, "count": 10, "language": "de", "format": "json"})
    safe = "".join(c if c.isalnum() else "_" for c in name)
    data = get_json(f"{GEOCODE}?{query}", cache_dir / f"geo_{safe}.json", pause_s=0.2)
    swiss = [r for r in data.get("results", []) if r.get("country_code") == "CH"]
    if not swiss:
        return None
    exact = [r for r in swiss if r["name"].lower() == name.lower()] or swiss[:1]
    best = max(exact, key=lambda r: r.get("population") or 0)
    return {"name": name, "lat": round(best["latitude"], 4), "lon": round(best["longitude"], 4),
            "canton": best.get("admin1", "")}


def farthest_point_sample(places: list[dict], count: int, first: str) -> list[dict]:
    chosen = [next(p for p in places if p["name"] == first)]
    rest = [p for p in places if p["name"] != first]
    nearest = [km(p, chosen[0]) for p in rest]
    while len(chosen) < count and rest:
        index = max(range(len(rest)), key=nearest.__getitem__)
        pick = rest.pop(index)
        nearest.pop(index)
        chosen.append(pick)
        nearest = [min(d, km(p, pick)) for d, p in zip(nearest, rest)]
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--batch", type=int, default=10, help="locations per archive request")
    parser.add_argument("--pause", type=float, default=28.0, help="seconds between archive requests")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    out = args.out or Path("data") / f"ch_weather_{args.year}.json"
    cache_dir = out.parent / "cache"

    names = [n.strip() for n in CANDIDATES.replace("\n", " ").split(",") if n.strip()]
    places = []
    for name in names:
        place = geocode(name, cache_dir)
        if place is None:
            print(f"  not found in Switzerland, skipped: {name}")
        else:
            places.append(place)
    print(f"geocoded {len(places)} of {len(names)} towns", flush=True)

    chosen = farthest_point_sample(places, args.count, "Basel")
    spacing = [min(km(p, q) for q in chosen if q is not p) for p in chosen]
    print(f"kept {len(chosen)}: nearest-neighbour distance {min(spacing):.0f}-{max(spacing):.0f} km, "
          f"median {sorted(spacing)[len(spacing) // 2]:.0f} km", flush=True)

    for start in range(0, len(chosen), args.batch):
        batch = chosen[start:start + args.batch]
        query = urllib.parse.urlencode({
            "latitude": ",".join(str(p["lat"]) for p in batch),
            "longitude": ",".join(str(p["lon"]) for p in batch),
            "start_date": f"{args.year}-01-01", "end_date": f"{args.year}-12-31",
            "hourly": "temperature_2m", "timezone": "Europe/Zurich", "format": "json",
        })
        key = f"wx_{args.year}_{start:03d}_{len(batch)}_{abs(hash(tuple(p['name'] for p in batch))) % 10**8}.json"
        cached = sorted(cache_dir.glob(f"wx_{args.year}_{start:03d}_{len(batch)}_*.json"))
        data = get_json(f"{ARCHIVE}?{query}", cached[0] if cached else cache_dir / key, args.pause)
        data = data if isinstance(data, list) else [data]
        for place, result in zip(batch, data):
            temps = result["hourly"]["temperature_2m"]
            if any(t is None for t in temps):
                raise ValueError(f"missing temperatures for {place['name']}")
            place["elevation_m"] = round(result["elevation"])
            place["temps_c"] = temps
            place["first_hour"] = result["hourly"]["time"][0]
        print(f"  weather {start + len(batch)}/{len(chosen)}", flush=True)

    outline = []
    try:
        geo = get_json(OUTLINE, cache_dir / "outline.json", pause_s=0)
        geometry = geo["features"][0]["geometry"]
        rings = geometry["coordinates"] if geometry["type"] == "Polygon" else geometry["coordinates"][0]
        outline = [[round(x, 3), round(y, 3)] for x, y in rings[0]]
    except Exception as error:   # the map still works without the outline
        print(f"  outline not available ({error})")

    hours = {len(p["temps_c"]) for p in chosen}
    payload = {
        "year": args.year,
        "source": "Open-Meteo historical archive, temperature_2m, hourly, Europe/Zurich; "
                  "coordinates from the Open-Meteo geocoding API",
        "selection": f"farthest-point sampling of {len(chosen)} from {len(places)} Swiss towns, from Basel",
        "hours": hours.pop() if len(hours) == 1 else sorted(hours),
        "outline": outline,
        "locations": chosen,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB, {payload['hours']} hours per location)")


if __name__ == "__main__":
    main()
