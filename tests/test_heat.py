from datetime import datetime

import pytest

from digitalheat import (BackupHeater, HeatDemandProfile, HeatStorage, House, WeatherSeries,
                         reference_assumptions)

START = datetime(2025, 1, 1)


def reference_profile(temps):
    a = reference_assumptions()
    return HeatDemandProfile.reference_house(
        WeatherSeries.from_temperatures(temps, START),
        design_load_kw=a.value("design_heat_load_kw"),
        indoor_setpoint_c=a.value("indoor_setpoint_c"),
        design_delta_k=a.value("design_delta_k"),
        heating_day_threshold_c=a.value("heating_day_threshold_c"),
        hot_water_kwh_per_day=a.value("hot_water_kwh_per_day"),
    )


def test_design_day_needs_ten_kilowatts():
    profile = reference_profile([-5.6] * 24)
    assert profile.space_heating_kwh[0] == pytest.approx(10.0)
    assert profile.total_hot_water_kwh == pytest.approx(12.0)


def test_no_heating_on_a_warm_day_even_in_a_cold_hour():
    temps = [18.0] * 24
    temps[3] = 5.0                       # one cold hour, daily mean still above 12
    profile = reference_profile(temps)
    assert profile.total_space_heating_kwh == 0


def test_heating_day_is_decided_per_calendar_day():
    profile = reference_profile([5.0] * 24 + [15.0] * 24)
    assert sum(profile.space_heating_kwh[:24]) > 0
    assert sum(profile.space_heating_kwh[24:]) == 0


def test_no_negative_demand_above_setpoint():
    temps = [25.0] * 12 + [-10.0] * 12   # mean 7.5: a heating day with hot hours
    profile = reference_profile(temps)
    assert min(profile.space_heating_kwh) == 0


def test_tank_limits():
    tank = HeatStorage(capacity_kwh=35)
    assert tank.charge(40) == 35
    assert tank.headroom_kwh == 0
    assert tank.discharge(50) == 35
    assert tank.soc_kwh == 0


def test_shape_scales_to_annual_total():
    profile = HeatDemandProfile.from_shape([4.0, 2.0, 0.0, 2.0], annual_space_heating_kwh=800,
                                           hot_water_kwh_per_day=12)
    assert profile.total_space_heating_kwh == pytest.approx(800)
    assert profile.space_heating_kwh[0] == pytest.approx(400)


@pytest.mark.parametrize("server_heat", [0.0, 0.3, 4.0, 60.0])
def test_settle_conserves_energy(server_heat):
    house = House("h", "House", "CH-NW", 47.56, 7.59, reference_profile([0.0] * 24),
                  HeatStorage(35, soc_kwh=5), BackupHeater(cop=2.5))
    flows = house.settle(0, server_heat)
    assert flows.server_heat_kwh == pytest.approx(
        flows.direct_kwh + flows.to_tank_kwh + flows.dumped_kwh)
    assert flows.demand_kwh == pytest.approx(
        flows.direct_kwh + flows.from_tank_kwh + flows.backup_kwh)
    assert 0 <= flows.tank_soc_kwh <= 35


def test_open_meteo_csv(tmp_path):
    path = tmp_path / "weather.csv"
    path.write_text(
        "latitude,longitude,elevation,utc_offset_seconds,timezone,timezone_abbreviation\n"
        "47.55,7.58,260.0,3600,Europe/Zurich,GMT+1\n"
        "\n"
        "time,temperature_2m (°C),shortwave_radiation (W/m²)\n"
        "2025-01-01T00:00,1.5,0.0\n"
        "2025-01-01T01:00,-0.5,0.0\n",
        encoding="utf-8",
    )
    weather = WeatherSeries.from_open_meteo_csv(path)
    assert len(weather) == 2
    assert weather[1].temp_c == -0.5
    assert weather[0].ghi_w_m2 == 0.0
    assert weather.start == datetime(2025, 1, 1)
