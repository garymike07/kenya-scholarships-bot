#!/bin/bash
# Auto-restart bot with crash recovery
# Usage: nohup ./run.sh > /dev/null 2>&1 &

cd "$(dirname "$0")"
LOG="bot.log"
MAX_LOG_SIZE=10485760  # 10MB

while true; do
    # Rotate log if too large
    if [ -f "$LOG" ] && [ "$(stat -f%z "$LOG" 2>/dev/null || stat -c%s "$LOG" 2>/dev/null)" -gt "$MAX_LOG_SIZE" ] 2>/dev/null; then
        mv "$LOG" "${LOG}.old"
    fi

    echo "[$(date)] Starting grants bot (PID $$)..." >> "$LOG"
    python3 main.py >> "$LOG" 2>&1
    EXIT_CODE=$?
    echo "[$(date)] Bot exited with code $EXIT_CODE" >> "$LOG"

    if [ $EXIT_CODE -eq 0 ]; then
        echo "[$(date)] Clean exit. Restarting in 5s..." >> "$LOG"
        sleep 5
    else
        echo "[$(date)] Crash detected. Restarting in 15s..." >> "$LOG"
        sleep 15
    fi
done
