#!/usr/bin/env bash
###
# Run pytest for tanat-utils
# Usage:
#   bash scripts/test.sh
###
set -euo pipefail

# Get the project root directory
SELF=$(readlink -f "${BASH_SOURCE[0]}")
DIR=${SELF%/*/*}

cd -- "$DIR"

# Setup virtual environment if needed
if [[ ! -e ./venv ]]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
  source ./venv/bin/activate
  pip install --upgrade pip
  pip install -e ".[test]"
else
  source ./venv/bin/activate
fi

echo "Running tests..."
pytest -vv --import-mode=importlib --cov=src/tanat_utils --cov-report=term tests/
