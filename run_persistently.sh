#!/bin/bash

# Navigate to script directory
cd "$(dirname "$0")"

LOG_FILE="persistent_runner.log"
MAIN_BOT_SCRIPT="main.py" # Assuming main.py is the correct entry point based on package.json
KEEP_ALIVE_SCRIPT="keep_alive_http.py"
PID_BOT_FILE="bot_main.pid"
PID_KEEPALIVE_FILE="bot_keepalive.pid"

log() {
    # Add timestamp to log messages
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$LOG_FILE"
}

# Function to check if a process is running using its PID file
is_running() {
    local pid_file=$1
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        # Check if a process with this PID exists
        if ps -p "$pid" > /dev/null; then
            return 0 # 0 means true (running) in bash
        fi
    fi
    return 1 # 1 means false (not running)
}

# Function to start the main bot script
start_main_bot() {
    log "Attempting to start $MAIN_BOT_SCRIPT..."
    if is_running "$PID_BOT_FILE"; then
        log "$MAIN_BOT_SCRIPT is already running (PID: $(cat $PID_BOT_FILE))."
        return
    fi
    # Clean up stale PID file if process died without removing it
    rm -f "$PID_BOT_FILE"
    # Start the bot in the background, redirect output to /dev/null instead of log file
    nohup python3 "$MAIN_BOT_SCRIPT" > /dev/null 2>&1 &
    echo $! > "$PID_BOT_FILE"
    log "$MAIN_BOT_SCRIPT started with PID $(cat $PID_BOT_FILE)."
    sleep 2 # Allow some time for the process to initialize
}

# Function to start the keep-alive Flask server
start_keepalive_server() {
    log "Attempting to start $KEEP_ALIVE_SCRIPT..."
    if is_running "$PID_KEEPALIVE_FILE"; then
        log "$KEEP_ALIVE_SCRIPT is already running (PID: $(cat $PID_KEEPALIVE_FILE))."
        return
    fi
    # Clean up stale PID file
    rm -f "$PID_KEEPALIVE_FILE"
    # Start the keep-alive server, log output, save PID
    nohup python3 "$KEEP_ALIVE_SCRIPT" & # Removed redirection to let Glitch capture output
    echo $! > "$PID_KEEPALIVE_FILE"
    log "$KEEP_ALIVE_SCRIPT started with PID $(cat $PID_KEEPALIVE_FILE)."
    # Wait longer for Flask server to bind to port
    sleep 5 
}

# --- Main Execution --- 
log "----------------------------------------"
log "Starting persistent runner script."

# Optional: Install dependencies on first run or if needed
if [ -f "requirements.txt" ]; then
    log "Checking/installing Python dependencies from requirements.txt..."
    # Using --user to avoid needing root, common in restricted environments
    pip3 install -r requirements.txt --user >> "$LOG_FILE" 2>&1
    INSTALL_EXIT_CODE=$?
    if [ $INSTALL_EXIT_CODE -eq 0 ]; then
        log "Dependencies installed/updated successfully."
    else
        log "Warning: pip install exited with code $INSTALL_EXIT_CODE. Check $LOG_FILE for details."
    fi
else
    log "requirements.txt not found, skipping dependency installation."
fi

# Initial start of both processes
log "Performing initial start checks..."
start_keepalive_server
start_main_bot

log "Entering monitoring loop..."
# Continuous monitoring loop
while true; do
    log "-- Monitoring Check --"

    # Check and restart keep-alive server if needed
    if ! is_running "$PID_KEEPALIVE_FILE"; then
        log "$KEEP_ALIVE_SCRIPT process not found. Restarting..."
        start_keepalive_server
    else
        log "$KEEP_ALIVE_SCRIPT is running (PID: $(cat $PID_KEEPALIVE_FILE))."
    fi

    # Check and restart main bot if needed
    if ! is_running "$PID_BOT_FILE"; then
        log "$MAIN_BOT_SCRIPT process not found. Restarting..."
        start_main_bot
    else
        log "$MAIN_BOT_SCRIPT is running (PID: $(cat $PID_BOT_FILE))."
    fi

    # Wait before the next check
    log "Sleeping for 60 seconds before next check."
    sleep 60
done
