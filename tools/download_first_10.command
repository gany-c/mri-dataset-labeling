#!/bin/zsh
set -e
set -o pipefail
TOOLS_DIR="${0:A:h}"
DATA_ROOT="$HOME/rsna-data"
mkdir -p "$DATA_ROOT"
cd "$DATA_ROOT"
if [[ ! -x .download-env/bin/python ]]; then
  python3 -m venv .download-env
  .download-env/bin/python -m pip install -r "$TOOLS_DIR/requirements-download.txt"
fi
.download-env/bin/python -u "$TOOLS_DIR/download_studies.py" --root "$DATA_ROOT" --count 10 2>&1 | tee -a download.log
