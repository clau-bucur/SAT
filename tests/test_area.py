from datetime import timedelta

import pytest
from homeassistant.components.climate import HVACAction, HVACMode
from homeassistant.util import dt as dt_util

from custom_components.sat.area import Area, Areas, ATTR_SENSOR_TEMPERATURE_ID
from custom_components.sat.const import CONF_HEATING_SYSTEM, CONF_SENSOR_MAX_VALUE_AGE, OPTIONS_DEFAULTS
from custom_components.sat.types import HeatingSystem
from tests.const import make_config


async def test_area_current_temperature_stale_climate_state(hass, monkeypatch):
    now = dt_util.utcnow()
    monkeypatch.setattr(dt_util, "utcnow", lambda: now)
    hass.states.async_set("climate.room1", "heat", {"current_temperature": 21.0})

    config_options = dict(OPTIONS_DEFAULTS)
    config_options[CONF_SENSOR_MAX_VALUE_AGE] = "00:01:00"
    config = make_config(data={CONF_HEATING_SYSTEM: HeatingSystem.RADIATORS}, options=config_options)

    area = Area(config, "climate.room1")
    await area.async_added_to_hass(hass, "device.test")

    monkeypatch.setattr(dt_util, "utcnow", lambda: now + timedelta(seconds=120))

    assert area.current_temperature is None


async def test_area_off_climate_is_excluded(hass):
    hass.states.async_set("climate.room1", HVACMode.OFF, {"temperature": 21.0, "current_temperature": 18.0})

    config = make_config(data={CONF_HEATING_SYSTEM: HeatingSystem.RADIATORS}, options=dict(OPTIONS_DEFAULTS))

    area = Area(config, "climate.room1")
    await area.async_added_to_hass(hass, "device.test")

    assert area.climate_state is None
    assert area.target_temperature is None
    assert area.current_temperature is None
    assert area.temperature_state is None
    assert area.requires_heat is False


async def test_area_heat_climate_is_included(hass):
    hass.states.async_set("climate.room1", HVACMode.HEAT, {"temperature": 21.0, "current_temperature": 18.0})

    config = make_config(data={CONF_HEATING_SYSTEM: HeatingSystem.RADIATORS}, options=dict(OPTIONS_DEFAULTS))

    area = Area(config, "climate.room1")
    await area.async_added_to_hass(hass, "device.test")

    assert area.climate_state is not None
    assert area.target_temperature == 21.0
    assert area.current_temperature == 18.0


async def test_area_current_temperature_stale_override_sensor(hass, monkeypatch):
    now = dt_util.utcnow()
    monkeypatch.setattr(dt_util, "utcnow", lambda: now)
    hass.states.async_set(
        "climate.room1",
        "heat",
        {
            "current_temperature": 21.0,
            ATTR_SENSOR_TEMPERATURE_ID: "sensor.room1_temp",
        },
    )
    hass.states.async_set("sensor.room1_temp", "20.5")

    config_options = dict(OPTIONS_DEFAULTS)
    config_options[CONF_SENSOR_MAX_VALUE_AGE] = "00:01:00"
    config = make_config(data={CONF_HEATING_SYSTEM: HeatingSystem.RADIATORS}, options=config_options)

    area = Area(config, "climate.room1")
    await area.async_added_to_hass(hass, "device.test")

    monkeypatch.setattr(dt_util, "utcnow", lambda: now + timedelta(seconds=120))

    assert area.current_temperature is None


async def test_area_remembers_when_its_target_changed(hass):
    hass.states.async_set("climate.room1", HVACMode.HEAT, {"temperature": 18.0, "current_temperature": 17.5})

    config = make_config(data={CONF_HEATING_SYSTEM: HeatingSystem.RADIATORS}, options=dict(OPTIONS_DEFAULTS))

    area = Area(config, "climate.room1")
    await area.async_added_to_hass(hass, "device.test")

    area.control_pid(dt_util.utc_from_timestamp(1000.0))
    area.control_pid(dt_util.utc_from_timestamp(1060.0))
    assert area.driving_room.target_temperature_changed_at == 1000.0
    assert area.driving_room.error == 0.5

    hass.states.async_set("climate.room1", HVACMode.HEAT, {"temperature": 20.0, "current_temperature": 17.5})
    area.control_pid(dt_util.utc_from_timestamp(1120.0))
    assert area.driving_room.target_temperature_changed_at == 1120.0


@pytest.mark.parametrize(
    ("action", "valve_position", "requires_heat"),
    [
        (HVACAction.IDLE, None, False),
        (HVACAction.HEATING, None, True),
        (HVACAction.IDLE, 0, False),
        (HVACAction.IDLE, 50, True),
        (None, None, False),
    ],
)
async def test_only_open_or_calling_rooms_can_limit_other_rooms(hass, action, valve_position, requires_heat):
    attributes = {"temperature": 21.0, "current_temperature": 21.4}
    if action is not None:
        attributes["hvac_action"] = action
    if valve_position is not None:
        attributes["current_valve_position"] = valve_position
    hass.states.async_set("climate.sanctuary", HVACMode.HEAT, attributes)

    area = Area(make_config(), "climate.sanctuary")
    area._hass = hass
    area.heating_curve._value = 40.0
    area.pid._last_error = -0.4

    assert area.pid.available is True
    assert area.pid.output > 22.0
    assert area.requires_heat is requires_heat
    assert Areas([area]).pids.overshoot_cap == (30.4 if requires_heat else None)


async def test_idle_upstairs_room_does_not_throttle_living_demand(hass):
    hass.states.async_set("climate.living", HVACMode.HEAT, {"temperature": 22.5, "current_temperature": 22.4, "hvac_action": HVACAction.HEATING})
    hass.states.async_set("climate.sanctuary", HVACMode.HEAT, {"temperature": 21.0, "current_temperature": 21.4, "hvac_action": HVACAction.IDLE})

    rooms = []
    for entity_id, error in [("climate.living", 0.1), ("climate.sanctuary", -0.4)]:
        area = Area(make_config(), entity_id)
        area._hass = hass
        area.heating_curve._value = 40.0
        area.pid._last_error = error
        rooms.append(area)

    pids = Areas(rooms).pids
    requested = min(pids.output, pids.overshoot_cap) if pids.overshoot_cap is not None else pids.output

    assert requested == rooms[0].pid.output
    assert requested > 40.0
