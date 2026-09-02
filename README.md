# BLE Gateway

A Python BLE gateway that listens for Govee, ThermoPro, Inkbird, SensorPush, and Ruuvi sensor advertisements and publishes sensor data to an MQTT broker.

## Supported Devices

### Govee
- Govee H5074, H5075, H5100, H5177, H5179
- And other Govee thermometer/hygrometer models supported by [govee-ble](https://github.com/Bluetooth-Devices/govee-ble)

### ThermoPro
- ThermoPro TP351, TP357, TP358, TP359
- And other ThermoPro models supported by [thermopro-ble](https://github.com/Bluetooth-Devices/thermopro-ble)

### Inkbird
- Inkbird IBS-TH1, IBS-TH2, ITH-12S
- And other Inkbird models supported by [inkbird-ble](https://github.com/Bluetooth-Devices/inkbird-ble)

### SensorPush
- SensorPush HT1, HT.w, HTP.xw
- And other SensorPush models supported by [sensorpush-ble](https://github.com/Bluetooth-Devices/sensorpush-ble)

### Ruuvi
- RuuviTag, RuuviTag Pro
- And other Ruuvi models supported by [ruuvitag-ble](https://github.com/Bluetooth-Devices/ruuvitag-ble)

## Features

- Passive BLE scanning for Govee, ThermoPro, Inkbird, SensorPush, and Ruuvi device advertisements
- Parses temperature, humidity, battery level, pressure, and voltage
- Publishes to MQTT with TLS support
- Web UI on the local network for configuration and per-sensor management
- Runs as CLI, systemd service, or Docker container

## Raspberry Pi Setup

This gateway runs well on Raspberry Pi, making it ideal for a dedicated BLE-to-MQTT bridge.

### Easy Install (Recommended)

Run this single command on your Raspberry Pi:

```bash
curl -sSL https://raw.githubusercontent.com/bogdan42k/ble-gateway/main/install.sh | sudo bash
```

The installer will:
- Install all dependencies
- Prompt you for MQTT configuration
- Set up auto-start on boot
- Start the service immediately

To uninstall:
```bash
curl -sSL https://raw.githubusercontent.com/bogdan42k/ble-gateway/main/install.sh | sudo bash -s -- --uninstall
```

### Manual Install

#### Prerequisites

- Raspberry Pi 3/4/5/Zero W (with built-in Bluetooth)
- Raspberry Pi OS Bullseye or newer
- Python 3.10+

#### Quick Start

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
sudo mkdir -p /opt/ble-gateway
sudo cp gateway.py config.py webui.py requirements.txt /opt/ble-gateway/
sudo python3 -m venv /opt/ble-gateway/venv
sudo /opt/ble-gateway/venv/bin/pip install -r /opt/ble-gateway/requirements.txt

# Create environment file with your credentials
sudo tee /opt/ble-gateway/.env << EOF
MQTT_BROKER=your-broker.example.com
MQTT_USERNAME=your_username
MQTT_PASSWORD=your_password
EOF
sudo chmod 600 /opt/ble-gateway/.env

# Install and start service
sudo cp ble-gateway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ble-gateway

# Check status
sudo systemctl status ble-gateway
sudo journalctl -u ble-gateway -f
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

## Web UI

The gateway serves a small configuration page on the local network, by default
at `http://<gateway-ip>:8080`. From it you can:

- Edit MQTT settings (broker, port, credentials, TLS, topic prefix, log level).
  Changing broker settings restarts the gateway automatically (takes a few
  seconds); log level and topic prefix apply live.
- See every recognized sensor: name, brand, MAC, RSSI, last seen, and the
  latest readings.
- Enable/disable publishing per sensor and give sensors friendly names
  (names are for the UI only — MQTT topics stay MAC-based). Disabling a
  sensor also clears its retained MQTT topics.
- Choose what happens to newly discovered sensors: publish automatically
  (default) or ignore until you enable them.

Settings saved in the UI are written to `config.json` next to the app (or the
path in `CONFIG_FILE`). Precedence: `config.json` > environment variables >
built-in defaults, so existing env-var-based deployments keep working.

The web server itself is configured via environment variables only (so a bad
save can't lock you out):

| Variable | Default | Description |
|----------|---------|-------------|
| `WEB_ENABLED` | `true` | Serve the web UI |
| `WEB_HOST` | `0.0.0.0` | Bind address |
| `WEB_PORT` | `8080` | Port |
| `WEB_USERNAME` | `admin` | Basic auth username |
| `WEB_PASSWORD` | - | Basic auth password; empty disables auth |
| `CONFIG_FILE` | `config.json` (app dir) | Where UI-saved settings are stored |

The UI is plain HTTP intended for trusted local networks. Set `WEB_PASSWORD`
if others share your network, or `WEB_ENABLED=false` to turn it off entirely.

## Configuration

Configuration can be done via the web UI (above) or environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MQTT_BROKER` | `mqtt.example.com` | MQTT broker hostname |
| `MQTT_PORT` | `8883` | MQTT broker port |
| `MQTT_USERNAME` | - | MQTT username |
| `MQTT_PASSWORD` | - | MQTT password |
| `MQTT_USE_TLS` | `true` | Enable TLS encryption |
| `MQTT_TOPIC_PREFIX` | `sensors` | MQTT topic prefix |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `NEW_DEVICES` | `publish` | `publish` new sensors automatically, or `ignore` them until enabled in the UI |

Values saved from the web UI (stored in `config.json`) override environment
variables.

## Usage

### Run directly

```bash
source venv/bin/activate
python gateway.py
```

### Run as systemd service

1. Copy files to `/opt/ble-gateway`:
   ```bash
   sudo mkdir -p /opt/ble-gateway
   sudo cp gateway.py config.py webui.py requirements.txt /opt/ble-gateway/
   sudo python3 -m venv /opt/ble-gateway/venv
   sudo /opt/ble-gateway/venv/bin/pip install -r /opt/ble-gateway/requirements.txt
   ```

2. Install and enable service:
   ```bash
   sudo cp ble-gateway.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now ble-gateway
   ```

3. Check status:
   ```bash
   sudo systemctl status ble-gateway
   sudo journalctl -u ble-gateway -f
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
sensors/{brand}/{device_mac}/temperature  - Temperature in Celsius (e.g., "23.5")
sensors/{brand}/{device_mac}/humidity     - Relative humidity percentage (e.g., "49.9")
sensors/{brand}/{device_mac}/battery      - Battery percentage (e.g., "92")
sensors/{brand}/{device_mac}/pressure     - Atmospheric pressure in hPa (e.g., "1013.2")
sensors/{brand}/{device_mac}/voltage      - Battery voltage in V (e.g., "2.9")
```

Brands: `govee`, `thermopro`, `inkbird`, `sensorpush`, `ruuvi`

Examples:
```
sensors/govee/a4:c1:38:xx:xx:xx/temperature
sensors/thermopro/c9:5f:6b:xx:xx:xx/humidity
sensors/inkbird/4c:c3:a3:xx:xx:xx/battery
sensors/sensorpush/a1:b2:c3:xx:xx:xx/temperature
sensors/ruuvi/d4:e5:f6:xx:xx:xx/pressure
```

MAC addresses are lowercase with colons.

Messages are published with the `retain` flag set.

## Example Output

```
2024-12-27 15:28:42 - ble-gateway - INFO - Device: 535C2D47-BF8F-7D78-BF11-C9F2602F4BE4 (Govee_H5074_38A8)
2024-12-27 15:28:42 - ble-gateway - INFO -   Temperature: 23.0°C
2024-12-27 15:28:42 - ble-gateway - INFO -   Humidity: 49.9%
2024-12-27 15:28:42 - ble-gateway - INFO -   Battery: 92%
```

## Dependencies

- [govee-ble](https://github.com/Bluetooth-Devices/govee-ble) - Govee BLE advertisement parser
- [thermopro-ble](https://github.com/Bluetooth-Devices/thermopro-ble) - ThermoPro BLE advertisement parser
- [inkbird-ble](https://github.com/Bluetooth-Devices/inkbird-ble) - Inkbird BLE advertisement parser
- [sensorpush-ble](https://github.com/Bluetooth-Devices/sensorpush-ble) - SensorPush BLE advertisement parser
- [ruuvitag-ble](https://github.com/Bluetooth-Devices/ruuvitag-ble) - RuuviTag BLE advertisement parser
- [bleak](https://github.com/hbldh/bleak) - Bluetooth Low Energy platform-agnostic client
- [paho-mqtt](https://github.com/eclipse/paho.mqtt.python) - MQTT client library

## License

MIT
