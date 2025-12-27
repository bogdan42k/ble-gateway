# Govee BLE Gateway

A Python BLE gateway that listens for Govee hygrometer advertisements and publishes sensor data to an MQTT broker.

## Supported Devices

- Govee H5074
- Govee H5075
- Govee H5100
- Govee H5177
- Govee H5179
- And other Govee thermometer/hygrometer models supported by [govee-ble](https://github.com/Bluetooth-Devices/govee-ble)

## Features

- Passive BLE scanning for Govee device advertisements
- Parses temperature, humidity, and battery level
- Publishes to MQTT with TLS support
- Runs as CLI, systemd service, or Docker container

## Raspberry Pi Setup

This gateway runs well on Raspberry Pi, making it ideal for a dedicated BLE-to-MQTT bridge.

### Prerequisites

- Raspberry Pi 3/4/5/Zero W (with built-in Bluetooth)
- Raspberry Pi OS Bullseye or newer
- Python 3.10+

### Quick Start

```bash
# Install system dependencies
sudo apt update
sudo apt install -y python3-venv python3-pip bluetooth bluez

# Clone the repository
git clone https://github.com/bogdan42k/ble-gateway.git
cd ble-gateway

# Create virtual environment and install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure and run
export MQTT_BROKER=your-broker.example.com
export MQTT_USERNAME=your_username
export MQTT_PASSWORD=your_password
python gateway.py
```

### Run as Service (Auto-start on Boot)

```bash
# Copy files
sudo mkdir -p /opt/govee-gateway
sudo cp gateway.py config.py requirements.txt /opt/govee-gateway/
sudo python3 -m venv /opt/govee-gateway/venv
sudo /opt/govee-gateway/venv/bin/pip install -r /opt/govee-gateway/requirements.txt

# Create environment file with your credentials
sudo tee /opt/govee-gateway/.env << EOF
MQTT_BROKER=your-broker.example.com
MQTT_USERNAME=your_username
MQTT_PASSWORD=your_password
EOF
sudo chmod 600 /opt/govee-gateway/.env

# Install and start service
sudo cp govee-gateway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now govee-gateway

# Check status
sudo systemctl status govee-gateway
sudo journalctl -u govee-gateway -f
```

### Troubleshooting

**Bluetooth permission errors:**
```bash
# Add user to bluetooth group
sudo usermod -aG bluetooth $USER
# Reboot or re-login
```

**No devices found:**
```bash
# Check Bluetooth is enabled
sudo systemctl status bluetooth
sudo hciconfig hci0 up
```

## Installation

### Using pip

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Using Docker

```bash
docker compose up -d
```

## Configuration

Configuration is done via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MQTT_BROKER` | `mqtt.example.com` | MQTT broker hostname |
| `MQTT_PORT` | `8883` | MQTT broker port |
| `MQTT_USERNAME` | - | MQTT username |
| `MQTT_PASSWORD` | - | MQTT password |
| `MQTT_USE_TLS` | `true` | Enable TLS encryption |
| `MQTT_TOPIC_PREFIX` | `govee` | MQTT topic prefix |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

Edit `config.py` to change default values, or set environment variables.

## Usage

### Run directly

```bash
source venv/bin/activate
python gateway.py
```

### Run as systemd service

1. Copy files to `/opt/govee-gateway`:
   ```bash
   sudo mkdir -p /opt/govee-gateway
   sudo cp gateway.py config.py requirements.txt /opt/govee-gateway/
   sudo python3 -m venv /opt/govee-gateway/venv
   sudo /opt/govee-gateway/venv/bin/pip install -r /opt/govee-gateway/requirements.txt
   ```

2. Install and enable service:
   ```bash
   sudo cp govee-gateway.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now govee-gateway
   ```

3. Check status:
   ```bash
   sudo systemctl status govee-gateway
   sudo journalctl -u govee-gateway -f
   ```

### Run with Docker

```bash
docker compose up -d
```

View logs:
```bash
docker compose logs -f
```

## MQTT Topics

Data is published to the following topics:

```
govee/{device_mac}/temperature  - Temperature in Celsius (e.g., "23.5")
govee/{device_mac}/humidity     - Relative humidity percentage (e.g., "49.9")
govee/{device_mac}/battery      - Battery percentage (e.g., "92")
```

MAC addresses are lowercase with colons (e.g., `a4:c1:38:xx:xx:xx`).

Messages are published with the `retain` flag set.

## Example Output

```
2024-12-27 15:28:42 - govee-gateway - INFO - Device: 535C2D47-BF8F-7D78-BF11-C9F2602F4BE4 (Govee_H5074_38A8)
2024-12-27 15:28:42 - govee-gateway - INFO -   Temperature: 23.0°C
2024-12-27 15:28:42 - govee-gateway - INFO -   Humidity: 49.9%
2024-12-27 15:28:42 - govee-gateway - INFO -   Battery: 92%
```

## Dependencies

- [govee-ble](https://github.com/Bluetooth-Devices/govee-ble) - Govee BLE advertisement parser
- [bleak](https://github.com/hbldh/bleak) - Bluetooth Low Energy platform-agnostic client
- [paho-mqtt](https://github.com/eclipse/paho.mqtt.python) - MQTT client library

## License

MIT
