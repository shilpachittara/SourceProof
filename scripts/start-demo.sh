#!/usr/bin/env bash
# Back-compat: same as make start / scripts/start.sh
exec "$(dirname "$0")/start.sh" "$@"
