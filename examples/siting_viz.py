"""Write the interactive siting page: one house, 100 weather profiles, a second site.

    python scripts/fetch_locations.py       # once: data/ch_weather_2025.json
    python examples/siting_viz.py --open    # writes out/siting.html
    python examples/siting_viz.py --rank    # also print the second-site ranking

The page recomputes everything in the browser when a control moves. The same
model lives in `digitalheat.siting`; this script runs it for the default
settings and embeds the results, and the page shows whether its own numbers
agree with them.
"""

from __future__ import annotations

import argparse
import base64
import json
import struct
import webbrowser
from dataclasses import asdict
from pathlib import Path

from digitalheat import reference_assumptions
from digitalheat.siting import (SitingParams, heat_requirement, rank_second_site, run_sites,
                                window_hours)

DEFAULTS = {"site1": "Basel", "compute_kw": 6.0, "window_start": 1, "window_months": 6}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--weather", type=Path, default=Path("data/ch_weather_2025.json"))
    parser.add_argument("--out", type=Path, default=Path("out/siting.html"))
    parser.add_argument("--open", action="store_true", help="open the page in the browser")
    parser.add_argument("--rank", action="store_true", help="print the second-site ranking")
    args = parser.parse_args()

    data = json.loads(args.weather.read_text(encoding="utf-8"))
    locations = data["locations"]
    params = SitingParams()
    need = {loc["name"]: heat_requirement(loc["temps_c"]) for loc in locations}

    first, compute_kw = DEFAULTS["site1"], DEFAULTS["compute_kw"]
    hours = window_hours(DEFAULTS["window_start"], DEFAULTS["window_months"])
    year = run_sites([need[first]], compute_kw, params)
    alone = run_sites([need[first]], compute_kw, params, hours)
    ranking = rank_second_site(need, first, compute_kw, params, hours)
    best = ranking[0]

    if args.rank:
        meta = {loc["name"]: loc for loc in locations}
        print(f"{first}, {compute_kw:g} kW of compute, recovery {params.recovery:.0%}, "
              f"tank {params.tank_kwh:g} kWh per house")
        print(f"  full year, one house: {year.covered_share:.1%} of heat covered, "
              f"{year.savings_chf:,.0f} CHF saved, {year.bill_recovered:.1%} of the bill recovered")
        print(f"  6 months from month {DEFAULTS['window_start']}, {first} alone: "
              f"{alone.savings_chf:,.0f} CHF saved, {alone.dumped_kwh:,.0f} kWh dumped\n")
        print(f"  {'rank':>4}  {'second site':<22}{'elev m':>7}{'saved CHF':>11}{'gain CHF':>10}"
              f"{'bill back':>10}{'dumped kWh':>12}")
        shown = list(enumerate(ranking, 1))
        for rank, score in shown[:10] + shown[-3:]:
            print(f"  {rank:>4}  {score.name:<22}{meta[score.name]['elevation_m']:>7}"
                  f"{score.savings_chf:>11,.0f}{score.gain_chf:>10,.0f}"
                  f"{score.bill_recovered:>10.1%}{score.dumped_kwh:>12,.0f}")

    a = reference_assumptions()
    payload = {
        "year": data["year"], "source": data["source"], "selection": data["selection"],
        "hours": data["hours"], "outline": data["outline"],
        "locations": [{
            "name": loc["name"], "canton": loc.get("canton", "").replace("Kanton ", ""),
            "lat": loc["lat"],
            "lon": loc["lon"], "elev": loc["elevation_m"],
            # temperatures in tenths of a degree, 16-bit little-endian, base64
            "t": base64.b64encode(struct.pack(f"<{len(loc['temps_c'])}h",
                                              *(round(t * 10) for t in loc["temps_c"]))).decode(),
        } for loc in locations],
        "house": {key: a.value(key) for key in (
            "design_heat_load_kw", "indoor_setpoint_c", "design_delta_k",
            "heating_day_threshold_c", "hot_water_kwh_per_day")},
        "params": asdict(params),
        "defaults": DEFAULTS,
        "check": {"year_savings_chf": year.savings_chf, "year_covered_share": year.covered_share,
                  "alone_savings_chf": alone.savings_chf, "best_name": best.name,
                  "best_savings_chf": best.savings_chf},
    }
    template = (Path(__file__).parent / "siting_template.html").read_text(encoding="utf-8")
    blob = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(template.replace("/*SITING_JSON*/null", blob), encoding="utf-8")
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.1f} MB, {len(locations)} locations)")
    if args.open:
        webbrowser.open(args.out.resolve().as_uri())


if __name__ == "__main__":
    main()
