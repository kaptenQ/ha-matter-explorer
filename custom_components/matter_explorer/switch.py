"""Switch entities for writable bool attributes."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ExplorerEntity, async_setup_platform


class ExplorerSwitch(ExplorerEntity, SwitchEntity):
    """A writable bool."""

    @property
    def is_on(self) -> bool | None:
        return None if self._raw is None else bool(self._raw)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._write(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._write(False)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    await async_setup_platform(hass, entry, Platform.SWITCH, async_add_entities, ExplorerSwitch)
