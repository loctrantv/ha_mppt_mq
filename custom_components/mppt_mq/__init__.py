import asyncio
import json
import ssl
import time
import threading
from dataclasses import asdict

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD
from homeassistant.helpers import aiohttp_client

from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DOMAIN, DEVICE_TYPE, DEFAULT_DEVICE_ID, DEFAULT_DEVICE_NAME, DEFAULT_RESET_TIMEOUT, DEFAULT_PATH, DEFAULT_PORT

import logging
_LOGGER = logging.getLogger(__name__)

# Dispatcher signals
SIGNAL_NEW_SENSORS = "mppt_mq_new_sensors"
SIGNAL_SENSOR_UPDATE = "mppt_mq_sensor_update"


class MQTTHandler:
    def __init__(self, hass: HomeAssistant, entry: config_entries.ConfigEntry):
        self.hass = hass
        self.entry = entry
        self._client = None
        self._thread = None
        self._watchdog_task = None
        self._last_update = time.time()
        self._stop_event = threading.Event()

        data = entry.data
        self.host = data.get(CONF_HOST, 'mqttx.smartsolar.io.vn')
        # ensure port is int
        self.port = int(data.get(CONF_PORT, DEFAULT_PORT))
        # websocket path
        self.path = DEFAULT_PATH
        self.device_id = data.get("device_id", DEFAULT_DEVICE_ID)
        self.client_id = data.get("client_id")
        device_type = data.get("type", DEVICE_TYPE)
        deviceMap = {
            "40a": "45a",
            "45a": "45a", 
            "60a": "60a",
        }
        self.topic = f'manhquan/device/mppt_charger/log/{deviceMap[device_type]}/{self.device_id}'
        self.device_name = data.get("device_name", DEFAULT_DEVICE_NAME)
        self.reset_timeout = data.get("reset_timeout", DEFAULT_RESET_TIMEOUT)

        # prepare storage for sensor values and discovered sensor names
        store = hass.data.setdefault(DOMAIN, {})
        store_entry = store.setdefault(entry.entry_id, {})
        store_entry.setdefault("latest", {})
        store_entry.setdefault("sensors", set())
    def start(self):
        import paho.mqtt.client as mqtt
        self._client = mqtt.Client(
            client_id=self.client_id,
            transport="websockets",
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2
        )
        self._client.ws_set_options(path=self.path)
        self._client.tls_set(cert_reqs=ssl.CERT_NONE)
        self._client.username_pw_set("web_app", "Abc@13579")

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

        try:
            _LOGGER.info("Connecting to cloud MQTT %s:%s path=%s", self.host, self.port, self.path)
            self._client.connect(self.host, self.port, keepalive=30)
            self._client.loop_start()
        except Exception as exc:
            # Paho raises WebsocketConnectionError when handshake fails; log guidance
            _LOGGER.error(
                "Websocket connection failed. Check that the broker supports WebSocket on the given port/path, and whether TLS (wss) is required. "
                "Try switching `use_tls` in integration settings or verify `path` and `port` values.")

        # start watchdog task in HA loop
        self._watchdog_task = asyncio.run_coroutine_threadsafe(self._watchdog_loop(), self.hass.loop)

    def stop(self):
        try:
            if self._client:
                self._client.loop_stop()
                self._client.disconnect()
        except Exception:
            pass
        if self._watchdog_task:
            try:
                self._watchdog_task.cancel()
            except Exception:
                pass
    
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        _LOGGER.info("MPPT cloud MQTT connected: %s", rc)
        try:
            client.subscribe(self.topic)
            _LOGGER.info("Subscribed to %s", self.topic)
        except Exception:
            _LOGGER.exception("Subscribe failed")

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        _LOGGER.warning("MPPT cloud MQTT disconnected: %s", rc)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except Exception:
            _LOGGER.exception("Failed parsing MQTT payload")
            return

        # schedule processing on hass loop
        asyncio.run_coroutine_threadsafe(self._process_payload(payload), self.hass.loop)

    async def _process_payload(self, payload):
        try:
            if "dataStreams" not in payload:
                return

            self._last_update = time.time()

            store = self.hass.data.setdefault(DOMAIN, {}).setdefault(self.entry.entry_id, {})
            latest = store.setdefault("latest", {})
            sensors = store.setdefault("sensors", set())

            new_sensors = []
            is_data = False
            for sensor in payload["dataStreams"]:
                name = sensor.get("name")
                value = sensor.get("value")
                if name is None or value is None:
                    continue

                latest[name] = {
                    "value": value,
                    "raw": sensor,
                }
                is_data = True
                # notify sensor platform about update (schedule on event loop)
                self.hass.loop.call_soon_threadsafe(async_dispatcher_send, self.hass, SIGNAL_SENSOR_UPDATE, self.entry.entry_id, name, latest[name])

                if name not in sensors:
                    sensors.add(name)
                    new_sensors.append(name)

            if new_sensors:
                self.hass.loop.call_soon_threadsafe(
                    async_dispatcher_send, self.hass, SIGNAL_NEW_SENSORS, self.entry.entry_id, new_sensors
                )

            if is_data:
                # availability
                latest["__availability__"] = "online"
                self.hass.loop.call_soon_threadsafe(
                    async_dispatcher_send, self.hass, SIGNAL_SENSOR_UPDATE, self.entry.entry_id, "__availability__", {"value": "online"}
                )

        except Exception:
            _LOGGER.exception("Error processing payload")

    async def _watchdog_loop(self):
        # runs inside hass loop
        try:
            while True:
                now = time.time()
                if (now - self._last_update) > self.reset_timeout:
                    store = self.hass.data.setdefault(DOMAIN, {}).setdefault(self.entry.entry_id, {})
                    latest = store.setdefault("latest", {})
                    latest["__availability__"] = "offline"
                    sensors = store.get("sensors", set())
                    for name in sensors:
                        if name != "__availability__":
                            async_dispatcher_send(self.hass, SIGNAL_SENSOR_UPDATE, self.entry.entry_id, name, {"availability": False})
                    async_dispatcher_send(self.hass, SIGNAL_SENSOR_UPDATE, self.entry.entry_id, "__availability__", {"value": "offline"})
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            return


async def async_setup(hass: HomeAssistant, config: dict):
    # Support YAML configuration import into a config entry
    conf = config.get(DOMAIN)
    if conf:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": "import"}, data=conf
            )
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: config_entries.ConfigEntry):
    handler = MQTTHandler(hass, entry)
    # ensure we keep the store dict for this entry and attach handler
    store = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    store["handler"] = handler

    # forward to sensor platform so entities are created
    # pass a list of platforms to async_forward_entry_setups
    hass.async_create_task(hass.config_entries.async_forward_entry_setups(entry, ["sensor"]))

    # start client in executor to avoid blocking
    await hass.async_add_executor_job(handler.start)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: config_entries.ConfigEntry):
    handler: MQTTHandler = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if handler:
        await hass.async_add_executor_job(handler.stop)
    return True
