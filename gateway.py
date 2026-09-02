#!/usr/bin/env python3
"""BLE Gateway for Govee, ThermoPro, Inkbird, SensorPush, and Ruuvi sensors - publishes sensor data to MQTT."""

import asyncio
import logging
import os
import signal
import ssl
import sys
import threading
import time

import paho.mqtt.client as mqtt
from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from govee_ble import GoveeBluetoothDeviceData
from thermopro_ble import ThermoProBluetoothDeviceData
from inkbird_ble import INKBIRDBluetoothDeviceData
from sensorpush_ble import SensorPushBluetoothDeviceData
from ruuvitag_ble import RuuvitagBluetoothDeviceData
from home_assistant_bluetooth import BluetoothServiceInfoBleak
from sensor_state_data import SensorDeviceClass

import config

VERSION = "1.5.0"

logger = logging.getLogger("ble-gateway")

BRAND_PARSERS = {
    "govee": GoveeBluetoothDeviceData,
    "thermopro": ThermoProBluetoothDeviceData,
    "inkbird": INKBIRDBluetoothDeviceData,
    "sensorpush": SensorPushBluetoothDeviceData,
    "ruuvi": RuuvitagBluetoothDeviceData,
}

CLASS_TO_TYPE = {
    SensorDeviceClass.TEMPERATURE: "temperature",
    SensorDeviceClass.HUMIDITY: "humidity",
    SensorDeviceClass.BATTERY: "battery",
    SensorDeviceClass.PRESSURE: "pressure",
    SensorDeviceClass.VOLTAGE: "voltage",
}

SENSOR_TYPES = tuple(CLASS_TO_TYPE.values())

UNITS = {
    "temperature": "°C",
    "humidity": "%",
    "battery": "%",
    "pressure": " hPa",
    "voltage": "V",
}


def normalize_mac(address: str) -> str:
    return address.lower().replace("-", ":")


