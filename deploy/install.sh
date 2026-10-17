#!/usr/bin/env bash
# Install price-tracker on a Linux server and schedule it daily with systemd.
# Run from the project folder on the server:   bash deploy/install.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

echo "==> Creating virtual environment in $APP_DIR/.venv"
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
mkdir -p output data logs

echo "==> Installing systemd units"
# Point the unit at this folder and user, whatever they are on this server
sed -e "s#/home/ubuntu/price-tracker#$APP_DIR#g" -e "s#^User=.*#User=$(id -un)#" \
    deploy/price-tracker.service | sudo tee /etc/systemd/system/price-tracker.service >/dev/null
sudo cp deploy/price-tracker.timer /etc/systemd/system/price-tracker.timer
sudo systemctl daemon-reload
sudo systemctl enable --now price-tracker.timer

echo "==> Done. Next scheduled run:"
systemctl list-timers price-tracker.timer --no-pager
