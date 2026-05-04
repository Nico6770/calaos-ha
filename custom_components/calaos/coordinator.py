import logging
from http.client import RemoteDisconnected
from urllib.error import URLError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DEVICE_ID, CONF_TYPE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry
from homeassistant.helpers.event import async_track_time_interval

from pycalaos import Client
from pycalaos.item.common import Item

from .const import DOMAIN, EVENT_DOMAIN, POLL_INTERVAL
from .entity import CalaosEntity
from .no_entity import (
    translate_trigger as noentity_translate_trigger,
    triggers as noentity_triggers,
)

_LOGGER = logging.getLogger(__name__)


class CalaosCoordinator:
    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self.hass = hass
        self.client = None
        self.entry_id = config_entry.entry_id
        self.calaos_url = config_entry.data["url"]
        self.calaos_username = config_entry.data["username"]
        self.calaos_password = config_entry.data["password"]
        self._entity_by_id = {}
        self._device_id_by_id = {}
        self.stopper = None
        self.client = None

    async def connect(self) -> None:
        _LOGGER.debug("Connecting to %s", self.calaos_url)
        self.client = await self.hass.async_add_executor_job(
            Client, self.calaos_url, self.calaos_username, self.calaos_password
        )

    @callback
    def stop_poller(self, *args) -> None:
        _LOGGER.debug("Disconnecting and stopping the poller for %s", self.calaos_url)
        if self.stopper:
            self.stopper()
        self.stopper = None
        self.client = None

    async def declare_noentity_devices(self) -> None:
        dev_registry = device_registry.async_get(self.hass)
        dev_registry.async_get_or_create(
            config_entry_id=self.entry_id,
            identifiers={(DOMAIN, self.entry_id)},
            name="Calaos server",
            manufacturer="Calaos",
            model="Calaos v3",
        )

        for item_type in noentity_triggers.keys():
            for item in self.client.items_by_type(item_type):
                await self.declare_device(dev_registry, self.entry_id, item)

    async def declare_device(
        self, registry: device_registry.DeviceRegistry, entry_id: str, item: Item
    ) -> None:
        _LOGGER.debug("Declaring device without entity for %s", item.name)
        device = registry.async_get_or_create(
            config_entry_id=entry_id,
            identifiers={(DOMAIN, entry_id, item.id)},
            name=item.name,
            manufacturer="Calaos",
            model="Calaos v3",
            suggested_area=item.room.name,
            via_device=(DOMAIN, entry_id),
        )

        self._device_id_by_id[item.id] = device.id

    @callback
    def register(self, item_id: str, entity: CalaosEntity) -> None:
        self._entity_by_id[item_id] = entity

    def item(self, id: str) -> Item:
        return self.client.items[id]

    def items_by_gui_type(self, gui_type: str) -> list[Item]:
        return self.client.items_by_gui_type(gui_type)

    async def poll(self, *args) -> None:
        if not self.client:
            try:
                await self.connect()
            except (RemoteDisconnected, URLError) as ex:
                _LOGGER.error("connection error before polling: %s", ex)
                self.client = None
                return
            except Exception as ex:
                _LOGGER.error("unknown error before polling: %s", ex)
                self.client = None
                return

        try:
            events = await self.hass.async_add_executor_job(self.client.poll)
        except (RemoteDisconnected, URLError) as ex:
            _LOGGER.error("connection error while polling: %s", ex)
            self.client = None
            return
        except Exception as ex:
            _LOGGER.error("unknown error while polling: %s", ex)
            self.client = None
            return

        if len(events) > 0:
            _LOGGER.debug("Calaos events: %s", events)

        for evt in events:
            if evt.item.id in self._entity_by_id:
                _LOGGER.debug("Event for known entity: %s", evt)
                entity = self._entity_by_id[evt.item.id]
                entity.async_schedule_update_ha_state()
                continue

            event_type = noentity_translate_trigger(evt)
            if not event_type:
                _LOGGER.debug(
                    "Ignoring no-entity event with unsupported state: item=%s type=%s state=%r",
                    getattr(evt.item, "id", None),
                    type(evt.item).__name__,
                    getattr(evt, "state", None),
                )
                continue

            device_id = self._device_id_by_id.get(evt.item.id)
            if not device_id:
                _LOGGER.warning(
                    "No Home Assistant device registered for Calaos item %s (%s)",
                    evt.item.id,
                    getattr(evt.item, "name", "unknown"),
                )
                continue

            _LOGGER.debug(
                "Firing Home Assistant event for no-entity device: item=%s trigger=%s device_id=%s",
                evt.item.id,
                event_type,
                device_id,
            )
            self.hass.bus.async_fire(
                EVENT_DOMAIN,
                {
                    CONF_DEVICE_ID: device_id,
                    CONF_TYPE: event_type,
                },
            )

    async def start_poller(self) -> None:
        _LOGGER.debug("Starting the poller for %s", self.calaos_url)
        self.stopper = async_track_time_interval(self.hass, self.poll, POLL_INTERVAL)
