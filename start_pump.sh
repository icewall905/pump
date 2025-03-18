#!/bin/bash

ENV_NAME="pump_env"  # Name your conda environment

# Check if conda is available
if ! command -v conda &> /dev/null; then
    echo "Conda not found! Please install Anaconda or Miniconda."
    exit 1
fi

# Initialize conda for shell if needed
conda_init_status=$(conda info --json | grep -c "not initialized")
if [ $conda_init_status -gt 0 ]; then
    echo "Initializing conda for your shell..."
    conda init "$(basename "$SHELL")"
    echo "Please restart your terminal and run this script again."
    exit 1
fi

# Check if our environment exists
if ! conda env list | grep -q "^${ENV_NAME}"; then
    echo "Creating conda environment '${ENV_NAME}'..."
    conda create -y -n $ENV_NAME python=3.9
fi

# Activate the environment
echo "Activating conda environment..."
eval "$(conda shell.bash hook)"
conda activate $ENV_NAME

# Create requirements.txt with all necessary packages
echo "Determining required packages..."
cat > requirements.txt << EOF
flask
requests
werkzeug
numpy
pandas
matplotlib
librosa
spotipy
pylast
mutagen
audioread
pydub
scikit-learn
tqdm
lxml
beautifulsoup4
pillow
musicbrainzngs
python-dotenv
acoustid
discogs-client
pyacoustid
tinytag
eyeD3
EOF

# Install all required packages
echo "Installing required packages..."
pip install -r requirements.txt

# Function to check if module is available
check_module() {
    python -c "import $1" 2>/dev/null
    if [ $? -eq 0 ]; then
        echo "✓ $1 is available"
    else
        echo "⚠️ $1 is not available - installing..."
        pip install $1
    fi
}

# Check critical modules
echo "Verifying critical modules..."
check_module flask
check_module musicbrainzngs
check_module spotipy
check_module pylast

# Start the web player
echo "Starting Pump Web Player..."
python web_player.py

# If the server exits, wait for user input before closing
echo ""
echo "Server stopped. Press any key to close this window..."
read -n 1