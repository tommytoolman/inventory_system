#!/bin/bash
# Script to display the project directory tree, excluding common unwanted folders.

echo "Generating project tree structure..."
tree -I 'venv|__pycache__|.git|.vscode|node_modules'
echo "Done."
