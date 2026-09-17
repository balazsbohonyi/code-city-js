#!/usr/bin/env bash
# Thin wrapper so the recipe matches the Java guide.
#   ./generate.sh [REPO] [OUT]
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$DIR/generate.py" "$@"
