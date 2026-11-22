"""Sensor entities for read-only attributes."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ExplorerEntity, async_setup_platform, display_state


class ExplorerSensor(ExplorerEntity, SensorEntity):
    """A read-only attribute."""

    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        spec = self._spec
        self._attr_native_unit_of_measurement = spec.unit
        if spec.device_class:
            self._attr_device_class = SensorDeviceClass(spec.device_class)
        if spec.device_class == "temperature":
            self._attr_state_class = SensorStateClass.MEASUREMENT
        if spec.device_class == "enum" and spec.options:
            self._attr_options = list(spec.options.values())

    @property
    def native_value(self) -> Any:
        if self._spec.options is not None:
            return self._spec.options.get(self._raw)
        return display_state(self.native)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    await async_setup_platform(hass, entry, Platform.SENSOR, async_add_entities, ExplorerSensor)
