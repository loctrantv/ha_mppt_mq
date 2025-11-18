from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.typing import StateType

from .const import DOMAIN
from .__init__ import SIGNAL_NEW_SENSORS, SIGNAL_SENSOR_UPDATE

_ENTITIES: dict[str, dict[str, SensorEntity]] = {}


class MPPTSensor(SensorEntity):
    def __init__(self, entry_id: str, device_id: str, name: str, device_info: dict):
        self._entry_id = entry_id
        self._device_id = device_id
        self._name = name
        self._attr_name = f"{device_info.get('name')} {name.replace('_',' ').title()}"
        self._unique_id = f"{device_id}_{name}"
        self._state: StateType | None = None
        self._unit = self.get_unit(name)
        self._device_class = self.get_device_class(name)
        self._state_class = self.get_state_class(name)
        self._device_info = device_info
        self._unsub = None

    @property
    def unique_id(self) -> str | None:
        return self._unique_id

    @property
    def name(self) -> str | None:
        return self._attr_name

    @property
    def native_value(self) -> StateType | None:
        return self._state

    @property
    def native_unit_of_measurement(self) -> str | None:
        return self._unit

    @property
    def device_info(self) -> dict:
        return self._device_info
    @property
    def state_class(self) -> str | None:
        return self._state_class
    @property
    def device_class(self) -> str | None:
        return self._device_class

    async def async_added_to_hass(self) -> None:
        # subscribe to updates for this entry
        self._unsub = async_dispatcher_connect(
            self.hass, SIGNAL_SENSOR_UPDATE, self._async_handle_update
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()
    
    def get_unit(self, name):
        return {
            "pv_voltage": "V",
            "bat_voltage": "V",
            "pv_current": "A",
            "bat_current": "A",
            "charge_power": "W",
            "today_kwh": "kWh",
            "total_kwh": "kWh",
            "temperature": "°C",
        }.get(name, None)

    def get_device_class(self, name):
        return {
            "pv_voltage": "voltage",
            "bat_voltage": "voltage",
            "pv_current": "current",
            "bat_current": "current",
            "charge_power": "power",
            "today_kwh": "energy",
            "total_kwh": "energy",
            "temperature": "temperature",
        }.get(name, None)

    def get_state_class(self, name):
        return {
            "today_kwh": "total_increasing",
            "total_kwh": "total_increasing",
            "pv_voltage": "measurement",
            "bat_voltage": "measurement",
            "pv_current": "measurement",
            "bat_current": "measurement",
            "charge_power": "measurement"
        }.get(name, None)
    
    def _async_handle_update(self, entry_id: str, name: str, payload: Any):
        if entry_id != self._entry_id:
            return
        if name == self._name:
            # payload is dict with value/unit/etc
            if isinstance(payload, dict):
                self._state = payload.get("value")
            else:
                self._state = payload
            # schedule state write on HA event loop via async_add_job
            self.hass.async_add_job(self.async_write_ha_state)
        if name == "__availability__" and self._name == "availability":
            if isinstance(payload, dict):
                self._state = payload.get("value")
            else:
                self._state = payload
            # schedule state write on HA event loop via async_add_job
            self.hass.async_add_job(self.async_write_ha_state)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    store = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    device_id = entry.data.get("device_id") or "unknown"
    device_name = entry.data.get("device_name") or "MPPT SmartSolar "

    device_info = {
        "identifiers": {(DOMAIN, device_id)},
        "name": device_name,
        "manufacturer": "SmartSolar",
        "model": "MPPT Charger",
    }

    # availability sensor
    avail = MPPTSensor(entry.entry_id, device_id, "availability", {**device_info, "name": device_name})
    _ENTITIES.setdefault(entry.entry_id, {})["availability"] = avail
    async_add_entities([avail])

    # create existing sensors
    sensors = store.get("sensors", set())
    new = []
    for name in sensors:
        if name == "__availability__":
            continue
        if name in _ENTITIES.setdefault(entry.entry_id, {}):
            continue
        ent = MPPTSensor(entry.entry_id, device_id, name, {**device_info, "name": device_name})
        _ENTITIES[entry.entry_id][name] = ent
        new.append(ent)
    if new:
        async_add_entities(new)

    # subscribe to new sensors created after setup
    async def _new_sensors_cb(entry_id: str, names: list[str]):
        if entry_id != entry.entry_id:
            return
        add = []
        for name in names:
            if name in _ENTITIES.setdefault(entry.entry_id, {}):
                continue
            ent = MPPTSensor(entry.entry_id, device_id, name, {**device_info, "name": device_name})
            _ENTITIES[entry.entry_id][name] = ent
            add.append(ent)
        if add:
            # async_add_entities is not async, call it directly (it schedules internally)
            async_add_entities(add)

    async_dispatcher_connect(hass, SIGNAL_NEW_SENSORS, _new_sensors_cb)
