"""Compute side: the servers and the registry that knows their state.

Entities
    HardwareSpec    optional description of a machine
    Server          one heat-producing server in a house
    ServerRegistry  every server, with lookups by house, region and state

Results are normalised to a 1 kW reference server, so the model only needs a
server's power, its recoverable heat fraction and what it is running.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ServerState(str, Enum):
    OFF = "off"          # no job, drawing idle power (0 by default)
    RUNNING = "running"
    FAILED = "failed"    # out of service; the scheduler skips it


@dataclass(frozen=True)
class HardwareSpec:
    """Descriptive only; the scheduler does not use it."""

    cpu_cores: int | None = None
    gpu_model: str | None = None
    ram_gb: float | None = None
    vram_gb: float | None = None


@dataclass
class Server:
    id: str
    house_id: str
    region: str
    power_kw: float                 # electricity at full load
    heat_recovery_fraction: float   # share of electricity recovered as useful heat
    idle_power_kw: float = 0.0
    hardware: HardwareSpec | None = None
    address: str | None = None      # host:port of the machine's executor agent
    # --- state ---
    state: ServerState = ServerState.OFF
    task_id: str | None = None
    throttle: float = 1.0           # 0 < throttle <= 1; scales power and progress
    # --- meters ---
    running_hours: float = 0.0
    electricity_kwh: float = 0.0
    heat_kwh: float = 0.0           # recoverable heat produced

    def __post_init__(self) -> None:
        if self.power_kw <= 0 or not 0 <= self.heat_recovery_fraction <= 1:
            raise ValueError(f"{self.id}: invalid power or heat recovery fraction")

    @property
    def is_free(self) -> bool:
        return self.state is ServerState.OFF

    def draw_kw(self, task_power_kw: float) -> float:
        """Electricity drawn while running a task of the given power."""
        return min(task_power_kw, self.power_kw) * self.throttle

    def heat_kw(self, task_power_kw: float) -> float:
        """Recoverable heat produced while running that task."""
        return self.draw_kw(task_power_kw) * self.heat_recovery_fraction

    def set_throttle(self, throttle: float) -> None:
        if not 0 < throttle <= 1:
            raise ValueError("throttle must be in (0, 1]")
        self.throttle = throttle

    def assign(self, task_id: str) -> None:
        if not self.is_free:
            raise RuntimeError(f"server {self.id} is {self.state.value}, cannot take {task_id}")
        self.state, self.task_id = ServerState.RUNNING, task_id

    def release(self) -> None:
        if self.state is ServerState.RUNNING:
            self.state = ServerState.OFF
        self.task_id = None

    def fail(self) -> str | None:
        """Take the server out of service; returns the task it was running."""
        task_id, self.task_id = self.task_id, None
        self.state = ServerState.FAILED
        return task_id

    def repair(self) -> None:
        if self.state is ServerState.FAILED:
            self.state = ServerState.OFF

    def run(self, hours: float, task_power_kw: float) -> tuple[float, float]:
        """Meter `hours` of running; returns (electricity kWh, recoverable heat kWh)."""
        electricity = self.draw_kw(task_power_kw) * hours
        heat = electricity * self.heat_recovery_fraction
        self.running_hours += hours
        self.electricity_kwh += electricity
        self.heat_kwh += heat
        return electricity, heat

    def idle(self, hours: float) -> tuple[float, float]:
        """Meter `hours` without a job."""
        if self.state is ServerState.FAILED:
            return 0.0, 0.0
        electricity = self.idle_power_kw * hours
        heat = electricity * self.heat_recovery_fraction
        self.electricity_kwh += electricity
        self.heat_kwh += heat
        return electricity, heat


class ServerRegistry:
    """Every server and its live state (the 'server list' a load balancer holds)."""

    def __init__(self) -> None:
        self._servers: dict[str, Server] = {}
        self._by_house: dict[str, list[Server]] = {}

    def add(self, server: Server) -> Server:
        if server.id in self._servers:
            raise KeyError(f"server {server.id!r} already registered")
        self._servers[server.id] = server
        self._by_house.setdefault(server.house_id, []).append(server)
        return server

    def get(self, server_id: str) -> Server:
        return self._servers[server_id]

    def all(self) -> list[Server]:
        return list(self._servers.values())

    def by_house(self, house_id: str) -> list[Server]:
        return list(self._by_house.get(house_id, ()))

    def free(self, house_id: str | None = None, region: str | None = None) -> list[Server]:
        servers = self.by_house(house_id) if house_id else self.all()
        return [s for s in servers if s.is_free and (region is None or s.region == region)]

    def running(self, house_id: str | None = None) -> list[Server]:
        servers = self.by_house(house_id) if house_id else self.all()
        return [s for s in servers if s.state is ServerState.RUNNING]

    def snapshot(self) -> list[dict]:
        """Plain-data view for a dashboard or an API response."""
        return [
            {
                "id": s.id, "house_id": s.house_id, "region": s.region,
                "state": s.state.value, "task_id": s.task_id, "throttle": s.throttle,
                "power_kw": s.power_kw, "running_hours": round(s.running_hours, 3),
                "electricity_kwh": round(s.electricity_kwh, 3), "heat_kwh": round(s.heat_kwh, 3),
            }
            for s in self._servers.values()
        ]
