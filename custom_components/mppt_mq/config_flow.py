import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD

from .const import DOMAIN, DEVICE_TYPE, DEFAULT_DEVICE_ID, DEFAULT_DEVICE_NAME, DEFAULT_RESET_TIMEOUT, DEFAULT_PORT

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default="mqttx.smartsolar.io.vn"): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional("type", default=DEVICE_TYPE): vol.In(["40a", "45a", "60a"]),
        vol.Optional("device_id", default=DEFAULT_DEVICE_ID): str,
        vol.Optional("device_name", default=DEFAULT_DEVICE_NAME): str,
        vol.Optional("reset_timeout", default=DEFAULT_RESET_TIMEOUT): int,
        vol.Optional(CONF_USERNAME, default=""): str,
        vol.Optional(CONF_PASSWORD, default=""): str,
    }
)


class MPPTConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title=user_input.get("device_name", "MPPT"), data=user_input)

        return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA)

    async def async_step_import(self, import_config):
        # Called when configuration is imported from YAML
        return await self.async_step_user(import_config)
