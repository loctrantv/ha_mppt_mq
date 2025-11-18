# MPPT MQ Home Assistant Integration

This custom integration converts the logic from `main.py` into a Home Assistant integration suitable for HACS.

Features:
- Connects to a cloud MQTT websocket server and subscribes to a topic
- Parses incoming JSON payloads containing `dataStreams`
- Writes sensor states directly into Home Assistant (no local MQTT required)
- Provides UI setup via Integrations (config flow) and YAML import support

Installation via HACS (GitHub path):
1. Add this repository to HACS as a custom repository by URL.
2. Install `MPPT MQ (HACS friendly)` from HACS.
3. Restart Home Assistant.
4. Go to Settings -> Devices & Services -> Add Integration -> MPPT MQ and configure your cloud MQTT settings.

YAML example (optional):
```yaml
mppt_mq:
  host: mqttx.smartsolar.io.vn
  port: 8084
  path: /mqtt
  topic: manhquan/device/mppt_charger/log/45a/15315806
  username: web_app
  password: Abc@13579
  device_id: 15315806
  device_name: MPPT
  reset_timeout: 30
```

After setup the integration will create sensors like `sensor.15315806_pv_voltage` and a `sensor.15315806_availability` that will be updated as data arrives.
