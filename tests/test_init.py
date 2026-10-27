"""Test setup process."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.components import esphome
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sat.config_flow import SatFlowHandler
from custom_components.sat.const import (
    CLIMATE,
    CONF_ERROR_MONITORING,
    CONF_HEATING_SYSTEM,
    CONF_MINIMUM_SETPOINT,
    DOMAIN,
    HEATING_SYSTEM_RADIATORS,
)
from custom_components.sat.coordinator import SatDataUpdateCoordinator
from custom_components.sat.esphome import SatEspHomeCoordinator
from tests.const import DEFAULT_USER_DATA


async def test_setup_update_unload_entry(hass):
    """Test entry setup and unload."""
    await hass.async_start()
    sat_entry = MockConfigEntry(
        domain=DOMAIN,
        version=SatFlowHandler.VERSION,
        data={
            **DEFAULT_USER_DATA,
            CONF_HEATING_SYSTEM: HEATING_SYSTEM_RADIATORS,
            CONF_MINIMUM_SETPOINT: 26.4,
        },
        options={CONF_ERROR_MONITORING: False},
    )
    sat_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(sat_entry.entry_id)

    # Wait till there are no tasks and see if we have been configured
    await hass.async_block_till_done()
    assert DOMAIN in hass.data and sat_entry.entry_id in hass.data[DOMAIN]

    original_climate = hass.data[DOMAIN][sat_entry.entry_id][CLIMATE]
    assert await hass.config_entries.async_reload(sat_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.data[DOMAIN][sat_entry.entry_id][CLIMATE] is not original_climate

    assert await hass.config_entries.async_unload(sat_entry.entry_id)
    await hass.async_block_till_done()
    assert sat_entry.entry_id not in hass.data[DOMAIN]


def _registry_coordinator(hass: HomeAssistant) -> SatEspHomeCoordinator:
    """Use the real HA registry without opening an ESPHome or MQTT connection."""
    coordinator = object.__new__(SatEspHomeCoordinator)
    coordinator.hass = hass
    coordinator._mac_address = "aa:bb:cc:dd:ee:ff"
    coordinator._entity_registry = entity_registry.async_get(hass)
    coordinator._state_change_unsub = None
    return coordinator


@pytest.mark.parametrize(
    ("domain", "key"),
    [("switch", "ch_enable"), ("number", "t_set"), ("sensor", "t_boiler")],
)
def test_esphome_prefers_modern_entity_id(
    hass: HomeAssistant, domain: str, key: str
) -> None:
    """A stale legacy registry entry must not mask the current ESPHome entity."""
    coordinator = _registry_coordinator(hass)
    registry = coordinator._entity_registry
    legacy = registry.async_get_or_create(
        domain, esphome.DOMAIN, f"AA:BB:CC:DD:EE:FF-{domain}-{key}",
        suggested_object_id="legacy_gateway",
    )
    modern = registry.async_get_or_create(
        domain, esphome.DOMAIN, f"AA:BB:CC:DD:EE:FF/0/{domain}/{key}",
        suggested_object_id="modern_gateway",
    )

    assert legacy.entity_id != modern.entity_id
    assert coordinator._get_entity_id(domain, key) == modern.entity_id


def test_esphome_falls_back_to_legacy_entity_id(hass: HomeAssistant) -> None:
    """Existing installations using the previous ESPHome format remain usable."""
    coordinator = _registry_coordinator(hass)
    legacy = coordinator._entity_registry.async_get_or_create(
        "switch", esphome.DOMAIN, "AA:BB:CC:DD:EE:FF-switch-ch_enable"
    )

    assert coordinator._get_entity_id("switch", "ch_enable") == legacy.entity_id


def test_esphome_unknown_entity_id(hass: HomeAssistant) -> None:
    """Missing entities retain the existing None result."""
    coordinator = _registry_coordinator(hass)
    assert coordinator._get_entity_id("switch", "ch_enable") is None


async def test_esphome_removal_unsubscribes_once(hass: HomeAssistant) -> None:
    """A removed coordinator stops receiving live state updates after a reload."""
    coordinator = _registry_coordinator(hass)
    entity = coordinator._entity_registry.async_get_or_create(
        "switch", esphome.DOMAIN, "AA:BB:CC:DD:EE:FF/0/switch/ch_enable"
    )
    hass.states.async_set(entity.entity_id, "off")
    coordinator.async_notify_listeners = AsyncMock()

    with (
        patch("custom_components.sat.esphome.mqtt.async_wait_for_mqtt_client", new=AsyncMock()),
        patch.object(SatDataUpdateCoordinator, "async_added_to_hass", new=AsyncMock()),
        patch.object(SatDataUpdateCoordinator, "async_will_remove_from_hass", new=AsyncMock()) as parent_remove,
    ):
        await coordinator.async_added_to_hass()
        unsubscribe = Mock(wraps=coordinator._state_change_unsub)
        coordinator._state_change_unsub = unsubscribe

        hass.states.async_set(entity.entity_id, "on")
        await hass.async_block_till_done()
        coordinator.async_notify_listeners.assert_awaited_once()

        await coordinator.async_will_remove_from_hass()
        await coordinator.async_will_remove_from_hass()
        unsubscribe.assert_called_once_with()
        assert coordinator._state_change_unsub is None
        assert parent_remove.await_count == 2

        hass.states.async_set(entity.entity_id, "off")
        await hass.async_block_till_done()
        coordinator.async_notify_listeners.assert_awaited_once()
