#!/bin/bash
# ShiftWheel installer for macOS.
#   curl -fsSL https://raw.githubusercontent.com/Aditya-Prakash-047/ShiftWheel-releases/main/install-mac.sh | bash
# Downloads the right build for this Mac from the latest GitHub release, installs it to
# /Applications and opens it. Files fetched by curl aren't marked "downloaded from the
# internet", so macOS doesn't show the "could not verify" warning. Read it first if you like —
# it's short.
set -euo pipefail

REPO="Aditya-Prakash-047/ShiftWheel-releases"
case "$(uname -m)" in
  arm64) ASSET="ShiftWheel-mac-apple-silicon.dmg" ;;
  *)     ASSET="ShiftWheel-mac-intel.dmg" ;;
esac
URL="https://github.com/$REPO/releases/latest/download/$ASSET"
TMP="$(mktemp -d)"
trap 'hdiutil detach "$TMP/mnt" -quiet 2>/dev/null || true; rm -rf "$TMP"' EXIT

echo "→ Downloading $ASSET"
curl -fL --progress-bar "$URL" -o "$TMP/ShiftWheel.dmg"

echo "→ Installing to /Applications"
hdiutil attach "$TMP/ShiftWheel.dmg" -mountpoint "$TMP/mnt" -nobrowse -quiet
osascript -e 'quit app "ShiftWheel"' 2>/dev/null || true
pkill -x ShiftWheel 2>/dev/null || true
DEST="/Applications/ShiftWheel.app"
if [ -w /Applications ]; then
  rm -rf "$DEST"; ditto "$TMP/mnt/ShiftWheel.app" "$DEST"
else
  sudo rm -rf "$DEST"; sudo ditto "$TMP/mnt/ShiftWheel.app" "$DEST"
fi
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true

echo "→ Opening ShiftWheel (look for it in the menu bar)"
open "$DEST"
echo "✓ Done. Drag any file in Finder and press Shift."
