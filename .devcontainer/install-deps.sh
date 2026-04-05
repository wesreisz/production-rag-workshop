#!/usr/bin/env bash
set -euo pipefail

pip install --upgrade pip

for req in modules/*/requirements.txt; do
  echo "Installing $req"
  pip install -r "$req"
done

for req in modules/*/dev-requirements.txt; do
  echo "Installing $req"
  pip install -r "$req"
done
