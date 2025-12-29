#!/bin/bash
#
# BLE Gateway Installer for Raspberry Pi
# https://github.com/bogdan42k/ble-gateway
#

set -e

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

INSTALL_DIR="/opt/ble-gateway"
SERVICE_NAME="ble-gateway"
REPO_URL="https://github.com/bogdan42k/ble-gateway.git"

print_banner() {
    echo ""
    echo -e "${BLUE}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║     BLE Gateway Installer for Raspberry Pi   ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════════╝${NC}"
    echo ""
}

print_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[i]${NC} $1"
}

check_root() {
    if [ "$EUID" -ne 0 ]; then
        print_error "This script must be run as root (use sudo)"
        echo ""
        echo "  Run: curl -sSL https://raw.githubusercontent.com/bogdan42k/ble-gateway/main/install.sh | sudo bash"
        echo ""
        exit 1
    fi
}

check_raspberry_pi() {
    if [ -f /proc/device-tree/model ]; then
        MODEL=$(tr -d '\0' < /proc/device-tree/model)
        if [[ "$MODEL" == *"Raspberry Pi"* ]]; then
            print_success "Raspberry Pi detected: $MODEL"
            return 0
        fi
    fi
    print_warning "Raspberry Pi not detected (continuing anyway)"
    return 0
}

check_python() {
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
        PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d'.' -f1)
        PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)

        if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 10 ]; then
            print_success "Python $PYTHON_VERSION found"
            return 0
        else
            print_error "Python 3.10+ required, found $PYTHON_VERSION"
            exit 1
        fi
    else
        print_error "Python 3 not found"
        exit 1
    fi
}

check_bluetooth() {
    if hciconfig hci0 &> /dev/null; then
        print_success "Bluetooth adapter available"
    else
        print_warning "Bluetooth adapter not detected (may need reboot after install)"
    fi
}

install_dependencies() {
    echo ""
    print_info "Installing system dependencies..."
    apt-get update -qq
    apt-get install -y -qq python3-venv python3-pip python3-dev build-essential libffi-dev libssl-dev bluetooth bluez git > /dev/null
    print_success "System packages installed"
}

download_gateway() {
    echo ""
    print_info "Downloading BLE Gateway..."

    if [ -d "$INSTALL_DIR" ]; then
        print_warning "Existing installation found, updating..."
        cd "$INSTALL_DIR"
        git pull -q
    else
        git clone -q "$REPO_URL" "$INSTALL_DIR"
    fi

    print_success "Downloaded to $INSTALL_DIR"
}

setup_python() {
    echo ""
    print_info "Setting up Python environment..."

    cd "$INSTALL_DIR"
    python3 -m venv venv
    print_success "Virtual environment created"

    # Use disk instead of tmpfs for builds (Pi has small /tmp)
    mkdir -p "$INSTALL_DIR/.pip-tmp"
    export TMPDIR="$INSTALL_DIR/.pip-tmp"

    ./venv/bin/pip install -q --upgrade pip
    ./venv/bin/pip install -q -r requirements.txt
    print_success "Dependencies installed"

    # Cleanup build temp
    rm -rf "$INSTALL_DIR/.pip-tmp"
}

configure_mqtt() {
    echo ""
    echo -e "${BLUE}MQTT Configuration:${NC}"
    echo ""

    # Check for existing config
    if [ -f "$INSTALL_DIR/.env" ]; then
        print_warning "Existing configuration found"
        read -p "  Reconfigure? [y/N]: " RECONFIG < /dev/tty
        if [[ ! "$RECONFIG" =~ ^[Yy]$ ]]; then
            print_info "Keeping existing configuration"
            return 0
        fi
    fi

    # MQTT Broker
    read -p "  MQTT Broker address: " MQTT_BROKER < /dev/tty
    if [ -z "$MQTT_BROKER" ]; then
        print_error "MQTT Broker is required"
        exit 1
    fi

    # MQTT Port
    read -p "  MQTT Port [8883]: " MQTT_PORT < /dev/tty
    MQTT_PORT=${MQTT_PORT:-8883}

    # MQTT Username
    read -p "  MQTT Username: " MQTT_USERNAME < /dev/tty

    # MQTT Password
    read -s -p "  MQTT Password: " MQTT_PASSWORD < /dev/tty
    echo ""

    # TLS
    read -p "  Use TLS encryption? [Y/n]: " USE_TLS < /dev/tty
    if [[ "$USE_TLS" =~ ^[Nn]$ ]]; then
        MQTT_USE_TLS="false"
    else
        MQTT_USE_TLS="true"
    fi

    # Write config
    cat > "$INSTALL_DIR/.env" << EOF
MQTT_BROKER=$MQTT_BROKER
MQTT_PORT=$MQTT_PORT
MQTT_USERNAME=$MQTT_USERNAME
MQTT_PASSWORD=$MQTT_PASSWORD
MQTT_USE_TLS=$MQTT_USE_TLS
LOG_LEVEL=INFO
EOF

    chmod 600 "$INSTALL_DIR/.env"
    print_success "Configuration saved"
}

