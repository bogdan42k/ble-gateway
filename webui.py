"""Embedded web UI for configuring the gateway over the local network.

Stdlib-only (http.server in a daemon thread): two JSON endpoints and one
inline HTML page. MQTT/broker settings restart the gateway on save; device
enable/disable and renames apply live.
"""

import base64
import hmac
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config

logger = logging.getLogger("ble-gateway.webui")

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BLE Gateway</title>
<style>
:root {
  color-scheme: light dark;
  --bg: #f4f5f7; --card: #ffffff; --text: #1a1d21; --muted: #6b7280;
  --border: #e2e4e8; --accent: #2563eb; --ok: #16a34a; --bad: #dc2626;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #14161a; --card: #1e2126; --text: #e5e7eb; --muted: #9ca3af;
          --border: #33373d; --accent: #3b82f6; --ok: #22c55e; --bad: #ef4444; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
       font: 15px/1.5 system-ui, -apple-system, sans-serif; }
main { max-width: 900px; margin: 0 auto; padding: 16px; }
h1 { font-size: 1.3em; margin: 8px 0 2px; }
h2 { font-size: 1.05em; margin: 0 0 12px; }
.sub { color: var(--muted); font-size: .85em; margin-bottom: 16px; }
.card { background: var(--card); border: 1px solid var(--border);
        border-radius: 10px; padding: 16px; margin-bottom: 16px; }
.dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%;
       margin-right: 5px; background: var(--bad); }
.dot.ok { background: var(--ok); }
.tablewrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .92em; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--border);
         white-space: nowrap; }
