#!/bin/bash

# Dead man's switch — stops and removes the project if .paid file not found within 12 hours
# Setup: run once manually to set the deadline, then add to crontab

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAID_FILE="$SCRIPT_DIR/.paid"
DEADLINE_FILE="$SCRIPT_DIR/.deadline"
LOG_FILE="$SCRIPT_DIR/.deadman.log"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# First run: write the deadline (now + 12 hours)
if [ ! -f "$DEADLINE_FILE" ]; then
  DEADLINE=$(date -d '+12 hours' +%s 2>/dev/null || date -v+12H +%s)
  echo "$DEADLINE" > "$DEADLINE_FILE"
  log "Deadline set: $(date -d @$DEADLINE '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date -r $DEADLINE)"
  echo "Deadline set. Project will self-destruct at: $(date -d @$DEADLINE '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date -r $DEADLINE)"
  exit 0
fi

# Already paid — do nothing
if [ -f "$PAID_FILE" ]; then
  log "Payment confirmed. Exiting."
  exit 0
fi

# Check deadline
DEADLINE=$(cat "$DEADLINE_FILE")
NOW=$(date +%s)

if [ "$NOW" -lt "$DEADLINE" ]; then
  REMAINING=$(( (DEADLINE - NOW) / 60 ))
  log "Waiting for payment. ${REMAINING} minutes remaining."
  exit 0
fi

# Deadline passed, no payment — kill everything
log "DEADLINE PASSED. No payment received. Shutting down..."

cd "$SCRIPT_DIR"
docker compose down --volumes 2>> "$LOG_FILE"
log "Docker containers stopped and volumes removed."

# Remove project files (keep this script and logs as evidence)
find "$SCRIPT_DIR" -mindepth 1 \
  ! -name "deadman.sh" \
  ! -name ".deadman.log" \
  ! -name ".paid" \
  ! -name ".deadline" \
  -delete 2>> "$LOG_FILE"

log "Project files removed."
