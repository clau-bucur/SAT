"""The tests for the climate component."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.components.climate import HVACMode
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.template import DOMAIN as TEMPLATE_DOMAIN
from homeassistant.const import UnitOfTemperature
from homeassistant.core import CoreState, HassJob, HassJobType, HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sat.climate import SatClimate
from custom_components.sat.entity import SatEntity
from custom_components.sat.const import *
from custom_components.sat.fake import SatFakeCoordinator
from tests.const import DEFAULT_USER_DATA


@pytest.mark.parametrize(*[
    "domains, data, options, config",
    [(
            [(TEMPLATE_DOMAIN, 1)],
            {
                CONF_MODE: MODE_FAKE,
                CONF_HEATING_SYSTEM: HEATING_SYSTEM_RADIATORS,
                CONF_MINIMUM_SETPOINT: 57,
                CONF_MAXIMUM_SETPOINT: 75,
            },
            {
                CONF_HEATING_CURVE_COEFFICIENT: 1.8,
                CONF_FORCE_PULSE_WIDTH_MODULATION: True,
                # Expected values describe the original PID and cycle settings.
                CONF_PID_CONTROLLER_VERSION: 1,
                CONF_CYCLES_PER_HOUR: 3,
            },
            {
                TEMPLATE_DOMAIN: [
                    {
                        SENSOR_DOMAIN: [
                            {
                                "name": "test_inside_sensor",
                                "state": "{{ 20.9 | float }}",
                            },
                            {
                                "name": "test_outside_sensor",
                                "state": "{{ 9.9 | float }}",
                            }
                        ]
                    },
                ],
            },
    )],
])
async def test_scenario_1(hass: HomeAssistant, entry: MockConfigEntry, climate: SatClimate, coordinator: SatFakeCoordinator) -> None:
    await coordinator.async_set_boiler_temperature(57)
    await climate.async_set_target_temperature(21.0)
    await climate.async_set_hvac_mode(HVACMode.HEAT)
    climate.schedule_control_heating_loop(force=True)
    await hass.async_block_till_done()

    assert climate.setpoint == 57
    assert climate.heating_curve.value == 32.2

    assert climate.pulse_width_modulation_enabled
    assert climate.pwm.last_duty_cycle_percentage == 23.83
    assert climate.pwm.duty_cycle == (285, 914)


@pytest.mark.parametrize(*[
    "domains, data, options, config",
    [(
            [(TEMPLATE_DOMAIN, 1)],
            {
                CONF_MODE: MODE_FAKE,
                CONF_HEATING_SYSTEM: HEATING_SYSTEM_RADIATORS,
                CONF_MINIMUM_SETPOINT: 58,
                CONF_MAXIMUM_SETPOINT: 75
            },
            {
                CONF_HEATING_CURVE_COEFFICIENT: 1.3,
                CONF_FORCE_PULSE_WIDTH_MODULATION: True,
                # Expected values describe the original PID and cycle settings.
                CONF_PID_CONTROLLER_VERSION: 1,
                CONF_CYCLES_PER_HOUR: 3,
            },
            {
                TEMPLATE_DOMAIN: [
                    {
                        SENSOR_DOMAIN: [
                            {
                                "name": "test_inside_sensor",
                                "state": "{{ 18.99 | float }}",
                            },
                            {
                                "name": "test_outside_sensor",
                                "state": "{{ 11.1 | float }}",
                            }
                        ]
                    },
                ],
            },
    )],
])
async def test_scenario_2(hass: HomeAssistant, entry: MockConfigEntry, climate: SatClimate, coordinator: SatFakeCoordinator) -> None:
    await coordinator.async_set_boiler_temperature(58)
    await climate.async_set_target_temperature(19.0)
    await climate.async_set_hvac_mode(HVACMode.HEAT)
    climate.schedule_control_heating_loop(force=True)
    await hass.async_block_till_done()

    assert climate.setpoint == 10
    assert climate.heating_curve.value == 27.8
    assert climate.requested_setpoint == 28.0

    assert climate.pulse_width_modulation_enabled
    assert climate.pwm.last_duty_cycle_percentage == 2.6
    assert climate.pwm.duty_cycle == (0, 2400)


@pytest.mark.parametrize(*[
    "domains, data, options, config",
    [(
            [(TEMPLATE_DOMAIN, 1)],
            {
                CONF_MODE: MODE_FAKE,
                CONF_HEATING_SYSTEM: HEATING_SYSTEM_RADIATORS,
                CONF_MINIMUM_SETPOINT: 41,
                CONF_MAXIMUM_SETPOINT: 75,
            },
            {
                CONF_HEATING_CURVE_COEFFICIENT: 0.9,
                CONF_FORCE_PULSE_WIDTH_MODULATION: True,
                # Expected values describe the original PID and cycle settings.
                CONF_PID_CONTROLLER_VERSION: 1,
                CONF_CYCLES_PER_HOUR: 3,
            },
            {
                TEMPLATE_DOMAIN: [
                    {
                        SENSOR_DOMAIN: [
                            {
                                "name": "test_inside_sensor",
                                "state": "{{ 19.9 | float }}",
                            },
                            {
                                "name": "test_outside_sensor",
                                "state": "{{ -2.2 | float }}",
                            }
                        ]
                    },
                ],
            },
    )],
])
async def test_scenario_3(hass: HomeAssistant, entry: MockConfigEntry, climate: SatClimate, coordinator: SatFakeCoordinator) -> None:
    await coordinator.async_set_boiler_temperature(41)
    await climate.async_set_target_temperature(20.0)
    await climate.async_set_hvac_mode(HVACMode.HEAT)
    climate.schedule_control_heating_loop(force=True)
    await hass.async_block_till_done()

    assert climate.setpoint == 41.0
    assert climate.heating_curve.value == 32.5
    assert climate.requested_setpoint == 34.6

    assert climate.pulse_width_modulation_enabled
    assert climate.pwm.last_duty_cycle_percentage == 53.62
    assert climate.pwm.duty_cycle == (643, 556)


@pytest.fixture
def scheduler_climate(hass: HomeAssistant) -> SatClimate:
    """Build the controller without loading unrelated integrations or test climates."""
    data = {
        **DEFAULT_USER_DATA,
        CONF_HEATING_SYSTEM: HEATING_SYSTEM_RADIATORS,
        CONF_MINIMUM_SETPOINT: 26.4,
    }
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    coordinator = SatFakeCoordinator(hass, data)
    result = SatClimate(coordinator, entry, UnitOfTemperature.CELSIUS)
    result.hass = hass
    result.entity_id = "climate.scheduler_test"
    return result


def test_control_scheduler_runs_on_event_loop(scheduler_climate: SatClimate) -> None:
    """The interval helper must not dispatch scheduling work to an executor thread."""
    job = HassJob(scheduler_climate.schedule_control_heating_loop)
    assert job.job_type is HassJobType.Callback


async def test_control_scheduler_coalesces_and_clears_pending_timer(
    hass: HomeAssistant, scheduler_climate: SatClimate
) -> None:
    """Repeated updates keep one timer, and its control job releases pending state."""
    cancel = Mock()
    with (
        patch("custom_components.sat.climate.async_call_later", return_value=cancel) as timer,
        patch.object(
            scheduler_climate,
            "async_control_heating_loop",
            new=AsyncMock(wraps=scheduler_climate.async_control_heating_loop),
        ) as control,
    ):
        for _ in range(6):
            scheduler_climate.schedule_control_heating_loop()

        timer.assert_called_once()
        assert timer.call_args.args[:2] == (hass, 10)
        assert scheduler_climate._control_heating_loop_unsub is cancel
        assert scheduler_climate._control_heating_loop_deadline is not None
        control.assert_not_awaited()

        # Dispatch the captured timer's real HassJob through HA. Missing sensor
        # data makes the production loop return after releasing scheduler state.
        hass.async_run_hass_job(timer.call_args.args[2], dt_util.utcnow())
        await hass.async_block_till_done()

        control.assert_awaited_once()
        assert scheduler_climate._control_heating_loop_unsub is None
        assert scheduler_climate._control_heating_loop_deadline is None


@pytest.mark.parametrize("pending", [False, True], ids=["idle", "pending-timer"])
async def test_force_control_runs_immediately(
    hass: HomeAssistant, scheduler_climate: SatClimate, pending: bool
) -> None:
    """A forced update must execute immediately even when no timer exists."""
    cancel = Mock()
    if pending:
        scheduler_climate._control_heating_loop_unsub = cancel
        scheduler_climate._control_heating_loop_deadline = 100

    with (
        patch("custom_components.sat.climate.async_call_later") as timer,
        patch.object(
            scheduler_climate,
            "async_control_heating_loop",
            new=AsyncMock(wraps=scheduler_climate.async_control_heating_loop),
        ) as control,
    ):
        scheduler_climate.schedule_control_heating_loop(force=True)
        await hass.async_block_till_done()

        control.assert_awaited_once()
        timer.assert_not_called()
        if pending:
            cancel.assert_called_once_with()
        else:
            cancel.assert_not_called()
        assert scheduler_climate._control_heating_loop_unsub is None
        assert scheduler_climate._control_heating_loop_deadline is None


@pytest.mark.parametrize(
    ("deadline", "recover"),
    [(None, True), (69.0, True), (70.0, False), (110.0, False)],
    ids=["missing-deadline", "overdue", "grace-boundary", "fresh"],
)
def test_control_scheduler_recovers_only_stale_pending_state(
    scheduler_climate: SatClimate, deadline: float | None, recover: bool
) -> None:
    """A stale handle cannot suppress control forever; fresh timers still coalesce."""
    old_cancel = Mock()
    new_cancel = Mock()
    scheduler_climate._control_heating_loop_unsub = old_cancel
    scheduler_climate._control_heating_loop_deadline = deadline

    with (
        patch("custom_components.sat.climate.monotonic", return_value=100.0),
        patch("custom_components.sat.climate.async_call_later", return_value=new_cancel) as timer,
    ):
        scheduler_climate.schedule_control_heating_loop()

    if recover:
        old_cancel.assert_called_once_with()
        timer.assert_called_once()
        assert scheduler_climate._control_heating_loop_unsub is new_cancel
        assert scheduler_climate._control_heating_loop_deadline == 110.0
    else:
        old_cancel.assert_not_called()
        timer.assert_not_called()
        assert scheduler_climate._control_heating_loop_unsub is old_cancel
        assert scheduler_climate._control_heating_loop_deadline == deadline


async def test_removed_climate_stops_pending_and_queued_control(
    hass: HomeAssistant, scheduler_climate: SatClimate
) -> None:
    """Removal cancels the timer and blocks callbacks queued before removal."""
    cancel = Mock()
    hass.states.async_set(scheduler_climate.inside_sensor_entity_id, "20")
    hass.states.async_set(scheduler_climate.outside_sensor_entities[0], "5")
    scheduler_climate._target_temperature = 22
    scheduler_climate._hvac_mode = HVACMode.HEAT
    scheduler_climate._control_heating_loop_unsub = cancel
    scheduler_climate._control_heating_loop_deadline = 100

    with (
        patch("custom_components.sat.climate.async_call_later") as timer,
        patch.object(scheduler_climate._coordinator, "async_control_heating_loop") as boiler,
    ):
        scheduler_climate._async_stop_control_heating_loop()
        scheduler_climate._async_stop_control_heating_loop()
        scheduler_climate.schedule_control_heating_loop()
        scheduler_climate.schedule_control_heating_loop(force=True)
        await scheduler_climate.async_control_heating_loop()
        await hass.async_block_till_done()

        cancel.assert_called_once_with()
        timer.assert_not_called()
        boiler.assert_not_awaited()
        assert scheduler_climate._control_heating_loop_unsub is None
        assert scheduler_climate._control_heating_loop_deadline is None


async def test_added_climate_registers_scheduler_cleanup(
    hass: HomeAssistant, scheduler_climate: SatClimate, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The entity lifecycle owns timer cleanup, including integration reloads."""
    monkeypatch.setattr(hass, "state", CoreState.running)
    with (
        patch.object(SatEntity, "async_added_to_hass", new=AsyncMock()),
        patch.object(scheduler_climate, "_restore_previous_state_or_set_defaults", new=AsyncMock()),
        patch.object(scheduler_climate, "_register_event_listeners", new=AsyncMock()),
        patch.object(scheduler_climate, "_register_services", new=AsyncMock()),
        patch.object(scheduler_climate.areas, "async_added_to_hass", new=AsyncMock()),
        patch.object(scheduler_climate._coordinator, "async_added_to_hass", new=AsyncMock()),
        patch.object(scheduler_climate, "async_on_remove") as on_remove,
    ):
        await scheduler_climate.async_added_to_hass()

    on_remove.assert_called_once_with(scheduler_climate._async_stop_control_heating_loop)
