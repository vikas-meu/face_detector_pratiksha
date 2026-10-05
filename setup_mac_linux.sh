#!/usr/bin/env bash
# One-step setup for macOS / Linux: creates a virtual environment and installs OpenCV.
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 was not found. Install Python 3 first (see README.md)."
    exit 1
fi

echo "Creating virtual environment..."
python3 -m venv venv

echo "Installing packages..."
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

echo "Downloading face models..."
python face_detector.py --download-models

echo
echo "Setup complete! Start the detector with:"
echo "  source venv/bin/activate && python face_detector.py"
