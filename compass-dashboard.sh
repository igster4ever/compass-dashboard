#!/usr/bin/env bash
# compass-dashboard — generate and open the compass HTML dashboard
# Usage: compass-dashboard [--namespace <ns>] [--output <path>] [--no-open]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/scripts/compass-dashboard.py" "$@"
