#!/usr/bin/env python3
"""BLE Gateway for Govee and ThermoPro sensors - publishes sensor data to MQTT."""

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
from govee_ble import GoveeBluetoothDeviceData
from thermopro_ble import ThermoProBluetoothDeviceData
from home_assistant_bluetooth import BluetoothServiceInfoBleak
from sensor_state_data import SensorDeviceClass

import config

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("ble-gateway")


class BLEGateway:
    def __init__(self):
        self.mqtt_client: mqtt.Client | None = None
        self.govee_parsers: dict[str, GoveeBluetoothDeviceData] = {}
        self.thermopro_parsers: dict[str, ThermoProBluetoothDeviceData] = {}
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

    def get_govee_parser(self, address: str) -> GoveeBluetoothDeviceData:
        """Get or create a Govee parser for a device."""
        if address not in self.govee_parsers:
            self.govee_parsers[address] = GoveeBluetoothDeviceData()
        return self.govee_parsers[address]

    def get_thermopro_parser(self, address: str) -> ThermoProBluetoothDeviceData:
        """Get or create a ThermoPro parser for a device."""
        if address not in self.thermopro_parsers:
            self.thermopro_parsers[address] = ThermoProBluetoothDeviceData()
        return self.thermopro_parsers[address]

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

    def process_sensor_update(self, device: BLEDevice, update):
        """Process sensor update and publish to MQTT."""
        if not update.entity_values:
            return False

        logger.info(f"Device: {device.address} ({device.name or 'Unknown'})")

        for device_key, sensor_value in update.entity_values.items():
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

        return True

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

        # Try Govee parser
        govee_parser = self.get_govee_parser(device.address)
        govee_update = govee_parser.update(service_info)
        if self.process_sensor_update(device, govee_update):
            return

        # Try ThermoPro parser
        thermopro_parser = self.get_thermopro_parser(device.address)
        thermopro_update = thermopro_parser.update(service_info)
        self.process_sensor_update(device, thermopro_update)

    async def run(self):
        """Run the BLE scanner."""
        self.mqtt_client = self.setup_mqtt()
        self.running = True

        logger.info("Starting BLE scanner for Govee and ThermoPro devices...")

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
    gateway = BLEGateway()

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
