#!/bin/bash
# Stop the Hive daemon
echo "Stopping Hive..."
pkill -f "hive.daemon.server" 2>/dev/null
echo "Hive stopped."
