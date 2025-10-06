#!/bin/bash
# Script to run EPUB processing with output logging

# Create logs directory if it doesn't exist
mkdir -p logs

# Get current timestamp
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="logs/processing_${TIMESTAMP}.log"

echo "Starting EPUB processing..."
echo "Output will be saved to: $LOG_FILE"
echo ""

# Run the command and save output to file
# Using 'tee' to show output AND save to file
python cli.py "$@" 2>&1 | tee "$LOG_FILE"

echo ""
echo "Processing complete!"
echo "Full log saved to: $LOG_FILE"