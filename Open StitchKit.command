#!/bin/bash
cd "$(dirname "$0")" || exit 1
if [ ! -x ".venv/bin/python" ]; then
  echo "StitchKit is not installed yet. Double-click 'Install StitchKit.command' first."
  read -r -p "Press Return to close."
  exit 1
fi
echo "Starting StitchKit... your browser will open in a moment."
exec .venv/bin/python app.py
