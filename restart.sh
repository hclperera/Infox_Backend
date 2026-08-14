#!/bin/bash
# Restart the InfoX API server

echo "Restarting infox_api.service..."
sudo systemctl restart infox_api.service

# Wait a moment and show status
sleep 1
systemctl status infox_api.service --no-pager -l
