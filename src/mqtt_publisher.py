import json
import logging
import threading
from typing import Optional

import paho.mqtt.client as mqtt

from .config import Config
from .dlms_parser import OBIS_REGISTRY, ObisEntry, ParsedValue

log = logging.getLogger(__name__)


class MqttPublisher:
    def __init__(self, config: Config) -> None:
        self._cfg = config
        self._client: Optional[mqtt.Client] = None
        self._connected = threading.Event()
        self._serial: str = ""
        self._discovery_published: bool = False

    def connect(self) -> None:
        cfg = self._cfg
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"electricity-meter-{cfg.meter_device_id}",
        )
        if cfg.mqtt_username:
            client.username_pw_set(cfg.mqtt_username, cfg.mqtt_password)

        client.will_set(
            topic=cfg.availability_topic,
            payload="offline",
            qos=1,
            retain=True,
        )
        client.reconnect_delay_set(min_delay=5, max_delay=300)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect

        log.info("Connecting to MQTT at %s:%d...", cfg.mqtt_host, cfg.mqtt_port)
        client.connect_async(cfg.mqtt_host, cfg.mqtt_port, keepalive=60)
        client.loop_start()
        self._client = client

        if not self._connected.wait(timeout=30):
            log.warning("MQTT connect timeout — will retry automatically in background")

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code == 0:
            log.info("MQTT connected")
            self._connected.set()
            self._publish(self._cfg.availability_topic, "online", qos=1, retain=True)
            # Re-publish discovery after reconnect (HA may have restarted)
            self._discovery_published = False
            if self._serial:
                self._do_publish_discovery()
        else:
            log.error("MQTT connect failed: reason_code=%s", reason_code)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:
        log.warning("MQTT disconnected: reason_code=%s", reason_code)
        self._connected.clear()

    def publish_discovery(self, serial: str) -> None:
        """Publish HA auto-discovery configs. Idempotent; re-publishes after MQTT reconnect."""
        if serial:
            self._serial = serial
        if not self._discovery_published:
            self._do_publish_discovery()

    def _do_publish_discovery(self) -> None:
        cfg = self._cfg
        device_block = {
            "identifiers": [f"{cfg.meter_device_id}_{self._serial}" if self._serial else cfg.meter_device_id],
            "name": "ST402D Electricity Meter",
            "manufacturer": "Meter & Control",
            "model": "ST402D",
        }

        count = 0
        for entry in OBIS_REGISTRY.values():
            payload = self._build_discovery_payload(entry, device_block)
            topic = (
                f"{cfg.mqtt_discovery_prefix}/{entry.ha_domain}"
                f"/{cfg.meter_device_id}/{entry.key}/config"
            )
            self._publish(topic, json.dumps(payload), qos=1, retain=True)
            count += 1

        log.info("Published %d HA discovery configs (device_id=%s)", count, cfg.meter_device_id)
        self._discovery_published = True

    def _build_discovery_payload(self, entry: ObisEntry, device_block: dict) -> dict:
        cfg = self._cfg
        payload: dict = {
            "name": entry.name,
            "unique_id": f"{cfg.meter_device_id}_{entry.key}",
            "state_topic": cfg.state_topic,
            "value_template": f"{{{{ value_json.{entry.key} }}}}",
            "availability_topic": cfg.availability_topic,
            "device": device_block,
        }

        if entry.ha_domain == "binary_sensor":
            payload["payload_on"] = "connected"
            payload["payload_off"] = "disconnected"
        else:
            if entry.unit:
                payload["unit_of_measurement"] = entry.unit
            if entry.ha_device_class:
                payload["device_class"] = entry.ha_device_class
            if entry.ha_state_class:
                payload["state_class"] = entry.ha_state_class
            if entry.ha_entity_category:
                payload["entity_category"] = entry.ha_entity_category

        return payload

    def publish_state(self, values: dict) -> None:
        state = {
            key: (pv.raw_value if pv.raw_value is not None else "")
            for key, pv in values.items()
        }
        payload = json.dumps(state)
        self._publish(self._cfg.state_topic, payload, qos=0, retain=False)
        log.debug("Published state (%d keys)", len(state))

    def set_offline(self) -> None:
        self._publish(self._cfg.availability_topic, "offline", qos=1, retain=True)

    def disconnect(self) -> None:
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()

    def _publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False) -> None:
        if self._client is None:
            log.warning("MQTT not initialised, dropping publish to %s", topic)
            return
        result = self._client.publish(topic, payload, qos=qos, retain=retain)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            log.warning("MQTT publish to %s failed: rc=%d", topic, result.rc)
