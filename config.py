"""Configuration for the BLE gateway.

Settings precedence: config.json > environment variables > defaults.
The web UI writes config.json; environment variables keep working for
deployments that don't use the UI. Web server settings are environment-only
so a bad save can never lock you out of the UI.
"""

import json
import logging
import os
import threading

logger = logging.getLogger("ble-gateway.config")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.getenv("CONFIG_FILE", os.path.join(_BASE_DIR, "config.json"))

# Web UI (environment-only)
WEB_ENABLED = os.getenv("WEB_ENABLED", "true").lower() == "true"
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
WEB_USERNAME = os.getenv("WEB_USERNAME", "admin")
WEB_PASSWORD = os.getenv("WEB_PASSWORD", "")  # empty = no auth

NEW_DEVICE_POLICIES = ("publish", "ignore")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

# setting name -> (environment variable, default, type)
SETTINGS = {
    "mqtt_broker": ("MQTT_BROKER", "mqtt.example.com", str),
    "mqtt_port": ("MQTT_PORT", 8883, int),
    "mqtt_username": ("MQTT_USERNAME", "", str),
    "mqtt_password": ("MQTT_PASSWORD", "", str),
    "mqtt_use_tls": ("MQTT_USE_TLS", True, bool),
    "mqtt_topic_prefix": ("MQTT_TOPIC_PREFIX", "sensors", str),
    "log_level": ("LOG_LEVEL", "INFO", str),
    "new_devices": ("NEW_DEVICES", "publish", str),
}

# Settings whose change requires reconnecting to MQTT, i.e. a gateway restart.
RESTART_SETTINGS = {"mqtt_broker", "mqtt_port", "mqtt_username", "mqtt_password", "mqtt_use_tls"}


def _coerce(value, typ):
    if typ is bool:
        if isinstance(value, bool):
            return value
        return str(value).lower() == "true"
    return typ(value)


class Config:
    def __init__(self, path: str = CONFIG_FILE):
        self.path = path
        self._lock = threading.Lock()
        self.devices: dict[str, dict] = {}
        self.load()

    def load(self):
        file_data = {}
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    file_data = json.load(f)
            except (OSError, ValueError) as e:
                logger.error(f"Ignoring unreadable {self.path}: {e}")

        for name, (env_var, default, typ) in SETTINGS.items():
            value = os.environ.get(env_var, default)
            value = file_data.get(name, value)
            try:
                value = _coerce(value, typ)
            except (TypeError, ValueError):
                logger.error(f"Invalid value {value!r} for {name}, using {default!r}")
                value = default
            setattr(self, name, value)

        if self.new_devices not in NEW_DEVICE_POLICIES:
            self.new_devices = "publish"
        if self.log_level not in LOG_LEVELS:
            self.log_level = "INFO"

        self.devices = {
            mac.lower(): {
                "enabled": bool(entry.get("enabled", True)),
                "name": str(entry.get("name", "")),
                "brand": str(entry.get("brand", "")),
            }
            for mac, entry in file_data.get("devices", {}).items()
            if isinstance(entry, dict)
        }

    def save(self):
        data = {name: getattr(self, name) for name in SETTINGS}
        data["devices"] = self.devices
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.chmod(tmp, 0o600)  # contains the MQTT password
            os.replace(tmp, self.path)
        logger.info(f"Configuration saved to {self.path}")

    def update_settings(self, changes: dict) -> set:
        """Apply recognized settings from `changes` and persist.

        Returns the names of settings that actually changed.
        Raises ValueError on values that don't fit the setting's type.
        """
        changed = set()
        for name, value in changes.items():
            if name not in SETTINGS:
                continue
            # A blank password field in the UI means "keep the current one"
            # (the page never echoes the stored password back).
            if name == "mqtt_password" and value == "":
                continue
            value = _coerce(value, SETTINGS[name][2])
            if name == "new_devices" and value not in NEW_DEVICE_POLICIES:
                raise ValueError(f"new_devices must be one of {NEW_DEVICE_POLICIES}")
            if name == "log_level" and value not in LOG_LEVELS:
                raise ValueError(f"log_level must be one of {LOG_LEVELS}")
            if getattr(self, name) != value:
                setattr(self, name, value)
                changed.add(name)
        if changed:
            self.save()
        return changed

    def set_device(self, mac: str, enabled=None, name=None, brand=None) -> dict:
        mac = mac.lower()
        entry = self.devices.setdefault(mac, {"enabled": True, "name": "", "brand": ""})
        if enabled is not None:
            entry["enabled"] = bool(enabled)
        if name is not None:
            entry["name"] = str(name)[:64]
        if brand:
            entry["brand"] = brand
        self.save()
        return entry

    def device_may_publish(self, mac: str) -> bool:
        entry = self.devices.get(mac)
        if entry is not None:
            return entry["enabled"]
        return self.new_devices == "publish"
