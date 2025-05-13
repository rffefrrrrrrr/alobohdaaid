#!/bin/bash

# Start the keep-alive HTTP server in the background
python3 keep_alive_http.py &

# Wait a second for the server to potentially start (optional)
sleep 1

# Print the Uptime URL to the console
# We extract the URL using Python to ensure consistency with the bot's logic
UPTIME_URL=$(python3 -c "from utils.uptime_url import UPTIME_URL; print(UPTIME_URL)")
echo "-----------------------------------------------------"
echo "Uptime Monitoring URL: $UPTIME_URL"
echo "-----------------------------------------------------"

# Start the main bot application
python3 main.py