install_service() {
    echo ""
    print_info "Installing systemd service..."

    cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=BLE Gateway for Govee, ThermoPro, Inkbird, SensorPush, and Ruuvi sensors
After=network.target bluetooth.target

[Service]
Type=simple
ExecStart=${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/gateway.py
WorkingDirectory=${INSTALL_DIR}
Restart=always
RestartSec=10

# Load environment variables from file
EnvironmentFile=${INSTALL_DIR}/.env

# Bluetooth access
CapabilityBoundingSet=CAP_NET_RAW CAP_NET_ADMIN
AmbientCapabilities=CAP_NET_RAW CAP_NET_ADMIN

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable ${SERVICE_NAME} > /dev/null 2>&1
    print_success "Service installed"
}

start_service() {
    systemctl restart ${SERVICE_NAME}
    sleep 2

    if systemctl is-active --quiet ${SERVICE_NAME}; then
        print_success "Service started successfully"
    else
        print_error "Service failed to start"
        echo ""
        echo "  Check logs: sudo journalctl -u ${SERVICE_NAME} -n 20"
        exit 1
    fi
}

show_success() {
    echo ""
    echo -e "${GREEN}════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  ✓ BLE Gateway is now running!${NC}"
    echo ""
    echo "  View logs:     sudo journalctl -u ${SERVICE_NAME} -f"
    echo "  Stop service:  sudo systemctl stop ${SERVICE_NAME}"
    echo "  Restart:       sudo systemctl restart ${SERVICE_NAME}"
    echo "  Reconfigure:   sudo nano ${INSTALL_DIR}/.env && sudo systemctl restart ${SERVICE_NAME}"
    echo -e "${GREEN}════════════════════════════════════════════════${NC}"
    echo ""
}

uninstall() {
    print_banner
    print_info "Uninstalling BLE Gateway..."

    # Stop and disable service
    if systemctl is-active --quiet ${SERVICE_NAME}; then
        systemctl stop ${SERVICE_NAME}
        print_success "Service stopped"
    fi

    if systemctl is-enabled --quiet ${SERVICE_NAME} 2>/dev/null; then
        systemctl disable ${SERVICE_NAME} > /dev/null 2>&1
        print_success "Service disabled"
    fi

    # Remove service file
    if [ -f /etc/systemd/system/${SERVICE_NAME}.service ]; then
        rm /etc/systemd/system/${SERVICE_NAME}.service
        systemctl daemon-reload
        print_success "Service file removed"
    fi

    # Remove installation directory
    if [ -d "$INSTALL_DIR" ]; then
        rm -rf "$INSTALL_DIR"
        print_success "Installation directory removed"
    fi

    echo ""
    print_success "BLE Gateway has been uninstalled"
    echo ""
}

# Main
main() {
    # Check for uninstall flag
    if [ "$1" = "--uninstall" ] || [ "$1" = "-u" ]; then
        check_root
        uninstall
        exit 0
    fi

    print_banner
    check_root

    echo "Checking system requirements..."
    check_raspberry_pi
    check_python
    check_bluetooth

    install_dependencies
    download_gateway
    setup_python
    configure_mqtt
    install_service
    start_service
    show_success
}

main "$@"
