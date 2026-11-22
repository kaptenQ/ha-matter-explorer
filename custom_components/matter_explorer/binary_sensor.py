"""Binary sensor entities for read-only bool attributes."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ExplorerEntity, async_setup_platform


class ExplorerBinarySensor(ExplorerEntity, BinarySensorEntity):
    """A read-only bool."""

    @property
    def is_on(self) -> bool | None:
        return None if self._raw is None else bool(self._raw)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    await async_setup_platform(
        hass, entry, Platform.BINARY_SENSOR, async_add_entities, ExplorerBinarySensor
    )
