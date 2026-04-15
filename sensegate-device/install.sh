#!/bin/bash
echo "=== INSTALL SENSEGATE DEVICE ==="

sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-pip git libcamera-apps -y

pip3 install -r requirements.txt

sudo cp people_counter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable people_counter

echo "=== INSTALL DONE ==="