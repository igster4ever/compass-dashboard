#!/bin/sh
# Launcher: runs compass-dashboard.py under the first Python >= 3.10 it can find, so skill text
# never hardcodes an interpreter path. Override with COMPASS_PYTHON=/path/to/python.
here=$(cd "${0%/*}" && pwd)
for py in "${COMPASS_PYTHON:-}" python3.14 python3.13 python3.12 python3.11 python3.10 python3 \
          /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  [ -n "$py" ] || continue
  command -v "$py" >/dev/null 2>&1 || continue
  "$py" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null || continue
  exec "$py" "$here/compass-dashboard.py" "$@"
done
echo "compass-dashboard: no Python >= 3.10 found on PATH; install one or set COMPASS_PYTHON" >&2
exit 1
