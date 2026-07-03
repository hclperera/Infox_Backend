#!/bin/bash
# Set path so git and gh work properly when run from cron
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export HOME=/home/raven

cd /home/raven/infox-backend

# Fetch latest from remote
git fetch origin

# Check if we are behind origin/master
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/master)

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "$(date): Changes detected. Pulling..."
    git pull origin master
    
    # Update dependencies if requirements.txt changed
    source venv/bin/activate
    pip install -r requirements.txt
    
    echo "$(date): Restarting service..."
    sudo systemctl restart infox_api.service
    echo "$(date): Update complete."
fi
