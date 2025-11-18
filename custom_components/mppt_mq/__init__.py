import asyncio
import json
import ssl
import time
import threading

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD

from .const import DOMAIN, DEVICE_TYPE, DEFAULT_DEVICE_NAME, DEFAULT_RESET_TIMEOUT

import logging
_LOGGER = logging.getLogger(__name__)


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
        self.host = data.get(CONF_HOST)
        self.port = data.get(CONF_PORT)
        self.path = '/mppt'

        self.username = data.get(CONF_USERNAME, 'web_app')
        self.password = data.get(CONF_PASSWORD,'Abc@13579')
        self.device_id = data.get("device_id", '')
        self.topic = f'manhquan/device/mppt_charger/log/{data.get("type", DEVICE_TYPE)}/{self.device_id}'
        self.device_name = data.get("device_name", DEFAULT_DEVICE_NAME)
        self.reset_timeout = data.get("reset_timeout", DEFAULT_RESET_TIMEOUT)

    def start(self):
        import paho.mqtt.client as mqtt

        self._client = mqtt.Client(client_id=f"mppt_{self.device_id}", transport="websockets")
        self._client.ws_set_options(path=self.path)
        # Do not require certs (same as original script)
        self._client.tls_set(cert_reqs=ssl.CERT_NONE)

        if self.username:
            self._client.username_pw_set(self.username, self.password)

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

        try:
            _LOGGER.info("Connecting to cloud MQTT %s:%s", self.host, self.port)
            self._client.connect(self.host, self.port, keepalive=30)
            self._client.loop_start()
        except Exception as exc:
            _LOGGER.exception("Failed to connect MQTT: %s", exc)

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

    def _on_disconnect(self, client, userdata, rc, properties=None):
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

            for sensor in payload["dataStreams"]:
                name = sensor.get("name")
                value = sensor.get("value")
                if name is None or value is None:
                    continue

                entity_id = f"sensor.{self.device_id}_{name}"
                friendly = f"{self.device_name} {name.replace('_', ' ').title()}"
                attrs = {
                    "friendly_name": friendly,
                    "device_id": self.device_id,
                    "sensor_name": name,
                    "unit_of_measurement": sensor.get("unit", ""),
                }
                # write state directly to hass
                self.hass.states.async_set(entity_id, value, attrs)

            # set availability state
            avail_id = f"sensor.{self.device_id}_availability"
            self.hass.states.async_set(avail_id, "online", {"friendly_name": f"{self.device_name} availability"})

        except Exception:
            _LOGGER.exception("Error processing payload")

    async def _watchdog_loop(self):
        # runs inside hass loop
        try:
            while True:
                now = time.time()
                if (now - self._last_update) > self.reset_timeout:
                    avail_id = f"sensor.{self.device_id}_availability"
                    self.hass.states.async_set(avail_id, "offline", {"friendly_name": f"{self.device_name} availability"})
                await asyncio.sleep(1)
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
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = handler
    # start client in executor to avoid blocking
    await hass.async_add_executor_job(handler.start)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: config_entries.ConfigEntry):
    handler: MQTTHandler = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if handler:
        await hass.async_add_executor_job(handler.stop)
    return True