th { color: var(--muted); font-weight: 600; font-size: .85em; }
tr:last-child td { border-bottom: none; }
td.name { cursor: pointer; }
td.name:hover::after { content: " \\270E"; color: var(--muted); }
.mac { font-family: ui-monospace, monospace; font-size: .9em; color: var(--muted); }
.badge { font-size: .75em; padding: 1px 7px; border-radius: 9px;
         background: var(--accent); color: #fff; margin-left: 6px; }
.off { color: var(--muted); }
label { display: block; margin: 10px 0 3px; font-size: .88em; color: var(--muted); }
input[type=text], input[type=password], input[type=number], select {
  width: 100%; max-width: 380px; padding: 7px 9px; border-radius: 7px;
  border: 1px solid var(--border); background: var(--bg); color: var(--text);
  font: inherit; }
.row { display: flex; gap: 24px; flex-wrap: wrap; align-items: center; }
button { margin-top: 14px; padding: 8px 18px; border: none; border-radius: 7px;
         background: var(--accent); color: #fff; font: inherit; cursor: pointer; }
button:disabled { opacity: .5; cursor: default; }
.switch { position: relative; display: inline-block; width: 36px; height: 20px; }
.switch input { opacity: 0; width: 0; height: 0; }
.slider { position: absolute; inset: 0; background: var(--border);
          border-radius: 20px; transition: .15s; cursor: pointer; }
.slider:before { content: ""; position: absolute; height: 14px; width: 14px;
                 left: 3px; top: 3px; background: #fff; border-radius: 50%; transition: .15s; }
input:checked + .slider { background: var(--ok); }
input:checked + .slider:before { transform: translateX(16px); }
.note { font-size: .82em; color: var(--muted); margin-top: 8px; }
#msg { margin-top: 10px; font-size: .9em; min-height: 1.2em; }
</style>
</head>
<body>
<main>
<h1>BLE Gateway</h1>
<div class="sub" id="status">Loading&hellip;</div>

<div class="card">
  <h2>Sensors</h2>
  <div class="row">
    <label style="margin:0">New devices:
      <select id="policy" onchange="setPolicy()" style="width:auto;margin-left:6px">
        <option value="publish">publish automatically</option>
        <option value="ignore">ignore until enabled</option>
      </select>
    </label>
  </div>
  <div class="tablewrap">
  <table>
    <thead><tr><th>Name</th><th>Brand</th><th>MAC</th><th>RSSI</th>
      <th>Last seen</th><th>Readings</th><th>Publish</th></tr></thead>
    <tbody id="devices"><tr><td colspan="7" class="off">No sensors discovered yet.</td></tr></tbody>
  </table>
  </div>
  <div class="note">Click a name to rename. Disabling a sensor stops publishing
    immediately and clears its retained MQTT topics.</div>
</div>

<div class="card">
  <h2>MQTT</h2>
  <form onsubmit="saveSettings(event)">
    <label>Broker <input type="text" id="mqtt_broker" required></label>
    <label>Port <input type="number" id="mqtt_port" min="1" max="65535" required></label>
    <label>Username <input type="text" id="mqtt_username" autocomplete="off"></label>
    <label>Password <input type="password" id="mqtt_password" autocomplete="new-password"
        placeholder="(unchanged)"></label>
    <label>Topic prefix <input type="text" id="mqtt_topic_prefix" required></label>
    <div class="row">
      <label><input type="checkbox" id="mqtt_use_tls"> Use TLS</label>
      <label>Log level
        <select id="log_level" style="width:auto;margin-left:6px">
          <option>DEBUG</option><option>INFO</option><option>WARNING</option><option>ERROR</option>
        </select>
      </label>
    </div>
    <button id="save">Save</button>
    <div class="note">Changing broker settings restarts the gateway (a few seconds).</div>
    <div id="msg"></div>
  </form>
</div>
</main>

<script>
const $ = id => document.getElementById(id);
const UNITS = {temperature: "\\u00B0C", humidity: "%", battery: "%", pressure: " hPa", voltage: "V"};
let settingsDirty = false;
["mqtt_broker","mqtt_port","mqtt_username","mqtt_password","mqtt_topic_prefix"]
  .forEach(id => $(id).addEventListener("input", () => settingsDirty = true));

function ago(ts) {
  if (!ts) return "\\u2014";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return Math.round(s) + "s ago";
  if (s < 3600) return Math.round(s / 60) + "m ago";
  if (s < 86400) return Math.round(s / 3600) + "h ago";
  return Math.round(s / 86400) + "d ago";
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
}

function render(state) {
  $("status").innerHTML =
    '<span class="dot ' + (state.mqtt_connected ? "ok" : "") + '"></span>' +
    (state.mqtt_connected ? "MQTT connected to " : "MQTT disconnected from ") +
    esc(state.settings.mqtt_broker) + " &middot; v" + esc(state.version);

  if (!settingsDirty) {
    for (const k of ["mqtt_broker","mqtt_port","mqtt_username","mqtt_topic_prefix"])
      $(k).value = state.settings[k];
    $("mqtt_use_tls").checked = state.settings.mqtt_use_tls;
    $("log_level").value = state.settings.log_level;
    $("policy").value = state.settings.new_devices;
  }

  const rows = state.devices.map(d => {
    const readings = Object.entries(d.readings)
      .map(([k, v]) => v + (UNITS[k] || "")).join(", ") || "\\u2014";
    const name = d.name || d.ble_name || "(unnamed)";
    const badge = d.is_new ? ' <span class="badge">new</span>' : "";
    return '<tr' + (d.publishing ? "" : ' class="off"') + '>' +
      '<td class="name" onclick="rename(\\'' + d.mac + '\\',\\'' + esc(d.name).replace(/'/g, "\\\\'") + '\\')">' +
        esc(name) + badge + '</td>' +
      '<td>' + esc(d.brand || "?") + '</td>' +
      '<td class="mac">' + d.mac + '</td>' +
      '<td>' + (d.rssi ?? "\\u2014") + '</td>' +
      '<td>' + ago(d.last_seen) + '</td>' +
      '<td>' + esc(readings) + '</td>' +
      '<td><label class="switch"><input type="checkbox" ' + (d.enabled ? "checked" : "") +
        ' onchange="toggle(\\'' + d.mac + '\\', this.checked)"><span class="slider"></span></label></td>' +
      '</tr>';
  });
  $("devices").innerHTML = rows.join("") ||
    '<tr><td colspan="7" class="off">No sensors discovered yet.</td></tr>';
}

async function api(path, body) {
  const res = await fetch(path, body
    ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)}
    : undefined);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function refresh() {
  try { render(await api("/api/state")); } catch (e) { /* gateway restarting */ }
}

