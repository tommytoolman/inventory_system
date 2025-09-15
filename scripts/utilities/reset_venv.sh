#!/bin/bash

echo "Deactivating virtual environment if active..."
deactivate 2>/dev/null || true

echo "Removing old virtual environment..."
rm -rf venv

echo "Creating new virtual environment..."
python3 -m venv venv

echo "Activating new virtual environment..."
source venv/bin/activate

echo "Upgrading pip..."
python -m pip install --upgrade pip

echo "Installing requirements..."
pip install -r requirements.txt

echo "Virtual environment has been reset and requirements installed!"
echo "To activate, run: source venv/bin/activate"

# Make the script executable:
# chmod +x reset_venv.sh

# To use it, just run:
# ./reset_venv.sh