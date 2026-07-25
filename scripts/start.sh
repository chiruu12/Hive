#!/bin/bash
# Start the Hive daemon in the foreground. Stop it with Ctrl+C or
# `hive stop` (or scripts/stop.sh) from another terminal.
hive init 2>/dev/null
exec hive start "$@"
