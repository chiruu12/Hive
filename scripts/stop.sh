#!/bin/bash
# Stop the Hive daemon via the CLI's PID-file-based graceful shutdown.
# Must be run from the directory containing .hive/ (same as `hive start`).
exec hive stop "$@"
