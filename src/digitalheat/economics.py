"""Economics and reporting: prices, the hourly ledger and the yearly balance.

Entities
    Tariff         electricity price, heat value and fixed costs
    HourRecord     one house, one step: heat flows, electricity, income
    Ledger         every HourRecord of a run
    YearlyBalance  the figures the brief asks for, per house
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, fields
from pathlib import Path

from .heat import HeatFlows


@dataclass(frozen=True)
class Tariff:
    electricity_chf_per_kwh: float
    heat_pump_cop: float                          # heat value = electricity price / COP
    fixed_cost_chf_per_server_year: float = 0.0   # hardware, installation, maintenance
    source: str = ""

    @property
    def heat_value_chf_per_kwh(self) -> float:
        """What a kWh of useful server heat is worth: the heat-pump electricity it replaces."""
        return self.electricity_chf_per_kwh / self.heat_pump_cop


@dataclass(frozen=True)
class HourRecord:
    t: int
    house_id: str
    flows: HeatFlows
    electricity_kwh: float        # drawn by the house's servers
    running_server_hours: float
    servers_running: int
    income_chf: float             # computing income earned in this step


@dataclass(frozen=True)
class YearlyBalance:
    house_id: str
    steps: int
    servers: int
    heat_demand_kwh: float
    heat_covered_kwh: float            # demand met by server heat (direct or via tank)
    covered_share: float               # heat_covered / heat_demand
    server_heat_kwh: float             # recoverable heat the servers produced
    heat_dumped_kwh: float
    backup_heat_kwh: float
    running_server_hours: float
    utilisation: float                 # running hours / (servers x hours in the run)
    missed_deadline_pct: float         # fleet-wide: tasks are not owned by a house
    electricity_kwh: float
    electricity_cost_chf: float
    heat_value_chf: float
    computing_income_chf: float
    fixed_cost_chf: float
    net_chf: float                     # income + heat value - electricity - fixed cost
    break_even_chf_per_server_hour: float | None   # None if no server ever ran

    @property
    def pays_off(self) -> bool:
        return self.net_chf >= 0

    def summary(self) -> str:
        break_even = ("n/a" if self.break_even_chf_per_server_hour is None
                      else f"{self.break_even_chf_per_server_hour:.3f} CHF")
        verdict = "pays off" if self.pays_off else "does NOT pay off"
        return "\n".join([
            f"House {self.house_id}: {self.servers} server(s), {self.steps} hours",
            f"  Heat demand            {self.heat_demand_kwh:10.0f} kWh",
            f"  Covered by servers     {self.heat_covered_kwh:10.0f} kWh ({self.covered_share:.1%})",
            f"  Heat dumped            {self.heat_dumped_kwh:10.0f} kWh",
            f"  Utilisation            {self.utilisation:10.1%}",
            f"  Missed deadlines       {self.missed_deadline_pct:10.1f} %",
            f"  Electricity cost       {self.electricity_cost_chf:10.0f} CHF",
            f"  Heat value             {self.heat_value_chf:10.0f} CHF",
            f"  Computing income       {self.computing_income_chf:10.0f} CHF",
            f"  Net                    {self.net_chf:10.0f} CHF -> {verdict}",
            f"  Break-even price       {break_even} per server-hour",
        ])


class Ledger:
    def __init__(self) -> None:
        self.records: list[HourRecord] = []

    def record(self, record: HourRecord) -> None:
        self.records.append(record)

    def for_house(self, house_id: str) -> list[HourRecord]:
        return [r for r in self.records if r.house_id == house_id]

    def window(self, house_id: str, first_t: int, steps: int) -> list[HourRecord]:
        """Records of one stretch, e.g. a January day for the demo."""
        return [r for r in self.for_house(house_id) if first_t <= r.t < first_t + steps]

    def balance(self, house_id: str, servers: int, tariff: Tariff, dt_h: float = 1.0,
                missed_deadline_pct: float = 0.0) -> YearlyBalance:
        records = self.for_house(house_id)
        steps = len(records)
        hours = steps * dt_h
        demand = sum(r.flows.demand_kwh for r in records)
        covered = sum(r.flows.covered_kwh for r in records)
        running = sum(r.running_server_hours for r in records)
        electricity = sum(r.electricity_kwh for r in records)
        income = sum(r.income_chf for r in records)
        cost = electricity * tariff.electricity_chf_per_kwh
        heat_value = covered * tariff.heat_value_chf_per_kwh
        fixed = tariff.fixed_cost_chf_per_server_year * servers * hours / 8760
        return YearlyBalance(
            house_id=house_id,
            steps=steps,
            servers=servers,
            heat_demand_kwh=demand,
            heat_covered_kwh=covered,
            covered_share=covered / demand if demand else 0.0,
            server_heat_kwh=sum(r.flows.server_heat_kwh for r in records),
            heat_dumped_kwh=sum(r.flows.dumped_kwh for r in records),
            backup_heat_kwh=sum(r.flows.backup_kwh for r in records),
            running_server_hours=running,
            utilisation=running / (servers * hours) if servers and hours else 0.0,
            missed_deadline_pct=missed_deadline_pct,
            electricity_kwh=electricity,
            electricity_cost_chf=cost,
            heat_value_chf=heat_value,
            computing_income_chf=income,
            fixed_cost_chf=fixed,
            net_chf=income + heat_value - cost - fixed,
            break_even_chf_per_server_hour=(cost + fixed - heat_value) / running if running else None,
        )

    def to_csv(self, path: str | Path) -> None:
        """Hourly records as CSV, so every yearly figure can be recomputed by hand."""
        flow_cols = [f.name for f in fields(HeatFlows)]
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["t", "house_id", *flow_cols, "electricity_kwh",
                             "running_server_hours", "servers_running", "income_chf"])
            for r in self.records:
                writer.writerow([r.t, r.house_id, *(getattr(r.flows, c) for c in flow_cols),
                                 r.electricity_kwh, r.running_server_hours,
                                 r.servers_running, r.income_chf])
