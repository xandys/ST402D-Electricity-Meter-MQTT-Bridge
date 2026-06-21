# ST402D Electricity Meter MQTT Bridge

Bridges a **Meter & Control ST402D** electricity meter to **MQTT** with automatic **Home Assistant** discovery.

The meter pushes DLMS/COSEM frames over RS-485. A [Waveshare RS485-TO-ETH-B](https://www.waveshare.com/rs485-to-eth-b.htm) converter exposes that serial stream as a TCP socket. This bridge connects to that socket, parses each push frame, and publishes the values to MQTT.

```
ST402D meter ─(RS-485)─► Waveshare RS485-ETH ─(TCP)─► this bridge ─(MQTT)─► Home Assistant
```

## Features

- Parses DLMS/COSEM data-notification push frames (no polling)
- Publishes all OBIS values as a single JSON state message per frame
- Auto-discovery for Home Assistant sensors and binary sensors
- Availability topic with LWT so HA shows `unavailable` when the bridge is down
- Exponential backoff reconnect on both TCP and MQTT sides
- Single dependency: [paho-mqtt](https://pypi.org/project/paho-mqtt/)

## Published entities

| Key | Name | Unit |
|-----|------|------|
| `power_import_total` | Active Power Import Total | W |
| `power_import_l1` / `l2` / `l3` | Active Power Import per Phase | W |
| `power_export_total` | Active Power Export Total | W |
| `power_export_l1` / `l2` / `l3` | Active Power Export per Phase | W |
| `energy_import_total` | Cumulative Import Energy Total | Wh |
| `energy_import_rate1`…`rate4` | Cumulative Import Energy by Tariff | Wh |
| `energy_export_total` | Cumulative Export Energy Total | Wh |
| `power_limiter` | Power Limiter | W |
| `disconnect_status` | Disconnect Status | binary |
| `relay_1_status`…`relay_6_status` | Relay Status | binary |
| `serial_number` | Serial Number | diagnostic |
| `active_tariff` | Active Tariff | diagnostic |
| `device_name` | COSEM Device Name | diagnostic |
| `consumer_message` | Consumer Message | diagnostic |

## MQTT topics

| Topic | Description |
|-------|-------------|
| `electricity_meter/{METER_DEVICE_ID}/state` | JSON state payload, published every push (~60 s) |
| `electricity_meter/{METER_DEVICE_ID}/availability` | `online` / `offline` (retained, LWT) |
| `homeassistant/{domain}/{METER_DEVICE_ID}/{key}/config` | HA auto-discovery configs (retained) |

## Deployment

### Prerequisites

- Docker and Docker Compose
- Waveshare RS485-ETH converter configured in **TCP Server** mode (default port `4196`)
- MQTT broker (e.g. Mosquitto)

### Quick start

1. Clone the repo and edit `docker-compose.yml`:

```yaml
environment:
  WAVESHARE_HOST: "192.168.1.100"   # IP of the Waveshare converter
  MQTT_HOST: "192.168.1.10"         # IP of your MQTT broker
```

2. Start:

```bash
docker compose up -d
```

3. Check logs:

```bash
docker compose logs -f
```

### Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `WAVESHARE_HOST` | yes | — | IP or hostname of the Waveshare RS485-ETH converter |
| `WAVESHARE_PORT` | no | `4196` | TCP port on the Waveshare device |
| `MQTT_HOST` | yes | — | MQTT broker hostname or IP |
| `MQTT_PORT` | no | `1883` | MQTT broker port |
| `MQTT_USERNAME` | no | — | MQTT username |
| `MQTT_PASSWORD` | no | — | MQTT password |
| `MQTT_BASE_TOPIC` | no | `electricity_meter` | Root topic prefix |
| `MQTT_DISCOVERY_PREFIX` | no | `homeassistant` | HA discovery prefix |
| `METER_DEVICE_ID` | no | `st402d` | Device ID used in topics and entity unique IDs |
| `LOG_LEVEL` | no | `INFO` | Python log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

## Development

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
WAVESHARE_HOST=... MQTT_HOST=... python -m src.main
```

## Hardware setup

1. Wire the meter's RS-485 A/B terminals to the Waveshare converter's A/B terminals.
2. Configure the Waveshare converter via its web UI:
   - **Work Mode**: TCP Server
   - **Local Port**: `4196` (or change `WAVESHARE_PORT` accordingly)
   - **Baud Rate**: match the meter's configured baud rate (typically 9600)
3. Connect the Waveshare converter to your LAN and note its IP.
