#!/bin/bash
# Start the Hive daemon
echo "Starting Hive..."
hive init 2>/dev/null
python -m hive.daemon.server &
echo "Hive daemon running. Use 'hive status' to check agents."
