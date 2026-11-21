# Residential heat profile cross-check

This sensitivity check compares the case-calibrated 27,000 kWh Basel reference with the supplied HSR hourly residential profiles.

The source header says `MWh`, while the companion analysis interprets values as kWh per hour. Results below use that interpretation and normalize 8,640 hours (360 days) to 8,760 hours. Confirm units before using these as forecasts.

| Profile | 365-day demand (kWh) | Peak hourly demand (kW) | vs. case reference |
|---|---:|---:|---:|
| SFH_OLD | 16,446 | 7.37 | 60.9% |
| SFH_NEW | 8,004 | 4.37 | 29.6% |
| MFH_OLD | 101,563 | 38.10 | 376.2% |
| MFH_NEW | 33,283 | 16.50 | 123.3% |

## Sizing insight

Building type changes the useful heat sink materially: the old single-family profile is about 61% of the case reference, while the old multi-family profile is about 3.8 times larger. This supports sizing and siting servers against a profile rather than treating one reference house as universal.

## Provenance and limits

- Input: `context/residential_heating_hour_profile_HSR.csv`.
- Source analysis: `context/heat_model_server_vs_house_req.md`.
- These are 360-day profile shapes, not a weather-year simulation; hot-water treatment and units remain open questions.
- Rebuild with `python scripts/compare_heat_profiles.py`.
