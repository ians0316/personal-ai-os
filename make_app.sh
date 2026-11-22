#!/bin/sh
# Build "Personal AI OS.app" in dist/. Double-click it to open the desktop app.
# The app runs this project folder, so re-run this script if you move the folder.
set -e
cd "$(dirname "$0")"
ROOT="$(pwd)"
APP="dist/Personal AI OS.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/MacOS/PersonalAIOS" <<LAUNCH
#!/bin/sh
cd "$ROOT"
# Pick up an API key saved in .env (one line: ANTHROPIC_API_KEY=sk-ant-...)
[ -f .env ] && set -a && . ./.env && set +a
exec "$ROOT/.venv/bin/python" desktop.py >> "$ROOT/data/desktop.log" 2>&1
LAUNCH
chmod +x "$APP/Contents/MacOS/PersonalAIOS"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Personal AI OS</string>
  <key>CFBundleDisplayName</key><string>Personal AI OS</string>
  <key>CFBundleIdentifier</key><string>local.personal-ai-os</string>
  <key>CFBundleVersion</key><string>0.6</string>
  <key>CFBundleShortVersionString</key><string>0.6</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>PersonalAIOS</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>Personal AI OS listens while you hold the talk button, and turns your voice into text on this Mac.</string>
</dict>
</plist>
PLIST
mkdir -p data
echo "Built: $ROOT/$APP"
echo "Tip: drag it to your Dock. Put your API key in $ROOT/.env as ANTHROPIC_API_KEY=..."
