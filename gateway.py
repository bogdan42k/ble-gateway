#!/usr/bin/env python3
"""BLE Gateway for Govee Hygrometers - publishes sensor data to MQTT."""

import asyncio
import logging
import signal
import ssl
import sys
import time

import paho.mqtt.client as mqtt
from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from govee_ble import GoveeBluetoothDeviceData, SensorDeviceClass
from home_assistant_bluetooth import BluetoothServiceInfoBleak

import config

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("govee-gateway")


class GoveeGateway:
    def __init__(self):
        self.mqtt_client: mqtt.Client | None = None
        self.parsers: dict[str, GoveeBluetoothDeviceData] = {}
        self.running = False

    def setup_mqtt(self) -> mqtt.Client:
        """Set up and connect MQTT client."""
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.username_pw_set(config.MQTT_USERNAME, config.MQTT_PASSWORD)

        if config.MQTT_USE_TLS:
            ssl_context = ssl.create_default_context()
            client.tls_set_context(ssl_context)

        client.on_connect = self._on_mqtt_connect
        client.on_disconnect = self._on_mqtt_disconnect

        logger.info(f"Connecting to MQTT broker {config.MQTT_BROKER}:{config.MQTT_PORT}")
        client.connect(config.MQTT_BROKER, config.MQTT_PORT)
        client.loop_start()

        return client

    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            logger.info("Connected to MQTT broker")
        else:
            logger.error(f"MQTT connection failed: {reason_code}")

    def _on_mqtt_disconnect(self, client, userdata, flags, reason_code, properties):
        logger.warning(f"Disconnected from MQTT broker: {reason_code}")

    def get_parser(self, address: str) -> GoveeBluetoothDeviceData:
        """Get or create a parser for a device."""
        if address not in self.parsers:
            self.parsers[address] = GoveeBluetoothDeviceData()
        return self.parsers[address]

    def publish_sensor_data(self, address: str, sensor_type: str, value: float):
        """Publish sensor data to MQTT."""
        mac = address.lower().replace("-", ":")
        topic = f"{config.MQTT_TOPIC_PREFIX}/{mac}/{sensor_type}"
        payload = str(round(value, 1) if sensor_type != "battery" else int(value))

        result = self.mqtt_client.publish(topic, payload, retain=True)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.debug(f"Published {topic}: {payload}")
        else:
            logger.error(f"Failed to publish to {topic}: {result.rc}")

    def detection_callback(self, device: BLEDevice, advertisement_data: AdvertisementData):
        """Handle BLE advertisement detection."""
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

        parser = self.get_parser(device.address)
        update = parser.update(service_info)

        if not update.entity_values:
            return

        logger.info(f"Device: {device.address} ({device.name or 'Unknown'})")

        for device_key, sensor_value in update.entity_values.items():
            # Get device class from entity_descriptions
            description = update.entity_descriptions.get(device_key)
            if not description:
                continue

            device_class = description.device_class

            if device_class == SensorDeviceClass.TEMPERATURE:
                self.publish_sensor_data(device.address, "temperature", sensor_value.native_value)
                logger.info(f"  Temperature: {sensor_value.native_value}°C")

            elif device_class == SensorDeviceClass.HUMIDITY:
                self.publish_sensor_data(device.address, "humidity", sensor_value.native_value)
                logger.info(f"  Humidity: {sensor_value.native_value}%")

            elif device_class == SensorDeviceClass.BATTERY:
                self.publish_sensor_data(device.address, "battery", sensor_value.native_value)
                logger.info(f"  Battery: {sensor_value.native_value}%")

    async def run(self):
        """Run the BLE scanner."""
        self.mqtt_client = self.setup_mqtt()
        self.running = True

        logger.info("Starting BLE scanner for Govee devices...")

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
    gateway = GoveeGateway()

    def signal_handler(sig, frame):
        logger.info("Shutdown signal received")
        gateway.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        asyncio.run(gateway.run())
    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
