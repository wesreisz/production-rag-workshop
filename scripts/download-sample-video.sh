#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SAMPLES_DIR="${PROJECT_ROOT}/samples"

FOLDER_ID="1Fjtjb577U7vd3XgKdQsYAs4EBfJMdEPL"

mkdir -p "$SAMPLES_DIR"

if ! command -v gdown &>/dev/null; then
  echo "Installing gdown..."
  pip install -q gdown
fi

echo "Downloading all files from Google Drive folder..."
echo "Destination: $SAMPLES_DIR"
echo ""

gdown --folder "https://drive.google.com/drive/folders/${FOLDER_ID}" -O "$SAMPLES_DIR" --remaining-ok

echo ""
echo "Done. Downloaded files:"
ls -lh "$SAMPLES_DIR"/*.mp4 2>/dev/null || echo "No .mp4 files found"
