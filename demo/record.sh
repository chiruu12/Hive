#!/usr/bin/env bash
# Record a demo GIF of hive demo survival.
#
# Requires one of:
#   - vhs (https://github.com/charmbracelet/vhs)
#   - asciinema + agg (https://github.com/asciinema/agg)
#
# Usage:
#   ./demo/record.sh

set -euo pipefail

OUT="demo/hive-demo.gif"

if command -v vhs &>/dev/null; then
    echo "Recording with vhs..."
    cat > demo/demo.tape <<'TAPE'
Output demo/hive-demo.gif
Set Width 1200
Set Height 600
Set FontSize 14
Set Theme "Catppuccin Mocha"

Type "hive demo survival"
Enter
Sleep 95s
TAPE
    vhs demo/demo.tape
    echo "GIF saved to $OUT"

elif command -v asciinema &>/dev/null; then
    echo "Recording with asciinema..."
    CAST="demo/demo.cast"
    asciinema rec "$CAST" -c "hive demo survival" --overwrite
    if command -v agg &>/dev/null; then
        agg "$CAST" "$OUT"
        echo "GIF saved to $OUT"
    else
        echo "Cast saved to $CAST. Install agg to convert to GIF."
    fi

else
    echo "Install vhs or asciinema to record demos."
    echo "  brew install vhs"
    echo "  brew install asciinema"
    exit 1
fi
