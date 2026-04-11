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

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$REPO_ROOT" ] && [ -f "$REPO_ROOT/scripts/pre-commit" ]; then
  cp "$REPO_ROOT/scripts/pre-commit" "$REPO_ROOT/.git/hooks/pre-commit"
  chmod +x "$REPO_ROOT/.git/hooks/pre-commit"
  echo "Installed pre-commit hook"
fi
