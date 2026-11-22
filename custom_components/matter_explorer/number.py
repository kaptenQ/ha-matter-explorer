"""Number entities for writable integers with limits (setpoints are shown in °C)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ExplorerEntity, async_setup_platform


class ExplorerNumber(ExplorerEntity, NumberEntity):
    """A writable number with the node's limits."""

    _attr_mode = NumberMode.BOX

    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        spec = self._spec
        if spec.min is not None:
            self._attr_native_min_value = spec.min
        if spec.max is not None:
            self._attr_native_max_value = spec.max
        self._attr_native_step = spec.step
        self._attr_native_unit_of_measurement = spec.unit
        if spec.device_class:
            self._attr_device_class = NumberDeviceClass(spec.device_class)

    @property
    def native_value(self) -> float | None:
        return self.native

    async def async_set_native_value(self, value: float) -> None:
        await self._write(round(value * self._spec.scale))


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    await async_setup_platform(hass, entry, Platform.NUMBER, async_add_entities, ExplorerNumber)
