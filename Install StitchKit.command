#!/bin/bash
# One-time setup for StitchKit. Safe to run again if something went wrong.
cd "$(dirname "$0")" || exit 1
HERE="$(pwd)"
echo ""
echo "=== Installing StitchKit ==="
echo "This needs the internet and takes a few minutes the first time."
echo ""
# let the other double-click scripts in this folder open without macOS blocking them
xattr -dr com.apple.quarantine "$HERE" 2>/dev/null
chmod +x "$HERE"/*.command 2>/dev/null

export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "Getting uv, a small tool that installs Python for StitchKit..."
  curl -LsSf https://astral.sh/uv/install.sh | sh || { echo "Could not download uv. Check your internet connection."; read -r -p "Press Return to close."; exit 1; }
  export PATH="$HOME/.local/bin:$PATH"
fi

rm -rf "$HERE/.venv"
uv venv --python 3.12 "$HERE/.venv" || { echo "Python setup failed."; read -r -p "Press Return to close."; exit 1; }
uv pip install --python "$HERE/.venv" -r "$HERE/requirements.txt" || { echo "Installing parts failed."; read -r -p "Press Return to close."; exit 1; }
uv pip install --python "$HERE/.venv" --no-deps -r "$HERE/requirements-nodeps.txt" || { echo "Installing parts failed."; read -r -p "Press Return to close."; exit 1; }

echo ""
echo "Checking that everything works (about a minute)..."
if "$HERE/.venv/bin/python" "$HERE/tests/selftest.py"; then
  echo ""
  echo "=== StitchKit is installed. ==="
  echo "Double-click 'Open StitchKit.command' to start it."
else
  echo ""
  echo "The self-test failed. Send the text above to Claude for help."
fi
echo ""
read -r -p "Press Return to close this window."
