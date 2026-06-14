import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Config:
    waveshare_host: str
    mqtt_host: str
    waveshare_port: int = 4196
    mqtt_port: int = 1883
    mqtt_username: Optional[str] = None
    mqtt_password: Optional[str] = None
    mqtt_base_topic: str = "electricity_meter"
    mqtt_discovery_prefix: str = "homeassistant"
    meter_device_id: str = "st402d"
    log_level: str = "INFO"
    state_topic: str = field(init=False)
    availability_topic: str = field(init=False)

    def __post_init__(self) -> None:
        self.state_topic = f"{self.mqtt_base_topic}/{self.meter_device_id}/state"
        self.availability_topic = f"{self.mqtt_base_topic}/{self.meter_device_id}/availability"


def load_config() -> Config:
    def _require(name: str) -> str:
        val = os.environ.get(name, "").strip()
        if not val:
            raise ValueError(f"Required environment variable {name!r} is not set")
        return val

    def _optional(name: str) -> Optional[str]:
        val = os.environ.get(name, "").strip()
        return val or None

    return Config(
        waveshare_host=_require("WAVESHARE_HOST"),
        waveshare_port=int(os.environ.get("WAVESHARE_PORT", "4196")),
        mqtt_host=_require("MQTT_HOST"),
        mqtt_port=int(os.environ.get("MQTT_PORT", "1883")),
        mqtt_username=_optional("MQTT_USERNAME"),
        mqtt_password=_optional("MQTT_PASSWORD"),
        mqtt_base_topic=os.environ.get("MQTT_BASE_TOPIC", "electricity_meter"),
        mqtt_discovery_prefix=os.environ.get("MQTT_DISCOVERY_PREFIX", "homeassistant"),
        meter_device_id=os.environ.get("METER_DEVICE_ID", "st402d"),
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    )
