#!/bin/bash

# Check if we are inside a virtual environment
if [ -z "$VIRTUAL_ENV" ]; then
    echo "Virtual environment not detected. Setting up environment..."
    # Source the env_load.sh to activate or create the virtual environment
    source ./env_load.sh
fi

# Start the web player and keep the terminal open
echo "Starting Pump Web Player..."
python3 web_player.py

# If the server exits, wait for user input before closing
echo ""
echo "Server stopped. Press any key to close this window..."
read -n 1
