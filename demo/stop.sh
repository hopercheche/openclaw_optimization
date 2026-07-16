#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$SCRIPT_DIR/start.sh"

demo_compose down --remove-orphans
printf 'Demo containers stopped. Persistent volumes were preserved.\n'
