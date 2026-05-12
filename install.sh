#!/usr/bin/env bash
# install.sh — install granola-sync as a launchd agent (macOS)
#
# Copies the script to ~/Library/Application Support/granola-sync/ so that
# launchd can read it regardless of where the repo lives (Desktop, Documents,
# and similar are restricted by macOS TCC for launchd-spawned processes).
#
# Usage:
#   ./install.sh --vault PATH [--interval MINUTES]
#
# Examples:
#   ./install.sh --vault ~/Documents/Obsidian/MyVault/Granola
#   ./install.sh --vault ~/Documents/Obsidian/MyVault/Granola --interval 30
#
# Re-run with new args to update the existing agent in place.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.granola-sync.agent"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
INSTALL_DIR="$HOME/Library/Application Support/granola-sync"

VAULT=""
INTERVAL=15

usage() {
  cat <<EOF
Usage: ./install.sh --vault PATH [--interval MINUTES]

  --vault PATH         Path to the Obsidian Granola folder (required)
  --interval MINUTES   Sync interval in minutes (default: 15)
  -h, --help           Show this help

EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --vault)    VAULT="${2:?--vault needs a value}"; shift 2 ;;
    --interval) INTERVAL="${2:?--interval needs a value}"; shift 2 ;;
    -h|--help)  usage; exit 0 ;;
    *)          echo "error: unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$VAULT" ]]; then
  echo "error: --vault is required" >&2
  usage
  exit 1
fi

if ! [[ "$INTERVAL" =~ ^[0-9]+$ ]] || [[ "$INTERVAL" -lt 1 ]]; then
  echo "error: --interval must be a positive integer (minutes), got: $INTERVAL" >&2
  exit 1
fi

VAULT="${VAULT/#\~/$HOME}"
VAULT_PARENT="$(cd "$(dirname "$VAULT")" 2>/dev/null && pwd || true)"
if [[ -z "$VAULT_PARENT" ]]; then
  echo "error: parent of vault path does not exist: $(dirname "$VAULT")" >&2
  exit 1
fi
VAULT="$VAULT_PARENT/$(basename "$VAULT")"

# Prefer Homebrew python3 over /usr/bin/python3 (the macOS system one is 3.9 and
# in a SIP-protected location, which makes Full Disk Access grants brittle).
PYTHON=""
for candidate in \
  /opt/homebrew/bin/python3.13 \
  /opt/homebrew/bin/python3.12 \
  /opt/homebrew/bin/python3.11 \
  /opt/homebrew/bin/python3 \
  /usr/local/bin/python3 \
  "$(command -v python3 || true)"; do
  if [[ -x "$candidate" ]]; then
    PYTHON="$candidate"
    break
  fi
done
if [[ -z "$PYTHON" ]]; then
  echo "error: python3 not found. Install it (e.g. \`brew install python\`) and re-run." >&2
  exit 1
fi

INTERVAL_SEC=$(( INTERVAL * 60 ))

# Copy the script to a TCC-friendly location so launchd can read it.
mkdir -p "$INSTALL_DIR/logs" "$HOME/Library/LaunchAgents"
cp -f "$SCRIPT_DIR/granola_sync.py" "$INSTALL_DIR/granola_sync.py"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$INSTALL_DIR/granola_sync.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>GRANOLA_VAULT_ROOT</key>
        <string>$VAULT</string>
    </dict>
    <key>StartInterval</key>
    <integer>$INTERVAL_SEC</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR</string>
    <key>StandardOutPath</key>
    <string>$INSTALL_DIR/logs/granola-sync.log</string>
    <key>StandardErrorPath</key>
    <string>$INSTALL_DIR/logs/granola-sync.err</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "installed: $PLIST"
echo "script:    $INSTALL_DIR/granola_sync.py"
echo "vault:     $VAULT"
echo "interval:  every $INTERVAL min"
echo "logs:      $INSTALL_DIR/logs/granola-sync.{log,err}"

# Probe the first run (triggered by RunAtLoad). If it fails with a PermissionError
# from macOS TCC, the vault is in a protected folder and python3 needs Full Disk Access.
echo
echo "Waiting for first run..."
ERR_LOG="$INSTALL_DIR/logs/granola-sync.err"
OUT_LOG="$INSTALL_DIR/logs/granola-sync.log"
deadline=$(( $(date +%s) + 30 ))
while [[ $(date +%s) -lt $deadline ]]; do
  if grep -q "Done\." "$OUT_LOG" 2>/dev/null; then
    echo "first run OK. Sync is now active."
    echo
    echo "Run ./uninstall.sh to remove."
    exit 0
  fi
  if grep -q "PermissionError\|Operation not permitted" "$ERR_LOG" 2>/dev/null; then
    echo
    echo "First run failed with PermissionError (macOS TCC)."
    echo "Your vault lives in a folder that launchd cannot access without"
    echo "Full Disk Access. Grant it once:"
    echo
    echo "  1. Open: System Settings → Privacy & Security → Full Disk Access"
    echo "  2. Click + and add this exact path:"
    echo "       $PYTHON"
    echo "  3. Re-run: ./install.sh --vault \"$VAULT\" --interval $INTERVAL"
    echo
    echo "Tail $ERR_LOG to see the raw error."
    exit 1
  fi
  sleep 1
done
echo "first run did not finish within 30s — check logs:"
echo "  $OUT_LOG"
echo "  $ERR_LOG"
echo
echo "Run ./uninstall.sh to remove."