async function toggle(mac, enabled) {
  await api("/api/device", {mac, enabled});
  refresh();
}

async function rename(mac, current) {
  const name = prompt("Sensor name:", current);
  if (name === null) return;
  await api("/api/device", {mac, name});
  refresh();
}

async function setPolicy() {
  await api("/api/settings", {new_devices: $("policy").value});
}

async function saveSettings(ev) {
  ev.preventDefault();
  const body = {
    mqtt_broker: $("mqtt_broker").value,
    mqtt_port: parseInt($("mqtt_port").value, 10),
    mqtt_username: $("mqtt_username").value,
    mqtt_password: $("mqtt_password").value,
    mqtt_use_tls: $("mqtt_use_tls").checked,
    mqtt_topic_prefix: $("mqtt_topic_prefix").value,
    log_level: $("log_level").value,
  };
  $("save").disabled = true;
  try {
    const res = await api("/api/settings", body);
    settingsDirty = false;
    $("mqtt_password").value = "";
    $("msg").textContent = res.restarting
      ? "Saved. Gateway is restarting\\u2026" : "Saved.";
    if (res.restarting) setTimeout(() => { $("msg").textContent = ""; refresh(); }, 6000);
  } catch (e) {
    $("msg").textContent = "Error: " + e.message;
  } finally {
    $("save").disabled = false;
  }
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "BLEGateway"

    # --- helpers -----------------------------------------------------------

    def _authorized(self) -> bool:
        if not config.WEB_PASSWORD:
            return True
        expected = "Basic " + base64.b64encode(
            f"{config.WEB_USERNAME}:{config.WEB_PASSWORD}".encode()
        ).decode()
        return hmac.compare_digest(self.headers.get("Authorization", ""), expected)

    def _deny(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="BLE Gateway"')
        self.end_headers()

    def _send(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status: int = 200):
        self._send(status, json.dumps(data).encode(), "application/json")

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if not 0 < length <= 65536:
            return None
        try:
            return json.loads(self.rfile.read(length))
        except ValueError:
            return None

    # --- routes ------------------------------------------------------------

    def do_GET(self):
        if not self._authorized():
            return self._deny()
        if self.path == "/":
            return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        if self.path == "/api/state":
            return self._json(self.server.gateway.state())
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if not self._authorized():
            return self._deny()
        body = self._read_json()
        if not isinstance(body, dict):
            return self._json({"error": "invalid JSON body"}, 400)

        gateway = self.server.gateway
        try:
            if self.path == "/api/settings":
                restarting = gateway.apply_settings(body)
                return self._json({"ok": True, "restarting": restarting})
            if self.path == "/api/device":
                mac = str(body.get("mac", "")).lower()
                if mac not in gateway.seen and mac not in gateway.config.devices:
                    return self._json({"error": "unknown device"}, 404)
                entry = gateway.set_device(
                    mac, enabled=body.get("enabled"), name=body.get("name")
                )
                return self._json({"ok": True, "device": entry})
        except ValueError as e:
            return self._json({"error": str(e)}, 400)
        self._send(404, b"not found", "text/plain")

    def log_message(self, fmt, *args):
        logger.debug("%s %s", self.address_string(), fmt % args)


def start_webui(gateway) -> ThreadingHTTPServer:
    """Start the web UI in a daemon thread; returns the server."""
    server = ThreadingHTTPServer((config.WEB_HOST, config.WEB_PORT), Handler)
    server.daemon_threads = True
    server.gateway = gateway
    threading.Thread(target=server.serve_forever, daemon=True, name="webui").start()
    auth = " (basic auth on)" if config.WEB_PASSWORD else ""
    logger.info(f"Web UI listening on http://{config.WEB_HOST}:{config.WEB_PORT}{auth}")
    return server
