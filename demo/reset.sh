#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$SCRIPT_DIR/start.sh"

if [[ "${1:-}" != "--yes" ]]; then
  printf 'This permanently deletes Demo sessions, workspace, config, and Context Index data.\n'
  read -r -p 'Type RESET to continue: ' confirmation
  if [[ "$confirmation" != "RESET" ]]; then
    echo "Reset cancelled."
    exit 0
  fi
fi

demo_compose down --volumes --remove-orphans
printf 'Demo containers and persistent volumes were removed.\n'
