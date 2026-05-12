#!/usr/bin/env bash
# uninstall.sh — remove the granola-sync launchd agent (macOS)
#
# By default this only removes the launchd agent and plist. The installed
# script copy, cached tokens, and logs at ~/Library/Application Support/granola-sync/
# are left in place so re-installing later doesn't have to re-bootstrap tokens.
# Pass --purge to remove them too.
set -euo pipefail

LABEL="com.granola-sync.agent"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
INSTALL_DIR="$HOME/Library/Application Support/granola-sync"

PURGE=0
for arg in "$@"; do
  case "$arg" in
    --purge)   PURGE=1 ;;
    -h|--help) echo "Usage: ./uninstall.sh [--purge]"; exit 0 ;;
    *)         echo "error: unknown arg: $arg" >&2; exit 1 ;;
  esac
done

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true

if [[ -f "$PLIST" ]]; then
  rm -f "$PLIST"
  echo "removed: $PLIST"
else
  echo "no plist at $PLIST"
fi

if [[ "$PURGE" -eq 1 && -d "$INSTALL_DIR" ]]; then
  rm -rf "$INSTALL_DIR"
  echo "removed: $INSTALL_DIR"
fi
