"""Compare the supplied HSR residential profiles with the 27 MWh case reference."""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "context/residential_heating_hour_profile_HSR.csv"
REPORT = ROOT / "docs/HEAT_PROFILE_CROSSCHECK.md"
JSON_OUTPUT = ROOT / "data/derived/heat_profile_crosscheck.json"
REFERENCE_KWH = 27_000.0
SOURCE_HOURS = 8_640
YEAR_HOURS = 8_760


def main() -> None:
    with SOURCE.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = [name for name in reader.fieldnames or () if name != "Hour"]
        values = {name: [] for name in columns}
        for row in reader:
            for name in columns:
                value = float(row[name])
                if value < 0:
                    raise ValueError(f"negative heat demand in {name}: {value}")
                values[name].append(value)
    if not columns or any(len(series) != SOURCE_HOURS for series in values.values()):
        raise ValueError(f"expected {SOURCE_HOURS} hourly rows for every profile")

    profiles = []
    for source_name, series in values.items():
        annual = sum(series) * YEAR_HOURS / SOURCE_HOURS
        profiles.append({
            "name": source_name.replace(" (MWh)", ""),
            "source_label": source_name,
            "annualized_kwh": round(annual, 2),
            "peak_hourly_kw": round(max(series), 2),
            "share_of_case_reference": round(annual / REFERENCE_KWH, 6),
        })

    JSON_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUTPUT.write_text(json.dumps({
        "reference_space_heating_kwh": REFERENCE_KWH,
        "source_hours": SOURCE_HOURS,
        "annual_hours": YEAR_HOURS,
        "interpretation": "CSV values treated as kWh per hour; source header says MWh and needs confirmation.",
        "profiles": profiles,
    }, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Residential heat profile cross-check", "",
        "This sensitivity check compares the case-calibrated 27,000 kWh Basel reference with the supplied HSR hourly residential profiles.", "",
        "The source header says `MWh`, while the companion analysis interprets values as kWh per hour. Results below use that interpretation and normalize 8,640 hours (360 days) to 8,760 hours. Confirm units before using these as forecasts.", "",
        "| Profile | 365-day demand (kWh) | Peak hourly demand (kW) | vs. case reference |", "|---|---:|---:|---:|",
    ]
    for profile in profiles:
        lines.append(f"| {profile['name']} | {profile['annualized_kwh']:,.0f} | {profile['peak_hourly_kw']:,.2f} | {profile['share_of_case_reference']:.1%} |")
    lines += [
        "", "## Sizing insight", "",
        "Building type changes the useful heat sink materially: the old single-family profile is about 61% of the case reference, while the old multi-family profile is about 3.8 times larger. This supports sizing and siting servers against a profile rather than treating one reference house as universal.", "",
        "## Provenance and limits", "",
        "- Input: `context/residential_heating_hour_profile_HSR.csv`.",
        "- Source analysis: `context/heat_model_server_vs_house_req.md`.",
        "- These are 360-day profile shapes, not a weather-year simulation; hot-water treatment and units remain open questions.",
        "- Rebuild with `python scripts/compare_heat_profiles.py`.", "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {REPORT}")


if __name__ == "__main__":
    main()
