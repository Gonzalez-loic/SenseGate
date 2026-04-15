#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

sudo apt update
sudo apt install -y python3 python3-venv python3-pip python3-opencv python3-gi python3-gst-1.0 gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good sqlite3 libatlas-base-dev

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

mkdir -p runtime logs

sudo cp deploy/people_counter.service /etc/systemd/system/people_counter.service
sudo systemctl daemon-reload
sudo systemctl enable people_counter

echo "Installation terminée."
echo "1) cp config.example.yaml config.yaml"
echo "2) nano config.yaml"
echo "3) sudo systemctl restart people_counter"
