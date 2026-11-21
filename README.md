# digitalheat-backend

Schedules interruptible compute jobs across servers in homes so their heat arrives
where and when it is needed, and reports useful heat, useful computing and cost
over a year. Built for the DigitalHeat case at sprintd Basel GreenTech.

Pure Python, no runtime dependencies.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                                   # 29 tests

python scripts/fetch_weather.py          # Basel 2025 from Open-Meteo
python examples/reference_year.py data/open_meteo_basel_2025.csv --servers 3
python examples/live_job.py              # pauses and resumes a real process
python examples/trace_viz.py --open      # interactive trace of a small test case (out/trace.html)

python scripts/fetch_locations.py        # weather for 100 Swiss towns (about 5 minutes, cached)
python examples/siting_viz.py --open --rank   # one house, 100 profiles, second-site savings (out/siting.html)
python -m digitalheat                    # assumptions table (Markdown)
```

## Before reporting any number

- The job types in `examples/reference_year.py` are **placeholders**. Replace them with
  your measured runtimes, cited prices and stated daily arrivals.
- The tests use synthetic weather. Results must come from the Open-Meteo Basel 2025
  file or the profile CSV supplied with the case.
- Confirm the electricity price (33.25 Rp./kWh, ElCom 2026, IWB Basel, H4) on
  strompreis.elcom.admin.ch.

## Layout

| Path | Contents |
|---|---|
| `src/digitalheat/workload.py` | JobType, Measurement, ArrivalProcess, Task, Checkpoint, Demand |
| `src/digitalheat/compute.py` | Server, HardwareSpec, ServerRegistry |
| `src/digitalheat/heat.py` | Weather, HeatDemandProfile, HeatStorage, BackupHeater, HeatSignal, House |
| `src/digitalheat/scheduling.py` | Scheduler interface, HeatFollowingScheduler |
| `src/digitalheat/execution.py` | Action, Dispatcher, SimulatedExecutor, ProcessExecutor |
| `src/digitalheat/economics.py` | Tariff, Ledger, YearlyBalance |
| `src/digitalheat/simulation.py` | Fleet, Scenario, SimulationRun |
| `src/digitalheat/siting.py` | Screening model: heat requirement by location, compute shared between sites, second-site ranking |
| `src/digitalheat/assumptions.py` | AssumptionRegistry and the reference values |
| `src/digitalheat/clock.py` | Clock |
| `docs/ENTITIES.md` | Entity model: fields, relationships, invariants, open choices |

## Minimal use

```python
from digitalheat import ArrivalMode, ArrivalProcess, JobType, Scenario, WeatherSeries

weather = WeatherSeries.from_open_meteo_csv("data/open_meteo_basel_2025.csv")
job = JobType(id="llm_batch", name="Batch inference", runtime_h=4, power_kw=1.0,
              interruptible=True, price_chf_per_server_hour=0.20, source="<cite it>")
arrival = ArrivalProcess("llm_batch", ArrivalMode.UNLIMITED, source="<state it>")

scenario = Scenario("reference house", servers_per_house=3, job_types=[job], arrivals=[arrival])
run = scenario.build([scenario.reference_house(weather)], weather.start)
print(run.run()["ref"].summary())
```

To test another tank or price, override the assumption so the change stays visible:

```python
scenario.assumptions.override("tank_capacity_kwh", 70.0, source="what-if: double tank")
```
