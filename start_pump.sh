#!/bin/bash

# Start the web player and keep the terminal open
echo "Starting Pump Web Player..."
python3 web_player.py

# If the server exits, wait for user input before closing
echo ""
echo "Server stopped. Press any key to close this window..."
read -n 1