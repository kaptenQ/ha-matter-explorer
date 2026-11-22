"""Select entities for writable enum attributes (child lock: Off, Level 1 ... Level 5)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ExplorerEntity, async_setup_platform


class ExplorerSelect(ExplorerEntity, SelectEntity):
    """A writable enum."""

    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        self._attr_options = list((self._spec.options or {}).values())

    @property
    def current_option(self) -> str | None:
        return (self._spec.options or {}).get(self._raw)

    async def async_select_option(self, option: str) -> None:
        raw = next(v for v, label in (self._spec.options or {}).items() if label == option)
        await self._write(raw)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    await async_setup_platform(hass, entry, Platform.SELECT, async_add_entities, ExplorerSelect)
