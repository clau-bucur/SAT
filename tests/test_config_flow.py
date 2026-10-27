import asyncio
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.core import HomeAssistant

from custom_components.sat.const import CONF_HEATING_SYSTEM, CONF_NAME, HEATING_SYSTEM_RADIATORS, MODE_FAKE
from custom_components.sat.config_flow import SatFlowHandler


async def test_create_coordinator(hass):
    flow_handler = SatFlowHandler()
    flow_handler.data = {
        "name": "Test",
        "mode": MODE_FAKE,
        "device": "test_device",
    }

    await flow_handler.async_create_coordinator()


async def test_calibration_subscribes_before_measuring(hass: HomeAssistant) -> None:
    """Calibration must start coordinator updates before waiting for temperatures."""
    flow = SatFlowHandler()
    flow.hass = hass
    flow.data = {CONF_NAME: "Calibration test", CONF_HEATING_SYSTEM: HEATING_SYSTEM_RADIATORS}
    events = []
    subscribed = False

    async def subscribe() -> None:
        nonlocal subscribed
        await asyncio.sleep(0)
        subscribed = True
        events.append("subscribe")

    async def calculate() -> float:
        assert subscribed, "Temperature updates must be active before calibration"
        events.append("calculate")
        return 26.4

    coordinator = Mock()
    coordinator.async_setup = AsyncMock(side_effect=lambda: events.append("setup"))
    coordinator.async_added_to_hass = AsyncMock(side_effect=subscribe)
    coordinator.async_will_remove_from_hass = AsyncMock(side_effect=lambda: events.append("remove"))
    protection = Mock()
    protection.calculate = AsyncMock(side_effect=calculate)

    with (
        patch.object(flow, "async_create_coordinator", new=AsyncMock(return_value=coordinator)),
        patch.object(flow, "async_show_progress", return_value={"type": "show_progress"}),
        patch("custom_components.sat.config_flow.OvershootProtection", return_value=protection) as overshoot,
    ):
        await flow.async_step_calibrate()
        await flow.calibration
        await hass.async_block_till_done()

    assert events == ["setup", "subscribe", "calculate", "remove"]
    overshoot.assert_called_once_with(coordinator, HEATING_SYSTEM_RADIATORS)
    coordinator.async_added_to_hass.assert_awaited_once()
    protection.calculate.assert_awaited_once()
    assert flow.overshoot_protection_value == 26.4
