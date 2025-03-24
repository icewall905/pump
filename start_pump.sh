#!/bin/bash

ENV_NAME="pump_env"  # Name your environment
LOG_DIR="logs"       # Directory for log files

# Function to display colored messages
print_message() {
    local color=$1
    local message=$2
    case $color in
        "green") echo -e "\e[32m$message\e[0m" ;;
        "yellow") echo -e "\e[33m$message\e[0m" ;;
        "red") echo -e "\e[31m$message\e[0m" ;;
        *) echo "$message" ;;
    esac
}

# Check if running with sudo (needed for apt installs)
check_sudo() {
    if [ "$EUID" -ne 0 ]; then
        print_message "yellow" "Note: For system dependencies, you might be asked for your password."
    fi
}

# Setup environment based on available tools (conda or venv)
if command -v conda &> /dev/null; then
    print_message "green" "Conda detected. Using conda environment..."
    
    # Initialize conda for shell if needed
    conda_init_status=$(conda info --json | grep -c "not initialized")
    if [ $conda_init_status -gt 0 ]; then
        print_message "yellow" "Initializing conda for your shell..."
        conda init "$(basename "$SHELL")"
        print_message "yellow" "Please restart your terminal and run this script again."
        exit 1
    fi

    # Check if our environment exists
    if ! conda env list | grep -q "^${ENV_NAME}"; then
        print_message "green" "Creating conda environment '${ENV_NAME}'..."
        conda create -y -n $ENV_NAME python=3.9
    fi

    # Activate the conda environment
    print_message "green" "Activating conda environment..."
    eval "$(conda shell.bash hook)"
    conda activate $ENV_NAME
else
    print_message "yellow" "Conda not found. Falling back to Python virtual environment (venv)."
    # If the venv directory doesn't exist, create it
    if [ ! -d "$ENV_NAME" ]; then
        print_message "green" "Creating virtual environment '${ENV_NAME}' using venv..."
        python3 -m venv $ENV_NAME
    fi
    # Activate the venv
    print_message "green" "Activating virtual environment..."
    source $ENV_NAME/bin/activate
fi

# Check and install required system packages
print_message "green" "Checking system dependencies..."
check_sudo

