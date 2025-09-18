#!/bin/bash

# Sync All Platforms Script
# This script triggers the sync process for all configured platforms
# It can be run manually or via cron

# Configuration
BASE_URL="${BASE_URL:-http://localhost:8080}"
AUTH_USER="${BASIC_AUTH_USERNAME:-}"
AUTH_PASS="${BASIC_AUTH_PASSWORD:-}"
MAX_CONCURRENT="${MAX_CONCURRENT:-2}"
PLATFORMS="${PLATFORMS:-}"  # Empty means all platforms

# Logging configuration
LOG_DIR="${LOG_DIR:-/Users/wommy/Documents/GitHub/PROJECTS/HANKS/inventory_system/logs}"
LOG_FILE="${LOG_DIR}/sync_all_platforms_$(date +%Y%m%d).log"
KEEP_LOGS_DAYS="${KEEP_LOGS_DAYS:-30}"  # Keep logs for 30 days by default

# Create log directory if it doesn't exist
mkdir -p "$LOG_DIR"

# Colors for output (only when running interactively)
if [ -t 1 ]; then
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    RED='\033[0;31m'
    NC='\033[0m' # No Color
else
    GREEN=''
    YELLOW=''
    RED=''
    NC=''
fi

# Function to print timestamp
timestamp() {
    date "+%Y-%m-%d %H:%M:%S"
}

# Function to log messages to both console and file
log() {
    local message="[$(timestamp)] $1"
    echo -e "$message" | tee -a "$LOG_FILE"
}

# Function to log without color codes to file only
log_file() {
    echo "[$(timestamp)] $1" >> "$LOG_FILE"
}

# Clean up old logs
find "$LOG_DIR" -name "sync_all_platforms_*.log" -mtime +$KEEP_LOGS_DAYS -delete 2>/dev/null

# Start logging
log "=========================================="
log "SYNC ALL PLATFORMS - STARTING"
log "=========================================="
log_file "Script: $0"
log_file "User: $(whoami)"
log_file "Host: $(hostname)"
log_file "Working Directory: $(pwd)"

# Check if running on Railway
if [ -n "$RAILWAY_ENVIRONMENT" ]; then
    log "${GREEN}Running on Railway environment${NC}"
    BASE_URL="https://${RAILWAY_PUBLIC_DOMAIN:-your-app.up.railway.app}"
fi

# Check if auth credentials are provided
if [ -z "$AUTH_USER" ] || [ -z "$AUTH_PASS" ]; then
    log "${RED}ERROR: AUTH_USER and AUTH_PASS environment variables must be set${NC}"
    log "Usage: AUTH_USER=your_user AUTH_PASS=your_pass $0"
    exit 1
fi

# Build the API endpoint URL
ENDPOINT="${BASE_URL}/api/sync/all"
if [ -n "$PLATFORMS" ]; then
    ENDPOINT="${ENDPOINT}?platforms=${PLATFORMS}&max_concurrent=${MAX_CONCURRENT}"
else
    ENDPOINT="${ENDPOINT}?max_concurrent=${MAX_CONCURRENT}"
fi

log "${YELLOW}Starting sync process...${NC}"
log "Endpoint: $ENDPOINT"
log "Max concurrent: $MAX_CONCURRENT"
if [ -n "$PLATFORMS" ]; then
    log "Platforms: $PLATFORMS"
else
    log "Platforms: All configured"
fi

# Create auth header
AUTH_HEADER=$(echo -n "$AUTH_USER:$AUTH_PASS" | base64)

# Make the API call
log "Calling sync API..."
log_file "Full command: curl -X POST -H 'Authorization: Basic [REDACTED]' '$ENDPOINT'"

# Create temp file for curl output
TEMP_FILE=$(mktemp)
CURL_LOG=$(mktemp)

# Execute curl with detailed logging
HTTP_CODE=$(curl -s -w "%{http_code}" -X POST \
    -H "Authorization: Basic $AUTH_HEADER" \
    -H "Content-Type: application/json" \
    --output "$TEMP_FILE" \
    "$ENDPOINT" 2>"$CURL_LOG")

BODY=$(cat "$TEMP_FILE")
CURL_ERRORS=$(cat "$CURL_LOG")

# Clean up temp files
rm -f "$TEMP_FILE" "$CURL_LOG"

# Log curl errors if any
if [ -n "$CURL_ERRORS" ]; then
    log_file "Curl errors: $CURL_ERRORS"
fi

# Log raw response for debugging
log_file "HTTP Status Code: $HTTP_CODE"
log_file "Raw Response Body: $BODY"

# Check the response
if [ "$HTTP_CODE" -eq 200 ]; then
    log "${GREEN}SUCCESS: Sync initiated successfully${NC}"

    # Pretty print the JSON response if jq is available
    if command -v jq &> /dev/null; then
        # Save formatted JSON to log
        echo "$BODY" | jq '.' >> "$LOG_FILE"

        # Extract key information
        STATUS=$(echo "$BODY" | jq -r '.status')
        MESSAGE=$(echo "$BODY" | jq -r '.message')
        SYNC_RUN_ID=$(echo "$BODY" | jq -r '.sync_run_id')
        PLATFORMS_ATTEMPTED=$(echo "$BODY" | jq -r '.platforms_attempted[]' 2>/dev/null | tr '\n' ', ' | sed 's/,$//')
        SUCCESSFUL=$(echo "$BODY" | jq -r '.successful_platforms[]' 2>/dev/null | tr '\n' ', ' | sed 's/,$//')
        FAILED=$(echo "$BODY" | jq -r '.failed_platforms[]' 2>/dev/null | tr '\n' ', ' | sed 's/,$//')

        log "Overall Status: $STATUS"
        log "Message: $MESSAGE"
        log "Sync Run ID: $SYNC_RUN_ID"
        log "Platforms Attempted: ${PLATFORMS_ATTEMPTED:-none}"
        log "Successful: ${SUCCESSFUL:-none}"
        log "Failed: ${FAILED:-none}"

        # Log individual platform results
        log ""
        log "Individual Platform Results:"
        echo "$BODY" | jq -r '.results | to_entries[] | "\(.key): \(.value.status) - \(.value.message)"' | while read -r line; do
            log "  $line"
        done

        # Display summary on console if interactive
        if [ -t 1 ]; then
            echo ""
            echo "Summary:"
            echo "  Status: $STATUS"
            echo "  Sync Run ID: $SYNC_RUN_ID"
            echo "  Check full log at: $LOG_FILE"
        fi
    else
        log "Raw response: $BODY"
        log_file "Note: Install 'jq' for better JSON formatting"
    fi

    log ""
    log "=========================================="
    log "SYNC ALL PLATFORMS - COMPLETED"
    log "=========================================="
    exit 0
else
    log "${RED}ERROR: Sync failed with HTTP status $HTTP_CODE${NC}"
    log "Response: $BODY"

    # Try to extract error details if JSON
    if command -v jq &> /dev/null && echo "$BODY" | jq . >/dev/null 2>&1; then
        ERROR_MSG=$(echo "$BODY" | jq -r '.message // .detail // .error // "Unknown error"')
        log "Error details: $ERROR_MSG"
    fi

    log ""
    log "=========================================="
    log "SYNC ALL PLATFORMS - FAILED"
    log "=========================================="
    exit 1
fi