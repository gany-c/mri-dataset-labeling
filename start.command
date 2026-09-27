#!/bin/zsh
set -e
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo 'First run: python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt'
  exit 1
fi
echo 'Open http://127.0.0.1:8765 in your browser. Press Ctrl+C to stop.'
export KNEE_DICOM_ROOT="${KNEE_DICOM_ROOT:-$HOME/rsna-data/verified-studies}"
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