# Check if apt-get is available (for Debian/Ubuntu systems)
if command -v apt-get &> /dev/null; then
    packages=("ffmpeg" "libsndfile1" "libtag1-dev" "libchromaprint-dev")
    missing_packages=()
    
    for pkg in "${packages[@]}"; do
        if ! dpkg -l | grep -q "ii  $pkg"; then
            missing_packages+=("$pkg")
        fi
    done
    
    if [ ${#missing_packages[@]} -gt 0 ]; then
        print_message "yellow" "Installing required system libraries: ${missing_packages[*]}"
        sudo apt-get update
        sudo apt-get install -y "${missing_packages[@]}"
    else
        print_message "green" "All required system libraries are already installed."
    fi
else
    print_message "yellow" "This script is optimized for Debian/Ubuntu. You may need to manually install: ffmpeg, libsndfile, libtag, and libchromaprint."
fi

# Create a more comprehensive requirements.txt with correct versions
print_message "green" "Setting up Python dependencies..."
cat > requirements.txt << EOF
flask>=2.0.0
requests>=2.25.0
werkzeug>=2.0.0
numpy>=1.20.0
pandas>=1.3.0
matplotlib>=3.5.0
librosa>=0.9.0
spotipy>=2.19.0
pylast>=5.0.0
mutagen>=1.45.0
audioread>=2.1.9
pydub>=0.25.1
scikit-learn>=1.0.0
tqdm>=4.62.0
lxml>=4.6.0
beautifulsoup4>=4.10.0
pillow>=9.0.0
musicbrainzngs>=0.7.1
python-dotenv>=0.19.0
pyacoustid>=1.2.0
discogs-client>=2.3.0
tinytag>=1.5.0
eyeD3>=0.9.6
EOF

# Install all required packages
print_message "green" "Installing required packages..."
pip install -r requirements.txt

# Function to check if module is available
check_module() {
    python -c "import $1" 2>/dev/null
    if [ $? -eq 0 ]; then
        print_message "green" "✓ $1 is available"
        return 0
    else
        print_message "yellow" "⚠️ $1 is not available - installing..."
        pip install $1
        python -c "import $1" 2>/dev/null
        if [ $? -eq 0 ]; then
            print_message "green" "✓ $1 is now available"
            return 0
        else
            print_message "red" "✗ Failed to install $1"
            return 1
        fi
    fi
}

# Check critical modules
print_message "green" "Verifying critical modules..."
critical_modules=("flask" "logging" "musicbrainzngs" "spotipy" "pylast")
failed_modules=0

for module in "${critical_modules[@]}"; do
    if ! check_module $module; then
        failed_modules=$((failed_modules + 1))
    fi
done

# Create logs directory
print_message "green" "Setting up logging directory..."
mkdir -p $LOG_DIR
chmod 755 $LOG_DIR

# Create empty logging_config.py if it doesn't exist
if [ ! -f "logging_config.py" ]; then
    print_message "yellow" "Creating logging configuration module..."
    cat > logging_config.py << EOF
import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Define log levels
LOG_LEVELS = {
    'debug': logging.DEBUG,
    'info': logging.INFO,
    'warning': logging.WARNING,
    'error': logging.ERROR,
    'critical': logging.CRITICAL
}

def configure_logging(level='info', log_to_file=True, log_dir='logs', max_size_mb=10, backup_count=5):
    \"""
    Configure the logging system
    
    Args:
        level (str): Log level - 'debug', 'info', 'warning', 'error', 'critical'
        log_to_file (bool): Whether to log to a file
        log_dir (str): Directory for log files
        max_size_mb (int): Maximum size of log file in MB before rotation
        backup_count (int): Number of backup log files to keep
    \"""
    # Convert string level to logging level
    log_level = LOG_LEVELS.get(level.lower(), logging.INFO)
    
    # Create root logger and set level
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Clear any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler
    if log_to_file:
        # Create logs directory if it doesn't exist
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        
        # Set up rotating file handler
        file_handler = RotatingFileHandler(
            log_path / 'pump.log',
            maxBytes=max_size_mb * 1024 * 1024,
            backupCount=backup_count
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # Log configuration information
    logger = logging.getLogger('logging_config')
    logger.info(f"Logging configured with level: {level}")
    if log_to_file:
        logger.info(f"Logging to file: {os.path.abspath(log_path / 'pump.log')}")
        logger.info(f"Log rotation settings: max_size={max_size_mb}MB, backup_count={backup_count}")
    
    return root_logger

def get_logger(name):
    \"""Get a logger with the given name\"""
    return logging.getLogger(name)

def set_log_level(level):
    \"""Set the log level for all handlers\"""
    if level not in LOG_LEVELS:
        raise ValueError(f"Invalid log level: {level}. Valid levels are: {list(LOG_LEVELS.keys())}")
    
    root_logger = logging.getLogger()
    root_logger.setLevel(LOG_LEVELS[level])
    
    logger = logging.getLogger('logging_config')
    logger.info(f"Log level changed to: {level}")
EOF
fi

# Check if there were any failed critical modules
if [ $failed_modules -gt 0 ]; then
    print_message "red" "Failed to install $failed_modules critical modules. Please check your system and try again."
    exit 1
fi

# Verify that the Python files are where we expect them
print_message "green" "Verifying Python files..."
if [ ! -f "web_player.py" ]; then
    print_message "red" "Error: web_player.py not found in current directory!"
    print_message "yellow" "Current directory: $(pwd)"
    print_message "yellow" "Files in current directory: $(ls)"
    exit 1
fi

# Verify logging_config.py exists
if [ ! -f "logging_config.py" ]; then
    print_message "red" "Warning: logging_config.py not found, creating it now..."
    # The code to create logging_config.py is already in your script
fi

# Start the web player
print_message "green" "Starting Pump Web Player..."
python web_player.py

# If the server exits, wait for user input before closing
echo ""
print_message "yellow" "Server stopped. Press any key to close this window..."
read -n 1
