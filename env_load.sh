#!/bin/sh

# Name of the environment (for conda)
ENV_NAME="myenv"

if command -v conda >/dev/null 2>&1; then
    echo "Conda found. Using conda environment."
    # Check if the conda environment exists
    if conda info --envs | grep -q "^${ENV_NAME}[[:space:]]"; then
        echo "Activating existing conda environment: ${ENV_NAME}"
        conda activate "${ENV_NAME}"
    else
        echo "Creating new conda environment: ${ENV_NAME}"
        conda create -n "${ENV_NAME}" python -y
        conda activate "${ENV_NAME}"
    fi
else
    echo "Conda not found, falling back to virtual environment."
    # Determine the Python interpreter using command -v
    if command -v python3 >/dev/null 2>&1; then
        PYTHON=python3
    elif command -v python >/dev/null 2>&1; then
        PYTHON=python
    else
        echo "No Python interpreter found. Exiting."
        exit 1
    fi
    # Create the virtual environment if it does not exist
    if [ ! -d "env" ]; then
        echo "Creating virtual environment in ./env"
        $PYTHON -m venv env
    fi
    echo "Activating virtual environment..."
    . env/bin/activate
fi

# Install packages from requirements.txt
echo "Installing packages from requirements.txt..."
if pip install -r requirements.txt; then
    echo "All clear!"
else
    echo "Installation failed."
    exit 1
fi
