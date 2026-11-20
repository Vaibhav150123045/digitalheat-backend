"""Heat side: weather, demand, storage, backup heating and the house.

Entities
    WeatherRecord / WeatherSeries   hourly temperature and irradiance
    HeatDemandProfile               hourly space heating and hot water demand
    HeatStorage                     the buffer tank
    BackupHeater                    whatever covers demand the servers cannot
    HeatSignal                      what a house tells the scheduler each step
    HeatFlows                       where one step's heat went
    House                           ties the above together and settles heat

Energy is in kWh per step, power in kW.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence

EPS = 1e-9


# --------------------------------------------------------------------------- Weather


@dataclass(frozen=True)
class WeatherRecord:
    t: int
    time: datetime              # local time
    temp_c: float
    ghi_w_m2: float | None = None   # global horizontal irradiance (for the solar stretch goal)


class WeatherSeries:
    def __init__(self, records: Sequence[WeatherRecord], source: str = "") -> None:
        self.records = list(records)
        self.source = source

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, t: int) -> WeatherRecord:
        return self.records[t]

    @property
    def start(self) -> datetime:
        return self.records[0].time

    @classmethod
    def from_temperatures(cls, temps_c: Sequence[float], start: datetime,
                          source: str = "synthetic") -> "WeatherSeries":
        return cls(
            [WeatherRecord(t, start + timedelta(hours=t), float(temp))
             for t, temp in enumerate(temps_c)],
            source,
        )

    @classmethod
    def from_open_meteo_csv(cls, path: str | Path) -> "WeatherSeries":
        """Read an Open-Meteo archive CSV (hourly temperature_2m, optional shortwave_radiation).

        The file starts with a short metadata block; data begins at the row
        whose first column is `time`.
        """
        records: list[WeatherRecord] = []
        with open(path, newline="", encoding="utf-8") as handle:
            rows = csv.reader(handle)
            header: list[str] | None = None
            for row in rows:
                if not row:
                    continue
                if header is None:
                    if row[0].strip().lower() == "time":
                        header = [col.strip().lower() for col in row]
                    continue
                temp_col = next(i for i, col in enumerate(header) if col.startswith("temperature_2m"))
                ghi_col = next((i for i, col in enumerate(header)
                                if col.startswith("shortwave_radiation")), None)
                ghi = float(row[ghi_col]) if ghi_col is not None and row[ghi_col] else None
                records.append(WeatherRecord(len(records), datetime.fromisoformat(row[0]),
                                             float(row[temp_col]), ghi))
        if not records:
            raise ValueError(f"no hourly rows found in {path}")
        return cls(records, f"Open-Meteo archive CSV: {Path(path).name}")

    def daily_mean_temps(self) -> dict:
        """Mean hourly temperature per local calendar day."""
        sums: dict = {}
        for record in self.records:
            total, count = sums.get(record.time.date(), (0.0, 0))
            sums[record.time.date()] = (total + record.temp_c, count + 1)
        return {day: total / count for day, (total, count) in sums.items()}


# ----------------------------------------------------------------- HeatDemandProfile


@dataclass(frozen=True)
class HeatDemandProfile:
    space_heating_kwh: tuple[float, ...]   # per step
    hot_water_kwh: tuple[float, ...]       # per step
    dt_h: float = 1.0
    source: str = ""

    def __post_init__(self) -> None:
        if len(self.space_heating_kwh) != len(self.hot_water_kwh):
            raise ValueError("space heating and hot water series differ in length")

    def __len__(self) -> int:
        return len(self.space_heating_kwh)

    def demand_kwh(self, t: int) -> float:
        return self.space_heating_kwh[t] + self.hot_water_kwh[t]

    def forecast_kwh(self, t: int, horizon: int) -> tuple[float, ...]:
        """Demand for steps t .. t+horizon-1 (a perfect forecast from the profile)."""
        return tuple(self.demand_kwh(i) for i in range(t, min(t + horizon, len(self))))

    @property
    def total_space_heating_kwh(self) -> float:
        return sum(self.space_heating_kwh)

    @property
    def total_hot_water_kwh(self) -> float:
        return sum(self.hot_water_kwh)

    @property
    def total_kwh(self) -> float:
        return self.total_space_heating_kwh + self.total_hot_water_kwh

    @classmethod
    def reference_house(cls, weather: WeatherSeries, *, design_load_kw: float,
                        indoor_setpoint_c: float, design_delta_k: float,
                        heating_day_threshold_c: float, hot_water_kwh_per_day: float,
                        hot_water_shape: Sequence[float] | None = None,
                        dt_h: float = 1.0) -> "HeatDemandProfile":
        """The brief's formula.

        Space heating = max(0, load x (setpoint - T) / delta) on heating days
        only; a heating day is a local calendar day whose mean hourly
        temperature is below the threshold. Hot water is the same every day.
        """
        if hot_water_shape is not None and (
            len(hot_water_shape) != 24 or abs(sum(hot_water_shape) - 1) > 1e-6
        ):
            raise ValueError("hot_water_shape needs 24 weights summing to 1")
        daily_mean = weather.daily_mean_temps()
        space, water = [], []
        for record in weather.records:
            heating_day = daily_mean[record.time.date()] < heating_day_threshold_c
            load_kw = max(0.0, design_load_kw * (indoor_setpoint_c - record.temp_c) / design_delta_k)
            space.append(load_kw * dt_h if heating_day else 0.0)
            weight = hot_water_shape[record.time.hour] if hot_water_shape else 1 / 24
            water.append(hot_water_kwh_per_day * weight * dt_h)
        return cls(tuple(space), tuple(water), dt_h,
                   f"reference-house formula on {weather.source}")

    @classmethod
    def from_shape(cls, shape: Sequence[float], *, annual_space_heating_kwh: float,
                   hot_water_kwh_per_day: float, dt_h: float = 1.0,
                   source: str = "") -> "HeatDemandProfile":
        """Scale any hourly shape (e.g. a column of a load-profile CSV) to an annual total."""
        total = sum(shape)
        if total <= 0:
            raise ValueError("shape must contain positive values")
        space = tuple(value / total * annual_space_heating_kwh for value in shape)
        water = tuple(hot_water_kwh_per_day / 24 * dt_h for _ in shape)
        return cls(space, water, dt_h, source)

    @classmethod
    def from_csv(cls, path: str | Path, *, space_heating_col: str,
                 hot_water_col: str | None = None, hot_water_kwh_per_day: float = 0.0,
                 scale: float = 1.0, dt_h: float = 1.0) -> "HeatDemandProfile":
        """Read a ready-made profile whose columns are already in kWh per step
        (use `scale` to convert units)."""
        space, water = [], []
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                space.append(float(row[space_heating_col]) * scale)
                if hot_water_col:
                    water.append(float(row[hot_water_col]) * scale)
                else:
                    water.append(hot_water_kwh_per_day / 24 * dt_h)
        return cls(tuple(space), tuple(water), dt_h, f"CSV profile: {Path(path).name}")


def read_csv_column(path: str | Path, column: str) -> list[float]:
    """One numeric column of a CSV, e.g. `SFH_OLD (MWh)` from the HSR profile."""
    with open(path, newline="", encoding="utf-8") as handle:
        return [float(row[column]) for row in csv.DictReader(handle)]


# ----------------------------------------------------------------------- HeatStorage


@dataclass
class HeatStorage:
    capacity_kwh: float
    soc_kwh: float = 0.0                 # state of charge
    loss_fraction_per_h: float = 0.0

    def __post_init__(self) -> None:
        if self.capacity_kwh < 0 or not 0 <= self.soc_kwh <= self.capacity_kwh + EPS:
            raise ValueError("invalid tank capacity or state of charge")

    @property
    def headroom_kwh(self) -> float:
        return max(0.0, self.capacity_kwh - self.soc_kwh)

    def charge(self, kwh: float) -> float:
        """Store up to `kwh`; returns what was accepted."""
        accepted = min(max(kwh, 0.0), self.headroom_kwh)
        self.soc_kwh += accepted
        return accepted

    def discharge(self, kwh: float) -> float:
        """Draw up to `kwh`; returns what was delivered."""
        delivered = min(max(kwh, 0.0), self.soc_kwh)
        self.soc_kwh -= delivered
        return delivered

    def apply_losses(self, hours: float) -> float:
        lost = self.soc_kwh * (1 - (1 - self.loss_fraction_per_h) ** hours)
        self.soc_kwh -= lost
        return lost


# ---------------------------------------------------------------------- BackupHeater


@dataclass
class BackupHeater:
    """Covers heat demand that servers and tank cannot (a heat pump in the brief)."""

    cop: float
    heat_kwh: float = 0.0

    def supply(self, kwh: float) -> float:
        self.heat_kwh += max(kwh, 0.0)
        return max(kwh, 0.0)

    @property
    def electricity_kwh(self) -> float:
        return self.heat_kwh / self.cop


# ------------------------------------------------------------- HeatSignal, HeatFlows


@dataclass(frozen=True)
class HeatSignal:
    """The one input that steers scheduling: how much heat a house can use now."""

    house_id: str
    t: int
    demand_kwh: float                  # space heating + hot water this step
    tank_soc_kwh: float
    tank_headroom_kwh: float
    forecast_kwh: tuple[float, ...] = ()   # demand for this and the following steps

    @property
    def absorbable_kwh(self) -> float:
        """Server heat that can be used or stored this step without dumping."""
        return self.demand_kwh + self.tank_headroom_kwh

    def servers_wanted(self, heat_per_server_kwh: float) -> int:
        return int(math.floor(self.absorbable_kwh / heat_per_server_kwh + EPS))


@dataclass(frozen=True)
class HeatFlows:
    """Where one step's heat went.

    server_heat = direct + to_tank + dumped
    demand      = direct + from_tank + backup
    """

    demand_kwh: float
    server_heat_kwh: float
    direct_kwh: float       # server heat used immediately
    to_tank_kwh: float
    from_tank_kwh: float
    dumped_kwh: float       # server heat nobody could use
    backup_kwh: float       # demand left for the backup heater
    tank_loss_kwh: float
    tank_soc_kwh: float     # after the step

    @property
    def covered_kwh(self) -> float:
        """Demand met by server heat, directly or via the tank."""
        return self.direct_kwh + self.from_tank_kwh


# ----------------------------------------------------------------------------- House


@dataclass
class House:
    id: str
    name: str
    region: str                # e.g. "CH-NW"; matched against task region constraints
    latitude: float
    longitude: float
    profile: HeatDemandProfile
    storage: HeatStorage
    backup: BackupHeater
    server_ids: list[str] = field(default_factory=list)

    def heat_signal(self, t: int, horizon: int = 24) -> HeatSignal:
        return HeatSignal(
            house_id=self.id,
            t=t,
            demand_kwh=self.profile.demand_kwh(t),
            tank_soc_kwh=self.storage.soc_kwh,
            tank_headroom_kwh=self.storage.headroom_kwh,
            forecast_kwh=self.profile.forecast_kwh(t, horizon),
        )

    def settle(self, t: int, server_heat_kwh: float) -> HeatFlows:
        """Account for one step: server heat first meets demand, the surplus
        charges the tank, the tank covers what is still missing, and the backup
        heater takes the rest."""
        demand = self.profile.demand_kwh(t)
        direct = min(server_heat_kwh, demand)
        surplus = server_heat_kwh - direct
        to_tank = self.storage.charge(surplus)
        dumped = surplus - to_tank
        if dumped < EPS:                 # float noise, not real heat
            dumped = 0.0
        residual = demand - direct
        from_tank = self.storage.discharge(residual)
        backup = self.backup.supply(residual - from_tank)
        loss = self.storage.apply_losses(self.profile.dt_h)
        return HeatFlows(demand, server_heat_kwh, direct, to_tank, from_tank, dumped,
                         backup, loss, self.storage.soc_kwh)