class BLEGateway:
    def __init__(self, conf: config.Config):
        self.config = conf
        self.mqtt_client: mqtt.Client | None = None
        self.parsers: dict[str, dict[str, object]] = {b: {} for b in BRAND_PARSERS}
        self.running = False
        self.restart_requested = False
        # Registry of recognized sensors, keyed by normalized MAC. Read by the
        # web UI thread; plain dict/attribute updates are safe under the GIL.
        self.seen: dict[str, dict] = {
            mac: self._registry_entry(brand=entry["brand"])
            for mac, entry in conf.devices.items()
        }

    @staticmethod
    def _registry_entry(brand: str = "") -> dict:
        return {"ble_name": "", "brand": brand, "rssi": None, "last_seen": None, "readings": {}}

    def setup_mqtt(self) -> mqtt.Client:
        """Set up and connect MQTT client."""
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.username_pw_set(self.config.mqtt_username, self.config.mqtt_password)

        if self.config.mqtt_use_tls:
            ssl_context = ssl.create_default_context()
            client.tls_set_context(ssl_context)

        client.on_connect = self._on_mqtt_connect
        client.on_disconnect = self._on_mqtt_disconnect

        logger.info(f"Connecting to MQTT broker {self.config.mqtt_broker}:{self.config.mqtt_port}")
        client.connect(self.config.mqtt_broker, self.config.mqtt_port)
        client.loop_start()

        return client

    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            logger.info("Connected to MQTT broker")
        else:
            logger.error(f"MQTT connection failed: {reason_code}")

    def _on_mqtt_disconnect(self, client, userdata, flags, reason_code, properties):
        logger.warning(f"Disconnected from MQTT broker: {reason_code}")

    def publish_sensor_data(self, mac: str, brand: str, sensor_type: str, value):
        """Publish sensor data to MQTT."""
        topic = f"{self.config.mqtt_topic_prefix}/{brand}/{mac}/{sensor_type}"
        payload = str(value)

        result = self.mqtt_client.publish(topic, payload, retain=True)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.debug(f"Published {topic}: {payload}")
        else:
            logger.error(f"Failed to publish to {topic}: {result.rc}")

    def process_sensor_update(self, device: BLEDevice, update, brand: str) -> bool:
        """Record a parsed sensor update and publish it if the device is allowed to."""
        if not update.entity_values:
            return False

        mac = normalize_mac(device.address)
        readings = {}
        for device_key, sensor_value in update.entity_values.items():
            description = update.entity_descriptions.get(device_key)
            if not description:
                continue
            sensor_type = CLASS_TO_TYPE.get(description.device_class)
            if not sensor_type:
                continue
            value = sensor_value.native_value
            if sensor_type == "voltage" and value > 100:
                value = value / 1000  # Ruuvi reports millivolts
            readings[sensor_type] = int(value) if sensor_type == "battery" else round(value, 1)

        entry = self.seen.setdefault(mac, self._registry_entry())
        entry["ble_name"] = device.name or entry["ble_name"]
        entry["brand"] = brand
        entry["last_seen"] = time.time()
        entry["readings"].update(readings)

        publish = self.config.device_may_publish(mac)
        logger.info(
            f"Device: {device.address} ({device.name or 'Unknown'}) [{brand}]"
            + ("" if publish else " (publishing disabled)")
        )
        for sensor_type, value in readings.items():
            logger.info(f"  {sensor_type.capitalize()}: {value}{UNITS[sensor_type]}")
            if publish:
                self.publish_sensor_data(mac, brand, sensor_type, value)

        return True

    def detection_callback(self, device: BLEDevice, advertisement_data: AdvertisementData):
        """Handle BLE advertisement detection."""
        mac = normalize_mac(device.address)

        # Explicitly disabled devices skip parsing entirely; just track presence.
        device_conf = self.config.devices.get(mac)
        if device_conf is not None and not device_conf["enabled"]:
            entry = self.seen.setdefault(mac, self._registry_entry(brand=device_conf["brand"]))
            entry["ble_name"] = device.name or entry["ble_name"]
            entry["rssi"] = advertisement_data.rssi
            entry["last_seen"] = time.time()
            return

        # Wrap bleak data into Home Assistant Bluetooth format
        # Convert objc types to regular Python types for macOS compatibility
        service_info = BluetoothServiceInfoBleak(
            name=str(device.name) if device.name else str(device.address),
            address=str(device.address),
            rssi=int(advertisement_data.rssi) if advertisement_data.rssi else -127,
            manufacturer_data=dict(advertisement_data.manufacturer_data),
            service_data={str(k): v for k, v in advertisement_data.service_data.items()},
            service_uuids=[str(u) for u in advertisement_data.service_uuids],
            source="local",
            device=device,
            advertisement=advertisement_data,
            connectable=False,
            time=time.monotonic(),
            tx_power=int(advertisement_data.tx_power) if advertisement_data.tx_power else None,
        )

        for brand, parser_cls in BRAND_PARSERS.items():
            parser = self.parsers[brand].setdefault(device.address, parser_cls())
            if self.process_sensor_update(device, parser.update(service_info), brand):
                # Track the advertisement RSSI (device.rssi is deprecated in bleak)
                self.seen[mac]["rssi"] = advertisement_data.rssi
                return

    # --- called from the web UI thread -------------------------------------

    def state(self) -> dict:
        """Snapshot of settings and devices for the web UI."""
        settings = {name: getattr(self.config, name) for name in config.SETTINGS}
        del settings["mqtt_password"]  # never sent to the browser

        devices = []
        for mac in sorted(set(self.seen) | set(self.config.devices)):
            entry = self.seen.get(mac) or self._registry_entry()
            device_conf = self.config.devices.get(mac)
            devices.append({
                "mac": mac,
                "name": device_conf["name"] if device_conf else "",
                "ble_name": entry["ble_name"],
                "brand": (device_conf and device_conf["brand"]) or entry["brand"],
                "rssi": entry["rssi"],
                "last_seen": entry["last_seen"],
                "readings": dict(entry["readings"]),
                "enabled": device_conf["enabled"] if device_conf else True,
                "publishing": self.config.device_may_publish(mac),
                "is_new": device_conf is None,
            })

        return {
            "version": VERSION,
            "mqtt_connected": bool(self.mqtt_client and self.mqtt_client.is_connected()),
            "settings": settings,
            "devices": devices,
        }

    def set_device(self, mac: str, enabled=None, name=None) -> dict:
        """Enable/disable or rename a device; applies live, no restart."""
        brand = self.seen.get(mac, {}).get("brand", "")
        entry = self.config.set_device(mac, enabled=enabled, name=name, brand=brand)
        if enabled is False:
            self.clear_retained(mac)
        return entry

    def clear_retained(self, mac: str):
        """Clear a device's retained MQTT topics so stale values don't linger."""
        brand = (self.seen.get(mac) or {}).get("brand") or self.config.devices.get(mac, {}).get("brand")
        if not brand or not self.mqtt_client:
            return
        for sensor_type in SENSOR_TYPES:
            topic = f"{self.config.mqtt_topic_prefix}/{brand}/{mac}/{sensor_type}"
            self.mqtt_client.publish(topic, "", retain=True)
        logger.info(f"Cleared retained topics for {mac}")

    def apply_settings(self, changes: dict) -> bool:
        """Save settings; returns True if a restart was scheduled to apply them."""
        changed = self.config.update_settings(changes)
        if "log_level" in changed:
            logging.getLogger().setLevel(self.config.log_level)
            logger.info(f"Log level set to {self.config.log_level}")
        if changed & config.RESTART_SETTINGS:
            # Let the HTTP response go out before restarting.
            threading.Timer(1.0, self.request_restart).start()
            return True
        return False

    def request_restart(self):
        logger.info("Restart requested to apply new configuration")
        self.restart_requested = True
        self.running = False

    # ------------------------------------------------------------------------

    async def run(self):
        """Run the BLE scanner."""
        self.mqtt_client = self.setup_mqtt()
        self.running = True

        logger.info("Starting BLE scanner for Govee, ThermoPro, Inkbird, SensorPush, and Ruuvi devices...")

        async with BleakScanner(detection_callback=self.detection_callback):
            while self.running:
                await asyncio.sleep(1)

        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()
        logger.info("Gateway stopped")

    def stop(self):
        """Stop the gateway."""
        self.running = False


def main():
    conf = config.Config()
    logging.basicConfig(
        level=getattr(logging, conf.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    gateway = BLEGateway(conf)

    if config.WEB_ENABLED:
        from webui import start_webui
        start_webui(gateway)

    def signal_handler(sig, frame):
        logger.info("Shutdown signal received")
        gateway.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        asyncio.run(gateway.run())
    except KeyboardInterrupt:
        pass

    if gateway.restart_requested:
        logger.info("Restarting gateway...")
        os.execv(sys.executable, [sys.executable] + sys.argv)

    return 0


if __name__ == "__main__":
    sys.exit(main())
